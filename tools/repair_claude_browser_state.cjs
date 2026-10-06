// Source-checkout entry point; packaged Windows setup uses the same adapter.
if (!process.env.AI_STORAGE_MOVER_LEVEL_MODULE) process.env.AI_STORAGE_MOVER_LEVEL_MODULE = require('path').join(__dirname, 'browser-state/node_modules/classic-level');
require('../src/ai_storage_mover/repair_claude_browser_state.cjs');
