from contextlib import closing
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from ai_storage_mover.engine import Engine, link_root
from ai_storage_mover.model import MigrationError, read_json, validate, validate_runtime, atomic_json
from ai_storage_mover.repair import CACHE, apply_repair, inspect_layout, manifest
from ai_storage_mover.wizard import create_session, load_session, save_session


class RepairTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(__file__).resolve().parents[1] / '.runs'
        self.base.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix='repair-fixture-', dir=self.base))
        self.public = self.root / 'user' / 'AppData' / 'Roaming' / 'Codex'
        self.public.parent.mkdir(parents=True)
        self.source = self.root / 'external-profile'
        self.private = self.root / 'private-profile'
        self.record = self.root / 'record'
        self.record.mkdir()
        for profile in (self.source, self.private):
            (profile / CACHE).mkdir(parents=True)
            (profile / CACHE / 'data_0').write_bytes(b'old browser cache')
            (profile / 'account.json').write_text('fictional account state')
            (profile / 'empty').mkdir()
        link_root(self.public, self.source)
        self.expected = inspect_layout(self.public, self.private)

    def tearDown(self):
        assert self.root.resolve().parent == self.base.resolve()
        shutil.rmtree(self.root)  # Never follows directory junctions on supported Python.

    def repair(self, **kw):
        return apply_repair(self.expected, self.record, closed=lambda: True, **kw)

    def test_repair_preserves_both_profiles_and_original_target_and_is_idempotent(self):
        original = manifest(self.source)[0]
        receipt = self.repair()
        self.assertEqual(self.public.resolve(), self.public)
        self.assertEqual(manifest(self.source)[0], original)
        self.assertEqual((self.public / 'account.json').read_text(), 'fictional account state')
        self.assertEqual((self.private / 'account.json').read_text(), 'fictional account state')
        self.assertTrue((self.public / 'empty').is_dir())
        self.assertEqual(Path(receipt['junction_backup']).resolve(), self.source)
        for item in receipt['caches']:
            self.assertFalse(Path(item['original']).exists())
            self.assertEqual((Path(item['backup']) / 'data_0').read_bytes(), b'old browser cache')
        self.assertFalse(inspect_layout(self.public, self.private)['affected'])
        self.assertFalse(receipt['memory_leak_verified'])

    def test_source_change_is_detected_before_cutover(self):
        copy = shutil.copy2
        def change(a, b):
            result = copy(a, b)
            if Path(a).name == 'account.json':
                Path(a).write_text('newer state from another writer')
            return result
        with patch('ai_storage_mover.repair.shutil.copy2', side_effect=change), self.assertRaises(MigrationError):
            self.repair()
        self.assertEqual(self.public.resolve(), self.source)
        self.assertTrue((self.private / CACHE).exists())

    def test_corrupt_copy_is_rejected(self):
        copy = shutil.copy2
        def corrupt(a, b):
            result = copy(a, b)
            Path(b).write_bytes(b'corrupt')
            return result
        with patch('ai_storage_mover.repair.shutil.copy2', side_effect=corrupt), self.assertRaises(MigrationError):
            self.repair()
        self.assertEqual(self.public.resolve(), self.source)
        self.assertTrue((self.private / CACHE).exists())

    def test_rename_failure_rolls_back_without_deleting_data(self):
        rename = Path.rename
        def fail(path, target):
            if path == self.public:
                raise PermissionError('simulated locked public profile')
            return rename(path, target)
        with patch.object(Path, 'rename', fail), self.assertRaises(PermissionError):
            self.repair()
        self.assertEqual(self.public.resolve(), self.source)
        self.assertTrue((self.private / CACHE / 'data_0').exists())
        self.assertTrue((self.source / 'account.json').exists())

    def test_low_disk_and_cancellation_make_no_profile_changes(self):
        with patch('ai_storage_mover.repair.shutil.disk_usage', return_value=shutil._ntuple_diskusage(10, 10, 0)), self.assertRaises(MigrationError):
            self.repair()
        with self.assertRaises(MigrationError):
            self.repair(cancelled=lambda: True)
        self.assertEqual(list(self.public.parent.iterdir()), [self.public])

    def test_running_app_is_refused(self):
        with self.assertRaises(MigrationError):
            apply_repair(self.expected, self.record, closed=lambda: False)
        self.assertEqual(list(self.public.parent.iterdir()), [self.public])

    def test_reopened_app_stops_before_active_path_changes(self):
        with self.assertRaises(MigrationError):
            apply_repair(self.expected, self.record, closed=unittest.mock.Mock(side_effect=[True, False]))
        self.assertEqual(self.public.resolve(), self.source)
        self.assertTrue((self.private / CACHE / 'data_0').exists())

    def test_unknown_cache_layout_is_not_repaired(self):
        (self.private / CACHE).rename(self.private / CACHE.parent / 'unrecognized-cache')
        with self.assertRaises(MigrationError):
            inspect_layout(self.public, self.private)
        self.assertEqual(self.public.resolve(), self.source)

    def test_nested_link_cannot_copy_unrelated_data(self):
        other = self.root / 'unrelated'
        other.mkdir()
        (other / 'keep').write_text('unrelated')
        link_root(self.source / 'linked', other)
        with self.assertRaises(MigrationError):
            self.repair()
        self.assertEqual((other / 'keep').read_text(), 'unrelated')
        self.assertEqual(self.public.resolve(), self.source)

    def test_profile_changed_since_preview_is_refused(self):
        stale = dict(self.expected, source=str(self.root / 'wrong'))
        with self.assertRaises(MigrationError):
            apply_repair(stale, self.record, closed=lambda: True)
        self.assertEqual(self.public.resolve(), self.source)

    def test_manual_alias_parent_and_saved_plan_cannot_bypass_guard(self):
        project = self.root / 'Project'
        project.mkdir()
        session = create_session([project], self.root / 'storage', reserve_bytes=0)
        for selected in (self.public, self.public / 'web', self.public.parent, self.public.parent.parent,
                         self.public.parent / '..' / 'Roaming' / 'Codex', self.root / 'user'):
            with self.subTest(selected=selected), self.assertRaises(MigrationError):
                create_session([selected], self.root / 'target')
        plan = session['plan']
        plan['roots'][0]['source'] = str(self.public)
        with self.assertRaises(MigrationError):
            Engine(plan)
        self.assertFalse((self.root / 'storage').exists())
        self.assertTrue((self.source / 'account.json').exists())

    def test_saved_desktop_provider_and_runtime_override_are_blocked(self):
        project = self.root / 'Project'
        project.mkdir()
        session = create_session([project], self.root / 'storage', reserve_bytes=0)
        session['plan']['roots'][0]['provider'] = 'codex-desktop'
        with self.assertRaises(MigrationError):
            validate(session['plan'])
        session['plan']['roots'][0].pop('provider')
        session['runtime']['environment']['CODEX_ELECTRON_USER_DATA_PATH'] = str(self.source)
        save_session(session)
        with self.assertRaises(MigrationError):
            load_session(Path(session['plan']['run_dir']) / 'wizard.local.json')


if __name__ == '__main__':
    unittest.main()
