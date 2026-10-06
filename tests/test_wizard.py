from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ai_storage_mover.discovery import candidates, project_suggestions, scan_folder
from ai_storage_mover.engine import Engine
from ai_storage_mover.model import CLEANUP_PHRASE, MigrationError, make_plan
from ai_storage_mover.native import command, copy_new_tree
from ai_storage_mover.wizard import backups, cleanup, create_session, load_session, migrate, save_session, setup_command


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.runs = Path(__file__).resolve().parents[1] / '.runs'
        self.runs.mkdir(exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='wizard-', dir=self.runs))
        self.source = self.base / 'any project name'
        self.source.mkdir()
        (self.source / 'file.txt').write_text('original')

    def tearDown(self):
        assert self.base.resolve().parent == self.runs.resolve()
        shutil.rmtree(self.base)

    def session(self):
        return create_session([self.source], self.base / 'storage', reserve_bytes=0)

    def test_saved_session_retains_originals_and_later_cleanup_needs_phrase(self):
        session = self.session()
        migrate(session, configure_windows=False)
        original = Path(backups(session)[0])
        self.assertEqual((original / 'file.txt').read_text(), 'original')
        restored = load_session(Path(session['plan']['run_dir']) / 'wizard.local.json')
        self.assertEqual(restored['status'], 'complete')
        for phrase, tested in ((session['plan']['id'], True), (CLEANUP_PHRASE, False), ('', True)):
            with self.assertRaises(MigrationError):
                cleanup(restored, phrase, tested=tested, configure_windows=False)
            self.assertTrue(original.exists())
        cleanup(restored, CLEANUP_PHRASE, tested=True, configure_windows=False)
        self.assertFalse(original.exists())
        self.assertEqual(Path(session['plan']['roots'][0]['destination'], 'file.txt').read_text(), 'original')

    def test_fast_corrupt_target_blocks_all_roots_before_any_delete(self):
        second = self.base / 'second'
        second.mkdir()
        (second / 'file.txt').write_text('also original')
        session = create_session([self.source, second], self.base / 'storage', reserve_bytes=0)
        migrate(session, configure_windows=False)
        target = Path(session['plan']['roots'][1]['destination']) / 'file.txt'
        before = target.stat()
        target.write_text('is corrupted!')  # Same size as 'also original'.
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(MigrationError):
            cleanup(session, CLEANUP_PHRASE, tested=True, configure_windows=False)
        for old in backups(session):
            self.assertTrue((Path(old) / 'file.txt').exists())

    def test_changed_later_destination_keeps_original_snapshot(self):
        session = self.session()
        migrate(session, configure_windows=False)
        Path(session['plan']['roots'][0]['destination'], 'file.txt').write_text('new edit')
        with self.assertRaises(MigrationError):
            cleanup(session, CLEANUP_PHRASE, tested=True, configure_windows=False)
        self.assertEqual((Path(backups(session)[0]) / 'file.txt').read_text(), 'original')

    def test_hash_verified_copy_is_rehashed_before_destructive_cleanup(self):
        session = create_session([self.source], self.base / 'storage', verify_contents=True, reserve_bytes=0)
        migrate(session, configure_windows=False)
        target = Path(session['plan']['roots'][0]['destination']) / 'file.txt'
        before = target.stat()
        target.write_text('corrupt!')
        os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
        with self.assertRaises(MigrationError):
            cleanup(session, CLEANUP_PHRASE, tested=True, configure_windows=False)
        self.assertEqual((Path(backups(session)[0]) / 'file.txt').read_text(), 'original')

    def test_core_retire_cannot_bypass_typed_acknowledgment(self):
        session = self.session()
        with closing(Engine(session['plan'])) as engine:
            engine.apply(apps_closed=True)
            with self.assertRaises(MigrationError):
                engine.retire(session['plan']['id'])
        self.assertTrue(Path(backups(session)[0]).exists())

    def test_optional_temp_overrides_are_scoped_and_persisted(self):
        temp = self.base / 'custom-temp'
        session = create_session([self.source], self.base / 'storage', tools_temp=temp, reserve_bytes=0)
        save_session(session)
        loaded = load_session(Path(session['plan']['run_dir']) / 'plan.local.json')
        self.assertEqual(loaded['runtime']['environment']['TEMP'], str(temp))
        self.assertEqual(loaded['runtime']['environment']['TMP'], str(temp))
        self.assertNotIn('CODEX_HOME', loaded['runtime']['environment'])

    def test_provider_with_custom_profile_name_is_identified(self):
        profile = self.base / 'custom-profile'
        profile.mkdir()
        item = dict(source=str(profile), slot='Profiles/codex', category='profile', provider='codex')
        session = create_session([self.source], self.base / 'storage', [item], reserve_bytes=0)
        self.assertEqual(session['plan']['roots'][1]['provider'], 'codex')
        self.assertEqual(session['runtime']['environment']['CODEX_HOME'], str(self.base / 'storage' / 'Profiles' / 'codex'))

    def test_profile_inside_selected_project_uses_canonical_mapped_location(self):
        profile = self.source / '.codex'
        profile.mkdir()
        item = dict(source=str(profile), slot='Profiles/codex', category='profile', provider='codex')
        session = create_session([self.source], self.base / 'storage', [item], reserve_bytes=0)
        self.assertEqual(len(session['plan']['roots']), 1)
        self.assertEqual(session['runtime']['environment']['CODEX_HOME'], str(Path(session['plan']['roots'][0]['destination']) / '.codex'))

    def test_cache_inside_project_is_not_recopied_or_left_unconfigured(self):
        cache = self.source / 'cache'
        cache.mkdir()
        item = dict(source=str(cache), slot='Cache/uv/cache', category='cache')
        session = create_session([self.source], self.base / 'storage', [item], reserve_bytes=0)
        self.assertEqual(len(session['plan']['roots']), 1)
        self.assertEqual(session['runtime']['environment']['UV_CACHE_DIR'], str(Path(session['plan']['roots'][0]['destination']) / 'cache'))

    def test_source_and_destination_names_do_not_allow_overlaps(self):
        other = self.base / 'other' / self.source.name
        other.mkdir(parents=True)
        with self.assertRaises(MigrationError):
            create_session([self.source, other], self.base / 'storage')
        session = create_session([self.source, other], self.base / 'storage', destinations={str(other): str(self.base / 'different-project')})
        self.assertEqual(session['plan']['roots'][1]['destination'], str(self.base / 'different-project'))

    def test_discovery_keeps_multiple_hits_for_explicit_selection(self):
        home = self.base / 'home'
        (home / '.codex').mkdir(parents=True)
        custom = self.base / 'custom-codex'
        custom.mkdir()
        hits = candidates(home, {'CODEX_HOME': str(custom)})
        self.assertEqual(len([h for h in hits if h.get('provider') == 'codex']), 2)

    def test_windows_cache_detection_respects_environment_case_and_real_pip_root(self):
        home = self.base / 'home'
        local = home / 'AppData' / 'Local'
        pip = local / 'pip' / 'Cache'
        pip.mkdir(parents=True)
        npm = self.base / 'custom-npm'
        npm.mkdir()
        hits = candidates(home, {'LOCALAPPDATA': str(local), 'NPM_CONFIG_CACHE': str(npm)})
        self.assertEqual(next(h['source'] for h in hits if h['label'] == 'npm cache'), str(npm))
        self.assertEqual(next(h['source'] for h in hits if h['label'] == 'pip cache'), str(pip))

    def test_scan_is_bounded_and_does_not_descend_dependency_trees(self):
        (self.source / 'pyproject.toml').write_text('[project]')
        nested = self.source / 'node_modules' / 'another-project'
        nested.mkdir(parents=True)
        (nested / 'package.json').write_text('{}')
        result = scan_folder(self.base)
        self.assertIn(str(self.source), result['projects'])
        self.assertNotIn(str(nested), result['projects'])
        self.assertTrue(scan_folder(self.base, max_entries=1)['limited'])

    def test_saved_project_lookup_reads_paths_and_returns_canonical_dirs(self):
        home = self.base / 'home'
        home.mkdir()
        (home / '.claude.json').write_text(json.dumps({'projects': {str(self.source): {}}}))
        self.assertEqual(project_suggestions(home, {}), [str(self.source.resolve())])

    def test_native_command_cannot_move_delete_or_follow_junctions(self):
        args = command(self.source, self.base / 'target')
        self.assertIn('/MT:16', args)
        self.assertIn('/XJ', args)
        self.assertIn('/SL', args)
        for flag in ('/MIR', '/PURGE', '/MOV', '/MOVE', '/B', '/ZB'):
            self.assertNotIn(flag, args)

    def test_native_copy_never_traverses_existing_destination(self):
        target = self.base / 'target'
        target.mkdir()
        (target / 'existing').write_text('keep')
        entry = {'id': 'example', 'source': str(self.source), 'destination': str(target)}
        with patch('ai_storage_mover.native.subprocess.Popen', side_effect=AssertionError('Unexpected native traversal')):
            self.assertFalse(copy_new_tree(entry, self.base, reserve=0, notify=lambda *a, **k: None))
        self.assertEqual((target / 'existing').read_text(), 'keep')

    def test_native_failure_keeps_source_and_does_not_cut_over(self):
        class Failed:
            returncode = 8
            def poll(self): return self.returncode
        entry = {'id': 'example', 'source': str(self.source), 'destination': str(self.base / 'target')}
        with patch('ai_storage_mover.native.subprocess.Popen', return_value=Failed()):
            with self.assertRaises(MigrationError):
                copy_new_tree(entry, self.base, reserve=0, notify=lambda *a, **k: None)
        self.assertEqual((self.source / 'file.txt').read_text(), 'original')

    def test_frozen_setup_uses_bundled_worker_and_custom_runtime(self):
        with patch.object(__import__('sys'), 'frozen', True, create=True):
            args = setup_command(self.session(), preflight=True)
        self.assertIn('-BundledRuntime', args)
        self.assertIn('-RuntimeInput', args)
        self.assertIn('-PreflightOnly', args)
        self.assertTrue(args[args.index('-PythonPath') + 1].endswith('ai-storage-worker.exe'))


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Desktop display required')
class DesktopTests(unittest.TestCase):
    def test_wizard_navigation_and_exact_cleanup_gate(self):
        import tkinter as tk
        from ai_storage_mover.gui import Wizard
        root = tk.Tk()
        root.withdraw()
        try:
            app = Wizard(root)
            app.next()
            self.assertEqual(app.page, 0)
            self.assertIn('Select', app.error.get())
            app.projects = [str(Path(__file__).resolve().parent)]
            app.show(1)
            app.next()
            self.assertEqual(app.page, 1)
            self.assertTrue(app.destination_list.winfo_exists())
            self.assertEqual(len(app.destination_list.get_children()), 1)
            app.set_storage(Path(__file__).resolve().parents[1] / '.runs' / 'preview-storage')
            self.assertIn('Projects', app.destination_list.item('0', 'values')[1])
            app.session = create_session(app.projects, Path(__file__).resolve().parents[1] / '.runs' / 'preview-storage')
            app.session['status'] = 'complete'
            app.cleanup_screen()
            self.assertEqual(str(app.delete_button['state']), 'disabled')
            app.phrase.set(CLEANUP_PHRASE + 'x')
            app.tested.set(True)
            app.enable_cleanup()
            self.assertEqual(str(app.delete_button['state']), 'disabled')
            app.phrase.set(CLEANUP_PHRASE)
            app.enable_cleanup()
            self.assertEqual(str(app.delete_button['state']), 'normal')
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()
