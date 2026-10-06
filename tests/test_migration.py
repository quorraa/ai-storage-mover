from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from ai_storage_mover.engine import Engine, link_root, run_lock
from ai_storage_mover.model import CLEANUP_PHRASE, MigrationError, atomic_json, make_plan, protected, validate
from ai_storage_mover.references import map_path, repoint_codex, repoint_files, repoint_claude, codex_ui_paths
from ai_storage_mover.runtime import launch, settings


class Fixture(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1] / '.runs'
        self.base.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='fixture-', dir=self.base))
        self.source, self.target = self.root / 'source', self.root / 'target'
        self.source.mkdir()
        (self.source / 'hello.txt').write_text('original', encoding='utf-8')
        (self.source / 'nested').mkdir()
        (self.source / 'nested' / 'asset.bin').write_bytes(b'\0\1\2')
        self.plan = make_plan([(self.source, self.target, 'project')], self.root / 'storage', reserve_bytes=0)

    def tearDown(self):
        resolved = self.root.resolve()
        if not resolved.is_relative_to(self.base.resolve()) or resolved == self.base.resolve():
            raise RuntimeError('Fixture cleanup escaped its reviewed test root')
        # Modern Python rmtree does not descend Windows junctions.
        shutil.rmtree(self.root)

    def engine(self):
        return closing(Engine(self.plan))

    def apply(self):
        with self.engine() as engine:
            engine.apply(apps_closed=True)

    def test_copy_cutover_and_retire(self):
        self.apply()
        with self.engine() as engine:
            self.assertEqual((self.target / 'hello.txt').read_text(), 'original')
            self.assertTrue(engine.backup(self.plan['roots'][0]).exists())
            engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            self.assertFalse(engine.backup(self.plan['roots'][0]).exists())
            self.assertEqual((self.source / 'hello.txt').read_text(), 'original')
            status = json.loads((engine.run / 'status.json').read_text())
            self.assertEqual(status['percent'], 100)
            self.assertEqual(status['phase'], 'done')

    def test_existing_equal_metadata_corruption_is_detected(self):
        self.target.mkdir()
        bad = self.target / 'hello.txt'
        bad.write_text('corrupt!', encoding='utf-8')
        original = self.source / 'hello.txt'
        info = original.stat()
        os.utime(bad, ns=(info.st_atime_ns, info.st_mtime_ns))
        with self.engine() as engine:
            engine.stage()
            self.assertEqual(bad.read_text(), 'original')
            archived = list((engine.run / 'conflicts').rglob('hello.txt'))
            self.assertEqual(archived[0].read_text(), 'corrupt!')

    def test_metadata_policy_is_explicit_and_receipted(self):
        self.plan['verification'] = 'metadata'
        self.target.mkdir()
        shutil.copy2(self.source / 'hello.txt', self.target / 'hello.txt')
        with self.engine() as engine:
            receipt = engine.stage()
            self.assertEqual(receipt['policy'], 'metadata')
            self.assertGreaterEqual(receipt['reused'], 1)

    def test_journal_avoids_rehashing_verified_unchanged_files(self):
        with self.engine() as engine:
            first = engine.stage()
            with patch('ai_storage_mover.engine.sha', side_effect=AssertionError('Unchanged content was rehashed')):
                second = engine.stage()
            self.assertEqual(first['copied'], 2)
            self.assertEqual(second['copied'], 0)
            self.assertEqual(second['reused'], 2)

    def test_apply_reconciles_changes_after_stage(self):
        with self.engine() as engine:
            engine.stage()
            (self.source / 'hello.txt').write_text('changed later', encoding='utf-8')
            engine.apply(apps_closed=True)
            self.assertEqual((self.target / 'hello.txt').read_text(), 'changed later')

    def test_journal_detects_replaced_destination_with_equal_metadata(self):
        with self.engine() as engine:
            engine.stage()
            target = self.target / 'hello.txt'
            info = target.stat()
            replacement = target.with_name('replacement.txt')
            replacement.write_text('corrupt!')
            os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns))
            os.replace(replacement, target)
            engine.stage()
            self.assertEqual(target.read_text(), 'original')

    def test_cutover_requires_closed_writers_declaration(self):
        with self.engine() as engine:
            with self.assertRaises(MigrationError):
                engine.apply()
            self.assertFalse(self.source.is_symlink())

    def test_interrupted_cutover_resumes_without_recopying_linked_root(self):
        second = self.root / 'second'
        second.mkdir()
        (second / 'second.txt').write_text('two')
        self.plan = make_plan([(self.source, self.target, 'project'), (second, self.root / 'second-target', 'profile')], self.root / 'storage', reserve_bytes=0)
        original = link_root

        def fail_second(source, target):
            if Path(source) == second:
                raise OSError('simulated second-root failure')
            return original(source, target)

        with self.engine() as engine:
            with patch('ai_storage_mover.engine.link_root', side_effect=fail_second), self.assertRaises(OSError):
                engine.apply(apps_closed=True)
        with self.engine() as engine:
            engine.apply(apps_closed=True)
            self.assertTrue(engine.state['cutover_complete'])
            self.assertEqual((second / 'second.txt').read_text(), 'two')

    def test_recreated_source_is_never_overwritten(self):
        def recreate(source, target):
            Path(source).mkdir()
            (Path(source) / 'new.txt').write_text('writer created this')
            raise OSError('source recreated')
        with self.engine() as engine:
            with patch('ai_storage_mover.engine.link_root', side_effect=recreate), self.assertRaises(OSError):
                engine.apply(apps_closed=True)
            self.assertEqual((self.source / 'new.txt').read_text(), 'writer created this')
            self.assertTrue(engine.backup(self.plan['roots'][0]).exists())
            with self.assertRaises(MigrationError):
                engine.apply(apps_closed=True)

    def test_unexpected_backup_entry_stops_cleanup_before_deletion(self):
        self.apply()
        with self.engine() as engine:
            backup = engine.backup(self.plan['roots'][0])
            (backup / 'new-important.txt').write_text('keep me')
            with self.assertRaises(MigrationError):
                engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            self.assertEqual((backup / 'hello.txt').read_text(), 'original')
            self.assertTrue((backup / 'new-important.txt').exists())

    def test_modified_backup_is_retained(self):
        self.apply()
        with self.engine() as engine:
            backup = engine.backup(self.plan['roots'][0])
            (backup / 'hello.txt').write_text('unverified changes')
            with self.assertRaises(MigrationError):
                engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            self.assertTrue(backup.exists())

    def test_missing_destination_entry_blocks_retirement(self):
        self.apply()
        (self.target / 'hello.txt').unlink()
        with self.engine() as engine:
            with self.assertRaises(MigrationError):
                engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            self.assertTrue(engine.backup(self.plan['roots'][0]).exists())

    def test_interrupted_retirement_resumes(self):
        self.apply()
        original = os.unlink
        calls = 0

        def interrupt(path, *args, **kwargs):
            nonlocal calls
            if '.ai-mover-backup-' in str(path):
                calls += 1
                if calls == 2:
                    raise OSError('simulated cleanup interruption')
            return original(path, *args, **kwargs)

        with self.engine() as engine:
            with patch('ai_storage_mover.engine.os.unlink', side_effect=interrupt), self.assertRaises(OSError):
                engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            engine.fail(RuntimeError('simulated interruption'))
        with self.engine() as engine:
            engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
            self.assertTrue(engine.state['retired'])
            self.assertEqual((self.target / 'hello.txt').read_text(), 'original')

    def test_cleanup_never_follows_external_directory_link(self):
        external = self.root / 'external'
        external.mkdir()
        (external / 'keep.txt').write_text('outside selected root')
        link_root(self.source / 'external-link', external)
        self.apply()
        with self.engine() as engine:
            engine.retire(self.plan['id'], acknowledgment=CLEANUP_PHRASE)
        self.assertEqual((external / 'keep.txt').read_text(), 'outside selected root')

    def test_wrong_confirmation_id_refuses_cleanup(self):
        self.apply()
        with self.engine() as engine:
            with self.assertRaises(MigrationError):
                engine.retire('wrong', acknowledgment=CLEANUP_PHRASE)
            self.assertTrue(engine.backup(self.plan['roots'][0]).exists())

    def test_changed_plan_refuses_reuse_of_journal(self):
        with self.engine() as engine:
            engine.stage()
        self.plan['workers'] += 1
        with self.assertRaises(MigrationError):
            Engine(self.plan)

    def test_changed_volume_refuses_cutover(self):
        with self.engine() as engine:
            engine.state['roots'][self.plan['roots'][0]['id']] = {'destination_volume': 'different-volume'}
            engine.save()
            with self.assertRaises(MigrationError):
                engine.apply(apps_closed=True)
            self.assertTrue((self.source / 'hello.txt').exists())

    def test_rollback_preserves_later_destination_writes(self):
        self.apply()
        (self.target / 'hello.txt').write_text('later destination edit')
        with self.engine() as engine:
            engine.rollback(apps_closed=True)
        self.assertEqual((self.source / 'hello.txt').read_text(), 'original')
        self.assertEqual((self.target / 'hello.txt').read_text(), 'later destination edit')

    def test_overlapping_roots_are_rejected(self):
        with self.assertRaises(MigrationError):
            make_plan([(self.source, self.source / 'nested', 'project')], self.root / 'storage')

    def test_journal_inside_root_is_rejected(self):
        self.plan['run_dir'] = str(self.source / '.journal')
        with self.assertRaises(MigrationError):
            validate(self.plan)

    def test_concurrent_writer_is_rejected(self):
        with run_lock(Path(self.plan['run_dir'])):
            with self.assertRaises(MigrationError):
                with run_lock(Path(self.plan['run_dir'])):
                    pass

    def test_parallel_copy_reservations_protect_remaining_space(self):
        self.target.mkdir()
        self.plan['reserve_bytes'] = 100
        usage = shutil._ntuple_diskusage(2000, 1000, 1000)
        with self.engine() as engine, patch('ai_storage_mover.engine.shutil.disk_usage', return_value=usage):
            with engine.copy_space(self.target / 'first.bin', 700):
                with self.assertRaises(MigrationError):
                    with engine.copy_space(self.target / 'second.bin', 300):
                        self.fail('Concurrent reservations must include the first worker')
            with engine.copy_space(self.target / 'second.bin', 300):
                pass

    def test_runtime_writes_temp_to_storage_without_mutating_parent(self):
        runtime = settings(self.root / 'runtime-storage')
        original = os.environ.get('TEMP')
        output = self.root / 'temp-proof.json'
        code = 'import tempfile,json,pathlib; p=tempfile.NamedTemporaryFile(delete=False); p.write(b"proof"); p.close(); pathlib.Path(' + repr(str(output)) + ').write_text(json.dumps({"temp":tempfile.gettempdir(),"file":p.name}))'
        self.assertEqual(launch(runtime, [sys.executable, '-c', code]), 0)
        proof = json.loads(output.read_text())
        self.assertEqual(Path(proof['temp']).resolve(), Path(runtime['environment']['TEMP']).resolve())
        self.assertEqual(Path(proof['file']).read_bytes(), b'proof')
        self.assertEqual(os.environ.get('TEMP'), original)

    def test_extended_path_mapping_and_component_boundary(self):
        roots = [{'source': r'C:\Projects\AnyName', 'destination': r'D:\AI\Projects\AnyName'}]
        self.assertEqual(map_path(r'\\?\C:\Projects\AnyName\work', roots), r'\\?\D:\AI\Projects\AnyName\work')
        self.assertEqual(map_path(r'C:/Projects/AnyName/work', roots), r'D:\AI\Projects\AnyName\work')
        self.assertEqual(map_path(r'C:\Projects\AnyNameOther\work', roots), r'C:\Projects\AnyNameOther\work')

    def test_codex_adapter_changes_directory_fields_not_history(self):
        profile = self.root / 'profile'
        profile.mkdir()
        with closing(sqlite3.connect(profile / 'state_5.sqlite')) as db:
            db.execute('CREATE TABLE threads (id TEXT,cwd TEXT,message TEXT,rollout_path TEXT,agent_path TEXT)')
            db.execute('CREATE TABLE project_roots (project_id TEXT,position INTEGER,path TEXT)')
            db.execute('INSERT INTO threads VALUES (?,?,?,?,?)', ('chat', str(self.source), 'historical source reference ' + str(self.source), str(self.source / 'session.jsonl'), None))
            db.execute('INSERT INTO project_roots VALUES (?,?,?)', ('project', 0, str(self.source)))
            db.commit()
        counts = repoint_codex(self.plan, profile)
        self.assertEqual(counts['threads'], 1)
        self.assertEqual(counts['threads.rollout_path'], 1)
        self.assertEqual(counts['threads.agent_path'], 0)
        with closing(sqlite3.connect(profile / 'state_5.sqlite')) as db:
            row = db.execute('SELECT cwd,message,rollout_path,agent_path FROM threads').fetchone()
            self.assertEqual(row[0], str(self.target))
            self.assertIn(str(self.source), row[1])
            self.assertEqual(row[2], str(self.target / 'session.jsonl'))
            self.assertIsNone(row[3])

    def test_explicit_json_repoint_creates_backup(self):
        config = self.root / 'settings.json'
        config.write_text(json.dumps({'cwd': str(self.source)}))
        changes = repoint_files(self.plan, [config])
        self.assertEqual(json.loads(config.read_text())['cwd'], str(self.target))
        self.assertEqual(json.loads(Path(changes[0]['backup']).read_text())['cwd'], str(self.source))

    def test_codex_cached_import_and_tab_paths_preserve_messages(self):
        atoms = {
            'external-agent-import-discovery:claude-code': {'result': {'items': [{'cwd': str(self.source), 'path': str(self.source / 'session.jsonl'), 'title': str(self.source)}]}},
            'thread-tab-routes-v1:chat': {'routes': [{'params': {'path': str(self.source / 'file.txt'), 'prompt': str(self.source)}}]},
            'unrelated-history': {'path': str(self.source)},
        }
        result = codex_ui_paths({'electron-persisted-atom-state': atoms}, self.plan['roots'])['electron-persisted-atom-state']
        imported = result['external-agent-import-discovery:claude-code']['result']['items'][0]
        self.assertEqual(imported['cwd'], str(self.target))
        self.assertEqual(imported['path'], str(self.target / 'session.jsonl'))
        self.assertEqual(imported['title'], str(self.source))
        params = result['thread-tab-routes-v1:chat']['routes'][0]['params']
        self.assertEqual(params['path'], str(self.target / 'file.txt'))
        self.assertEqual(params['prompt'], str(self.source))
        self.assertEqual(result['unrelated-history']['path'], str(self.source))

    def test_claude_desktop_paths_preserve_session_prompt_and_history(self):
        desktop = self.root / 'desktop'
        session = desktop / 'claude-code-sessions' / 'account' / 'organization' / 'local_example.json'
        session.parent.mkdir(parents=True)
        session.write_text(json.dumps({'cwd': str(self.source), 'originCwd': str(self.source),
                                      'worktreePath': str(self.source / 'worktree'),
                                      'gitAnchors': [{'gitRoot': str(self.source), 'commonDir': str(self.source / '.git')}],
                                      'sessionPermissionUpdates': [{'directories': [str(self.source)], 'mode': 'default'}],
                                      'promptAppendSnapshot': str(self.source),
                                      'completedTurns': [{'cwd': str(self.source), 'message': 'keep me'}]}))
        config = desktop / 'claude_desktop_config.json'
        config.write_text(json.dumps({'preferences': {'remoteSessionFolderGrants': {'session': [str(self.source)]},
                                                        'epitaxyPrefs': {'preferredPreviewServers': {str(self.source): 'dev'}}}}))
        temp_roots = desktop / 'git-shadow' / 'cli-temp-roots.json'
        temp_roots.parent.mkdir()
        temp_roots.write_text(json.dumps([str(self.source / 'temp')]))
        changes = repoint_claude(self.plan, desktop=desktop)
        result = json.loads(session.read_text())
        self.assertEqual(result['cwd'], str(self.target))
        self.assertEqual(result['worktreePath'], str(self.target / 'worktree'))
        self.assertEqual(result['gitAnchors'][0]['gitRoot'], str(self.target))
        self.assertEqual(result['sessionPermissionUpdates'][0]['directories'], [str(self.target)])
        self.assertEqual(result['sessionPermissionUpdates'][0]['mode'], 'default')
        self.assertEqual(result['promptAppendSnapshot'], str(self.source))
        self.assertEqual(result['completedTurns'][0]['cwd'], str(self.source))
        self.assertEqual(json.loads(config.read_text())['preferences']['remoteSessionFolderGrants']['session'], [str(self.target)])
        self.assertEqual(json.loads(temp_roots.read_text()), [str(self.target / 'temp')])
        self.assertEqual(len(changes), 3)
        saved_session = next(item['backup'] for item in changes if item['path'] == str(session))
        self.assertEqual(json.loads(Path(saved_session).read_text())['cwd'], str(self.source))

    def test_system_and_package_paths_are_protected(self):
        for value in (r'C:\Windows\System32', r'E:\WindowsApps\Vendor', r'C:\Users\A\AppData\Local\Packages\Vendor'):
            self.assertTrue(protected(value))
        self.assertFalse(protected(r'C:\Projects\Windows\MyAgent'))


if __name__ == '__main__':
    unittest.main()
