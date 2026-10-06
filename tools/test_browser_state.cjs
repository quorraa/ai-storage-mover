// Native LevelDB fixtures, including a live lock and an authentication sentinel.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const child = require('child_process');
const { ClassicLevel } = require(process.env.AI_STORAGE_MOVER_LEVEL_MODULE || './browser-state/node_modules/classic-level');
const runs = path.resolve(__dirname, '../.runs');
fs.mkdirSync(runs, {recursive:true});
const fixture = fs.mkdtempSync(path.join(runs, 'browser-fixture-'));
assert.equal(path.dirname(fixture), runs);
const store = path.join(fixture, 'desktop/Local Storage/leveldb');
const plan = path.join(fixture, 'plan.local.json');
const source = 'C:\\Projects\\AnyName';
const destination = 'E:\\AI\\Projects\\新项目';
fs.writeFileSync(plan, JSON.stringify({run_dir:path.join(fixture,'run'), roots:[{source,destination}]}));
const key = name => Buffer.from('_https://claude.ai\0\x01' + name, 'latin1');
const value = data => Buffer.concat([Buffer.from([1]),Buffer.from(JSON.stringify(data),'latin1')]);
const decode = raw => JSON.parse(raw.subarray(1).toString(raw[0] === 0 ? 'utf16le' : 'latin1'));
const invoke = cache => child.spawnSync(process.execPath,[path.join(__dirname,'repair_claude_browser_state.cjs'),plan,cache], {encoding:'utf8',env:process.env});
(async () => {
  let db = new ClassicLevel(store,{keyEncoding:'buffer',valueEncoding:'buffer'});
  await db.open();
  const auth = value({token:'fixture-only',path:source});
  await db.batch([
    {type:'put',key:key('auth.fixture'),value:auth},
    {type:'put',key:key('LSS-persisted.cai-bright-charm:fixture'),value:value([source])},
    {type:'put',key:key('epitaxy.sidePaneStore.v1'),value:value({[JSON.stringify({cwd:source})]:{path:source+'\\file.txt'}})},
    {type:'put',key:key('dframe-store'),value:value({collapsedGroups:['code--'+source],unrelated:source+'Other'})},
  ]);
  const locked = invoke(store);
  assert.notEqual(locked.status,0,'A live native lock must refuse edits');
  assert.deepEqual(await db.get(key('auth.fixture')),auth);
  assert.deepEqual(decode(await db.get(key('LSS-persisted.cai-bright-charm:fixture'))),[source]);
  await db.close();
  const result = invoke(store);
  assert.equal(result.status,0,result.stderr);
  db = new ClassicLevel(store,{keyEncoding:'buffer',valueEncoding:'buffer',createIfMissing:false});
  await db.open();
  assert.deepEqual(await db.get(key('auth.fixture')),auth);
  assert.deepEqual(decode(await db.get(key('LSS-persisted.cai-bright-charm:fixture'))),[destination]);
  const panes=decode(await db.get(key('epitaxy.sidePaneStore.v1')));
  assert.equal(panes[JSON.stringify({cwd:destination})].path,destination+'\\file.txt');
  const frame=decode(await db.get(key('dframe-store')));
  assert.deepEqual(frame.collapsedGroups,['code--'+destination]);
  assert.equal(frame.unrelated,source+'Other');
  await db.close();
  const receipt=JSON.parse(fs.readFileSync(path.join(fixture,'run/claude-browser-paths-repaired.json'),'utf8'));
  assert.equal(receipt.changedKeys,3);
  assert.equal(invoke(store).status,0,'Second pass should be idempotent');
  const wrong=invoke(path.join(fixture,'not-a-cache'));
  assert.notEqual(wrong.status,0);
  console.log(JSON.stringify({browserFixtures:'passed',checks:['native live lock','unchanged authentication bytes','Unicode destination','opaque cwd identifiers','component boundary','idempotent second pass','invalid store refusal']}));
})().catch(e=>{console.error(e);process.exitCode=1;}).finally(()=>{
  const resolved=fs.realpathSync(fixture);
  assert.equal(path.dirname(resolved),fs.realpathSync(runs));
  fs.rmSync(resolved,{recursive:true});
});
