"""Exercise edited/revisited review paths in the real offline window, without copying."""
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import webview

from ai_storage_mover.gui import SetupAPI, document
from ai_storage_mover.model import MigrationError


base = Path(__file__).resolve().parents[1] / '.runs'
base.mkdir(exist_ok=True)
fixture = Path(tempfile.mkdtemp(prefix='desktop-flow-', dir=base))
source = fixture / 'Example project'
source.mkdir()
(source / 'keep.txt').write_text('untouched original')
other = fixture / 'Fixed project'
other.mkdir()


class FixtureAPI(SetupAPI):
    def start_migration(self, apps_closed=False):
        if not self._session or apps_closed is not True:
            raise MigrationError('Review and close apps first')
        # Substitute ONLY the final copy operation. Review uses the real controller.
        self._started_plan = self._session['plan']['run_dir']
        return {'started': True}


api = FixtureAPI()
window = webview.create_window('AI Storage Mover - owned flow test', html=document(),
                              js_api=api, hidden=True, width=1120, height=790)
api._window = window
result = {}
paths = dict(project=str(source), other=str(other), first=str(fixture / 'first'), second=str(fixture / 'second'))
script = r"""
async function exercise(p) {
  Object.assign(state, {projects:[p.project,p.other], storage:'', project_destination:'',
    tools_temp:'', claude_temp:'', items:[], selected:new Set(), visited:3, page:1,
    view:'setup', session:null, reviewKey:null, default_storage:null});
  render();
  function typeStorage(path) {
    $('#storage').value=path;
    $('#storage').dispatchEvent(new Event('input',{bubbles:true}));
  }
  typeStorage(p.first);
  let visibleDefaults=$('#project_destination').value===join(p.first,'Projects');
  await goToStep(3);
  await goToStep(1);
  typeStorage(p.second);
  let projects=join(p.second,'Chosen projects'), explicit=join(p.second,'Fixed destination');
  state.destinations[p.other]=explicit;
  $('#project_destination').value=projects;
  $('#project_destination').dispatchEvent(new Event('input',{bubbles:true}));
  let rows=document.querySelectorAll('#content .list .row .path');
  let immediateRows=rows[0].textContent===join(projects,leaf(p.project)) && rows[1].textContent===explicit;
  $('[data-step="3"]').click();
  for(let n=0;n<100 && state.pending;n++) await new Promise(r=>setTimeout(r,25));
  if(state.page!==3) throw Error('Sidebar did not enter Review');
  let shown=state.session, preparedRun=shown.run_dir;
  let accurate=shown.roots[0].destination===join(projects,leaf(p.project)) && shown.roots[1].destination===explicit;
  let temps=shown.runtime.TEMP===join(p.second,'Temp','tools') &&
    shown.runtime.CLAUDE_CODE_TMPDIR===join(p.second,'Temp','claude') &&
    $('#content').textContent.includes(shown.runtime.TEMP) &&
    $('#content').textContent.includes(shown.runtime.CLAUDE_CODE_TMPDIR);
  let headingFocus=document.activeElement===$('h1');
  $('#apps_closed').checked=true;
  $('#apps_closed').dispatchEvent(new Event('change',{bubbles:true}));
  await next();
  await goToStep(0);
  state.view='setup'; render();
  $('[data-action="remove-project"]').click();
  for(let n=0;n<100 && state.pending;n++) await new Promise(r=>setTimeout(r,25));
  let nearbyFocus=document.activeElement===$('[data-action="remove-project"]');
  state.snapshot={repair:{phase:'complete',active:false,inspection:{affected:true,
    public:'C:\\Users\\Demo\\AppData\\Roaming\\Codex',source:'E:\\AI\\Data\\Codex'}}};
  await handlers.repair();
  let repairInitiallyBlocked=$('[data-action=repair-start]').disabled;
  $('#repair-confirmed').checked=true;
  $('#repair-confirmed').dispatchEvent(new Event('change',{bubbles:true}));
  let repairGate=repairInitiallyBlocked&&!$('[data-action=repair-start]').disabled;
  state.snapshot={repair:{phase:'complete',active:false,receipt:{applied:true}}};render();
  let repairCompletion=$('h1').textContent==='Codex profile restored.'&&!$('[data-action=repair-start]');
  return {visibleDefaults, immediateRows, accurate, temps, headingFocus, nearbyFocus, preparedRun, repairGate, repairCompletion};
}
exercise(PATHS).then(r=>window.__flowResult=r).catch(e=>window.__flowResult={error:String(e)});
"""


def exercise():
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if window.evaluate_js('state.ready'):
                break
            time.sleep(.1)
        window.evaluate_js(script.replace('PATHS', json.dumps(paths)))
        while time.monotonic() < deadline:
            value = window.evaluate_js('window.__flowResult || null')
            if value:
                result.update(value)
                break
            time.sleep(.1)
    finally:
        window.destroy()


try:
    webview.start(exercise, gui='edgechromium' if os.name == 'nt' else None,
                  debug=False, http_server=False, private_mode=True)
    assert result and not result.get('error'), result
    for check in ('visibleDefaults', 'immediateRows', 'accurate', 'temps', 'headingFocus', 'nearbyFocus', 'repairGate', 'repairCompletion'):
        assert result.get(check) is True, result
    assert api._started_plan == result['preparedRun'], 'Started a different plan than Review displayed'
    assert (source / 'keep.txt').read_text() == 'untouched original'
    assert not (fixture / 'second').exists(), 'A review must not copy or change configuration'
    print(json.dumps(dict(desktop_review_flow='passed', **result)))
finally:
    assert fixture.resolve().parent == base.resolve()
    shutil.rmtree(fixture)
