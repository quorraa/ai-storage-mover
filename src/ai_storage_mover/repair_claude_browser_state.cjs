// Offline, whitelisted workspace state only. No browser debugging or network.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { ClassicLevel } = require(process.env.AI_STORAGE_MOVER_LEVEL_MODULE || '../../tools/browser-state/node_modules/classic-level');
const [planPath, cachePath] = process.argv.slice(2);
if (!planPath || !cachePath) throw Error('Usage: node repair_claude_browser_state.cjs PLAN CACHE_DIRECTORY');
const plan = JSON.parse(fs.readFileSync(planPath, 'utf8').replace(/^\uFEFF/, ''));
const run = path.resolve(plan.run_dir);
const original = path.resolve(cachePath);
if (!path.isAbsolute(plan.run_dir)) throw Error('An absolute private run directory is required');
if (run === original || run.startsWith(original + path.sep) || original.startsWith(run + path.sep)) throw Error('Backup and browser state directories must not overlap');
if (path.basename(original) !== 'leveldb' || path.basename(path.dirname(original)) !== 'Local Storage') throw Error('Select only the Claude Local Storage/leveldb folder');
if (!Array.isArray(plan.roots) || !plan.roots.length) throw Error('Explicit path mappings required');
const archive = path.join(run, 'claude-browser-state', crypto.randomUUID());
const backup = path.join(archive, 'before');
const inspection = path.join(archive, 'inspection');
const entries = plan.roots.sort((a,b) => b.source.length-a.source.length);
const allowed = name => name.startsWith('LSS-persisted.cai-bright-charm:') || name.startsWith('LSS-persisted.code-projects-order.') || name.startsWith('LSS-persisted.epitaxy-folder-permission-mode.') || name.startsWith('LSS-persisted.epitaxy-perm-mode-acks.') || name === 'LSS-persisted.preferredPreviewServers' || name === 'dframe-store' || name === 'dframe-store.backup.v1' || name === 'epitaxy.dismissedPrMap' || name.startsWith('epitaxy.sidePaneStore.v1');
function map(value) {
  if (typeof value !== 'string') return value;
  const prefix = value.startsWith('\\\\?\\') ? '\\\\?\\' : '';
  const plain = value.slice(prefix.length).replaceAll('/', '\\');
  for (const root of entries) {
    if (plain.toLowerCase() === root.source.toLowerCase() || plain.toLowerCase().startsWith(root.source.toLowerCase() + '\\')) return prefix + root.destination + plain.slice(root.source.length);
  }
  return value;
}
function nested(value, field = '') {
  if (Array.isArray(value)) return value.map(child => nested(child, field));
  if (value && typeof value === 'object') {
    const result = {};
    for (const [key,child] of Object.entries(value)) {
      const changed = mapKey(key);
      if (Object.hasOwn(result, changed)) throw Error('Mapped workspace keys overlap; no edits');
      Object.defineProperty(result, changed, {value:nested(child,key), enumerable:true, writable:true});
    }
    return result;
  }
  if (typeof value === 'string' && field === 'collapsedGroups') {
    const at = value.search(/[A-Z]:\\/i);
    if (at >= 0) return value.slice(0,at) + map(value.slice(at));
  }
  return map(value);
}
function fingerprint(folder) {
  return fs.readdirSync(folder).sort().map(name => name + ':' + crypto.createHash('sha256').update(fs.readFileSync(path.join(folder,name))).digest('hex')).join('\n');
}
function mapKey(key) {
  const direct = map(key);
  if (direct !== key) return direct;
  if (key.startsWith('{')) {
    try {
      const identifier = JSON.parse(key);
      if (identifier && typeof identifier === 'object' && typeof identifier.cwd === 'string') return JSON.stringify(nested(identifier));
    } catch {}
  }
  return key;
}
const encode = (text, flag) => {
  if (flag === 1 && /[^\u0000-\u00ff]/.test(text)) flag = 0;
  return Buffer.concat([Buffer.from([flag]), Buffer.from(text, flag === 0 ? 'utf16le' : 'latin1')]);
};
const decode = value => value.subarray(1).toString(value[0] === 0 ? 'utf16le' : 'latin1');
(async () => {
  fs.mkdirSync(archive, { recursive: true });
  const before = fingerprint(original);
  fs.cpSync(original, backup, { recursive: true });
  if (fingerprint(backup) !== before || fingerprint(original) !== before) throw Error('Browser state changed during backup; no edits');
  fs.cpSync(backup, inspection, { recursive: true });
  const copy = new ClassicLevel(inspection, { keyEncoding:'buffer', valueEncoding:'buffer', createIfMissing:false });
  const operations = [];
  const proof = [];
  try {
    await copy.open();
    for await (const [key,value] of copy.iterator()) {
      const rendered = key.toString('latin1');
      if (!rendered.startsWith('_https://claude.ai\0\x01')) continue;
      const name = rendered.slice('_https://claude.ai\0\x01'.length);
      if (!allowed(name) || ![0,1].includes(value[0])) continue;
      const old = decode(value);
      const parsed = JSON.parse(old);
      const changed = nested(parsed);
      if (JSON.stringify(parsed) === JSON.stringify(changed)) continue;
      operations.push({type:'put', key, value:encode(JSON.stringify(changed), value[0]), before:value});
      proof.push({key:name,changed:true,backup});
      if (name.startsWith('LSS-persisted.cai-bright-charm:')) proof[proof.length-1].workspacePaths = changed;
    }
  } finally { await copy.close(); }
  if (fingerprint(original) !== before) throw Error('Original state changed before applying; no edits');
  const live = new ClassicLevel(original, { keyEncoding:'buffer', valueEncoding:'buffer', createIfMissing:false });
  try {
    await live.open();
    for (const change of operations) if (!(await live.get(change.key)).equals(change.before)) throw Error('Workspace value changed concurrently; no edits');
    await live.batch(operations.map(({type,key,value}) => ({type,key,value})), {sync:true});
    for (const change of operations) if (!(await live.get(change.key)).equals(change.value)) throw Error('Saved workspace state did not verify');
  } finally { await live.close(); }
  const receipt = {utc:new Date().toISOString(),changedKeys:proof.length,source:original,backup,settings:proof,method:'offline LevelDB batch; no debugging endpoint'};
  fs.writeFileSync(path.join(run,'claude-browser-paths-repaired.json'), JSON.stringify(receipt,null,2));
  process.stdout.write(JSON.stringify(receipt,null,2)+'\n');
})().catch(error => {process.stderr.write(error.message+'\n');process.exitCode=1;});
