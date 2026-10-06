from pathlib import Path
import json
import shutil
import tempfile
import tomllib
import unittest

from ai_storage_mover.configure import configure, codex_environment
from ai_storage_mover.model import make_plan, MigrationError
from ai_storage_mover.runtime import settings


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.runs = Path(__file__).resolve().parents[1] / '.runs'
        self.runs.mkdir(exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix='setup-', dir=self.runs))

    def tearDown(self):
        assert self.base.resolve().parent == self.runs.resolve()
        shutil.rmtree(self.base)

    def test_codex_preserves_mcp_secrets_and_http_servers(self):
        text = '''# retain this comment
[mcp_servers.local]
command = "node"
env = { TOKEN = "keep", TEMP = "old" }
[mcp_servers."custom.server".env]
TOKEN = "also keep"
[mcp_servers."custom.server"]
command = "python"
[mcp_servers.remote]
url = "https://example.invalid/mcp"
'''
        updated = codex_environment(text, {'TEMP': str(self.base), 'UV_CACHE_DIR': str(self.base / 'uv')})
        value = tomllib.loads(updated)
        self.assertIn('# retain this comment', updated)
        self.assertEqual(value['mcp_servers']['local']['env']['TOKEN'], 'keep')
        self.assertEqual(value['mcp_servers']['custom.server']['env']['TOKEN'], 'also keep')
        self.assertEqual(value['mcp_servers']['custom.server']['env']['TEMP'], str(self.base))
        self.assertNotIn('env', value['mcp_servers']['remote'])

    def test_future_writes_and_legacy_preferences_survive_idempotent_setup(self):
        old = self.base / 'old-project'
        new = self.base / 'new-project'
        old.mkdir()
        legacy = self.base / 'legacy' / '.claude.json'
        legacy.parent.mkdir()
        legacy.write_text(json.dumps({'projects': {str(old): {'trust': True}}}))
        plan = make_plan([(old, new, 'project'), (self.base / 'old-global.json', legacy, 'profile')], self.base / 'storage')
        # The adapter recognizes the original global preferences filename.
        plan['roots'][1]['source'] = str(self.base / 'old-home' / '.claude.json')
        runtime = settings(self.base / 'storage')
        codex = Path(runtime['environment']['CODEX_HOME'])
        claude = Path(runtime['environment']['CLAUDE_CONFIG_DIR'])
        desktop = self.base / 'desktop'
        desktop.mkdir()
        (desktop / 'claude_desktop_config.json').write_text(json.dumps({'mcpServers': {'local': {'command': 'node', 'env': {'TOKEN': 'keep'}}}}))
        codex.mkdir(parents=True)
        (codex / 'AGENTS.md').write_text('Keep existing instructions.\n')
        with self.assertRaises(MigrationError):
            configure(plan, runtime, codex=codex, claude=claude)
        first = configure(plan, runtime, codex=codex, claude=claude, desktops=[desktop], projects=self.base / 'Projects', apps_closed=True)
        self.assertEqual(json.loads((claude / '.claude.json').read_text())['projects'], {str(new): {'trust': True}})
        self.assertTrue(legacy.exists())
        self.assertEqual(json.loads((claude / 'settings.json').read_text())['env']['UV_CACHE_DIR'], runtime['environment']['UV_CACHE_DIR'])
        server = json.loads((desktop / 'claude_desktop_config.json').read_text())['mcpServers']['local']
        self.assertEqual(server['env']['TOKEN'], 'keep')
        self.assertEqual(server['env']['TEMP'], runtime['environment']['TEMP'])
        self.assertEqual(tomllib.loads((codex / 'config.toml').read_text())['shell_environment_policy']['set']['TEMP'], runtime['environment']['TEMP'])
        text = (codex / 'AGENTS.md').read_text()
        self.assertIn('Keep existing instructions.', text)
        self.assertIn(str(self.base / 'Projects'), text)
        second = configure(plan, runtime, codex=codex, claude=claude, desktops=[desktop], projects=self.base / 'Projects', apps_closed=True)
        self.assertEqual(second['changed_configs'], [])
        self.assertEqual((codex / 'AGENTS.md').read_text(), text)
        self.assertTrue(Path(first['backup']).is_dir())


if __name__ == '__main__':
    unittest.main()
