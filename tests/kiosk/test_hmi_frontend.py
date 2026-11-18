"""QuickJS와 최소 DOM 모형으로 화면의 비동기 상태·중복 클릭을 검증합니다.

실제 브라우저 레이아웃 시험은 아니며 네트워크·로봇 호출은 모두 모형입니다.
"""

from html.parser import HTMLParser
import json
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs", reason="프런트엔드 동작 시험에는 QuickJS가 필요합니다.")
from art_kiosk.server import STATIC_DIR
STATIC = STATIC_DIR


class Elements(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.items = {}
        self.feed(page)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.items[attrs["id"]] = {"hidden": "hidden" in attrs, "disabled": "disabled" in attrs, "value":attrs.get("value","")}


BOOTSTRAP = r"""
const nodes = {};
const calls = [];
const storage = {};
const timers = new Map();
let nextTimer = 1;
let seed = 0;
let fakeSnapshot = {job_id: 'J1', state: 'DRAWING', total_strokes: 2, completed_strokes: 0, total_length_mm:100,completed_length_mm:10,external_force:false,run_id:1,
  stale: false, state_confirmed: true, age_sec: 0, valid_for_sec: 5};
let fakeCurrent = {job_id: 'J1', text: 'Hi', phase: 'REGISTERED', can_prepare: true, can_draw: false};
let previousSnapshot = null;
let prepareHold = false, prepareResolve = null;
let commandFailure = false;
let loginFailure = false;
let statusFailure = false;
let staleRejection = false;
function node(id, attrs = {}) {
  return {value: '', textContent: '', hidden: false, disabled: false, ...attrs,
    dataset: {}, files: [], classList: {toggle() {}}, listeners: {},
    getContext() { return {save(){}, restore(){}, translate(){}, scale(){}, drawImage(){}}; },
    toBlob(fn) { fn({name: 'camera.png'}); },
    addEventListener(name, fn) { this.listeners[name] = fn; },
    fire(name) { return this.listeners[name]?.({preventDefault() {}}); },
    click() { return this.fire('click'); }};
}
for (const [id, attrs] of Object.entries(elementAttrs)) nodes[id] = node(id, attrs);
const controls = ['PAUSE', 'RESUME', 'CANCEL'].map(command => {
  const button = node(command, {disabled: true}); button.dataset.command = command; return button;
});
globalThis.document = {
  getElementById(id) { if (!nodes[id]) throw Error('없는 DOM ID: ' + id); return nodes[id]; },
  querySelectorAll() { return controls; },
};
globalThis.performance = {now() { return 0; }};
globalThis.crypto = {getRandomValues(bytes) { bytes.fill(++seed); return bytes; }};
globalThis.AbortController = class {constructor() {this.signal = {};} abort() {}};
globalThis.URL = {createObjectURL() { return 'blob:test'; }, revokeObjectURL() {}};
globalThis.FormData = class {constructor() {this.data = [];} append(k,v) {this.data.push([k,v]);}};
globalThis.navigator = {mediaDevices: {getUserMedia: async () => ({getTracks: () => [{stop(){}}]})}};
globalThis.sessionStorage = {
  getItem(key) { return storage[key] || null; },
  setItem(key, value) { storage[key] = value; },
  removeItem(key) { delete storage[key]; },
};
globalThis.setTimeout = (fn, delay) => {const id = nextTimer++; timers.set(id, {fn, delay}); return id;};
globalThis.clearTimeout = (id) => timers.delete(id);
globalThis.setInterval = globalThis.setTimeout;
globalThis.clearInterval = globalThis.clearTimeout;
globalThis.fetch = (url, options = {}) => {
  calls.push({url, ...options});
  let code = 200, data = {};
  if (url === '/api/health') data = {engine: 'cv'};
  else if (url === '/api/kiosk/recover-execution') {
    code=200;data={reconciled:true,job_id:fakeCurrent.execution_job_id};fakeCurrent.can_recover=false;fakeCurrent.can_draw=true;
  }
  else if (url === '/api/admin/session') {
    code = loginFailure ? 401 : 200; data = loginFailure ? {detail: '인증 실패'} : {role: 'admin'};
  } else if (url.endsWith('/control')) {
    code = staleRejection ? 409 : commandFailure ? 504 : 202;
    data = staleRejection ? {detail: '오래된 상태로 중계 거부'} : commandFailure ? {detail: '상태 미확정'} : {manager_state: 'PAUSING', notice: '요청 수락, 실제 정지 미확정'};
  } else if (url === '/api/admin/current' || url === '/api/kiosk/current') {
    if (statusFailure) return Promise.reject(Error('연결 끊김'));
    data = {...fakeCurrent, status: fakeSnapshot ? {...fakeSnapshot} : null};
  } else if (url === '/api/kiosk/lineart') {
    data = {job_id:'LINEART_ONLY',preview_only:true,image_data:'data:image/png;base64,dGVzdA=='};
  } else if (url === '/api/kiosk/prepare') {
    data = {job_id:'NEW', ticket:'T1', phase:'PREVIEW'};
    if (prepareHold) return new Promise(resolve => {prepareResolve = () => resolve({status:200,ok:true,json:async()=>data});});
  } else if (url === '/api/kiosk/draw') {
    code = 202; data = {accepted:true,job_id:'NEW',manager_state:'QUEUED'};
  } else if (url === '/api/kiosk/preview') {
    data = {};
  } else if ((url.startsWith('/api/admin/jobs/') || url.startsWith('/api/kiosk/jobs/')) && previousSnapshot) {
    data = {...previousSnapshot};
  } else throw Error('예상하지 않은 URL ' + url);
  return Promise.resolve({status: code, ok: code < 400, json: async () => data, blob: async () => 'svg'});
};
function runTimer(delay) {
  const entry = [...timers.entries()].find(([id, item]) => item.delay === delay);
  if (!entry) throw Error('예약된 타이머 없음: ' + delay);
  timers.delete(entry[0]); entry[1].fn();
}
"""


class Browser:
    def __init__(self, name):
        self.context = quickjs.Context()
        attrs = Elements((STATIC / f"{name}.html").read_text()).items
        self.context.eval("const elementAttrs = " + json.dumps(attrs) + ";")
        self.context.eval(BOOTSTRAP)
        self.context.eval((STATIC / ("app.js" if name == "index" else "admin.js")).read_text())
        self.flush()

    def flush(self):
        for _ in range(200):
            if not self.context.execute_pending_job():
                return
        raise AssertionError("JavaScript 비동기 작업이 끝나지 않음")

    def run(self, code):
        self.context.eval(code)
        self.flush()

    def value(self, expression):
        return json.loads(self.context.eval(f"JSON.stringify({expression})"))

    def login_and_watch(self):
        self.flush()


def test_admin_opens_without_key_and_loads_current_job():
    browser=Browser('index')
    assert browser.value("calls.some(call=>call.url==='/api/kiosk/current')")
    assert browser.value("calls.every(call=>!call.headers?.Authorization)")
    assert not browser.value("Object.prototype.hasOwnProperty.call(nodes,'adminToken')")
    assert browser.value('nodes.btnPause.disabled') is False


def test_admin_duplicate_click_and_timeout_reuses_request_id():
    browser=Browser('index')
    browser.run('commandFailure=true;nodes.btnPause.click();nodes.btnPause.click();')
    assert browser.value("calls.filter(c=>c.url.endsWith('/control')).length")==1
    assert browser.value('Boolean(storage.a4PendingControl)')
    browser.run('nodes.btnPause.click();')
    sent=browser.value("calls.filter(c=>c.url.endsWith('/control')).map(c=>JSON.parse(c.body))")
    assert sent[0]['request_id']==sent[1]['request_id']
    assert browser.value('nodes.btnResume.disabled') is True
    browser.run('commandFailure=false;nodes.btnPause.click();')
    assert browser.value('Boolean(storage.a4PendingControl)')
    browser.run("fakeSnapshot.state='PAUSED';runTimer(1500);")
    assert not browser.value('Boolean(storage.a4PendingControl)')
    assert browser.value('nodes.btnResume.disabled') is False


def test_admin_stale_response_disconnect_and_local_expiry_disable_controls():
    browser=Browser('index')
    browser.run('fakeSnapshot.stale=true;fakeSnapshot.state_confirmed=false;runTimer(1500);')
    assert browser.value('[nodes.btnPause,nodes.btnResume,nodes.btnRestart].every(b=>b.disabled)')
    assert browser.value('nodes.jobProgress.hidden')
    browser.run('fakeSnapshot.stale=false;fakeSnapshot.state_confirmed=true;runTimer(1500);')
    assert browser.value('nodes.btnPause.disabled') is False
    browser.run('runTimer(5000);')
    assert browser.value('[nodes.btnPause,nodes.btnResume,nodes.btnRestart].every(b=>b.disabled)')
    browser.run('statusFailure=true;runTimer(1500);')
    assert '미확정' in browser.value('nodes.jobStatusText.textContent')


def test_user_progress_expires_and_disconnect_does_not_claim_pause():
    browser = Browser("index")
    assert browser.value("nodes.jobProgress.hidden") is False
    assert "그리는 중" in browser.value("nodes.jobStatusText.textContent")
    browser.run("runTimer(5000);")
    assert browser.value("nodes.jobProgress.hidden") is True
    assert "미확정" in browser.value("nodes.jobStatusText.textContent")
    browser.run("fakeSnapshot.state = 'PAUSING'; runTimer(1500);")
    assert "일시정지 확인 중" in browser.value("nodes.jobStatusText.textContent")
    browser.run("statusFailure = true; runTimer(1500);")
    assert browser.value("nodes.jobProgress.hidden") is True
    assert "미확정" in browser.value("nodes.jobStatusText.textContent")
    assert browser.value("calls.every(call => !call.url.startsWith('/api/admin/'))") is True


def test_user_automatically_prepares_photo_phrase_and_starts_only_on_click():
    browser = Browser('index')
    browser.run("fakeCurrent={job_id:null,phase:'IDLE',can_prepare:true};fakeSnapshot=null;runTimer(1500);")
    browser.run("nodes.photoFileInput.files=[{name:'p.png'}];nodes.photoFileInput.fire('change');nodes.calligraphyText.value='H';nodes.calligraphyText.fire('input');nodes.calligraphyText.value='Hi';nodes.calligraphyText.fire('input');")
    assert browser.value("[...timers.values()].filter(item=>item.delay===600).length") == 1
    assert browser.value("nodes.btnDraw.disabled") is True
    browser.run('runTimer(600);')
    assert browser.value("nodes.btnDraw.disabled") is False
    assert browser.value("calls.filter(call=>call.url==='/api/kiosk/draw').length") == 0
    assert browser.value("calls.find(call=>call.url==='/api/kiosk/prepare').body.data.find(pair=>pair[0]==='text')[1]") == 'Hi'
    browser.run('nodes.btnDraw.click();nodes.btnDraw.click();')
    assert browser.value("calls.filter(call=>call.url==='/api/kiosk/draw').length") == 1


def test_user_late_result_cannot_enable_old_preview_after_edit():
    browser = Browser('index')
    browser.run("fakeCurrent={job_id:null,phase:'IDLE',can_prepare:true};fakeSnapshot=null;runTimer(1500);")
    browser.run("prepareHold=true;nodes.photoFileInput.files=[{}];nodes.photoFileInput.fire('change');runTimer(600);")
    browser.run("nodes.calligraphyText.value='changed';nodes.calligraphyText.fire('input');prepareResolve();")
    assert browser.value('nodes.btnDraw.disabled') is True
    assert browser.value('nodes.resultImage.hidden') is True
    browser.run('prepareHold=false;runTimer(0);')
    assert browser.value('nodes.btnDraw.disabled') is False
    assert browser.value("calls.filter(call=>call.url==='/api/kiosk/prepare').slice(-1)[0].body.data.find(pair=>pair[0]==='text')[1]") == 'changed'


def test_admin_commands_include_automatically_selected_job():
    browser=Browser('index');browser.run('nodes.btnPause.click();')
    body=browser.value("JSON.parse(calls.find(c=>c.url.endsWith('/control')).body)")
    assert body['expected_job_id']=='J1' and body['command']=='PAUSE'
    assert not browser.value("Object.prototype.hasOwnProperty.call(nodes,'adminJobId')")


def test_camera_capture_enters_the_same_automatic_preview_flow():
    browser = Browser('index')
    browser.run("fakeCurrent={job_id:null,phase:'IDLE',can_prepare:true};fakeSnapshot=null;runTimer(1500);")
    browser.run("nodes.btnStartCam.click();")
    assert browser.value('nodes.btnCaptureNow.disabled') is False
    browser.run("nodes.camVideo.videoWidth=640;nodes.camVideo.videoHeight=480;nodes.btnCaptureNow.click();runTimer(600);")
    assert browser.value('nodes.btnDraw.disabled') is False
    assert browser.value("calls.filter(call=>call.url==='/api/kiosk/prepare').length") == 1



def test_admin_resolves_old_terminal_request_before_controlling_next_job():
    browser=Browser('index');browser.run('commandFailure=true;nodes.btnPause.click();')
    assert browser.value('Boolean(storage.a4PendingControl)')
    browser.run("previousSnapshot={job_id:'J1',state:'COMPLETED',stale:false,state_confirmed:true};fakeCurrent.job_id='J2';fakeSnapshot.job_id='J2';runTimer(1500);")
    assert not browser.value('Boolean(storage.a4PendingControl)')
    assert browser.value('nodes.btnPause.disabled') is False


def test_resuming_disables_pause_resume_but_keeps_cancel_available():
    browser=Browser('index');browser.run("fakeSnapshot.state='RESUMING';runTimer(1500);")
    assert browser.value('nodes.btnPause.disabled') and browser.value('nodes.btnResume.disabled')
    assert browser.value('nodes.btnRestart.disabled') is False
    assert '멈춘 위치' in browser.value('nodes.jobStatusText.textContent')










def test_force_ui_only_allows_reset_and_locks_inputs():
    browser=Browser('index');browser.run("fakeSnapshot.state='FORCE_STOPPED';fakeSnapshot.external_force=true;runTimer(1500);")
    assert browser.value('nodes.forceNotice.hidden') is False
    assert browser.value('nodes.btnPause.disabled') and not browser.value('nodes.btnResume.disabled')
    assert browser.value('nodes.btnRestart.disabled') is False
    assert not browser.value('nodes.photoFileInput.disabled')
    assert not browser.value('nodes.calligraphyText.disabled')
    assert browser.value('nodes.btnDraw.disabled')
    browser.run('nodes.btnRestart.click();')
    assert browser.value("JSON.parse(calls.find(c=>c.url.endsWith('/control')).body).command")=='STOP'
    assert not browser.value('Boolean(storage.a4PendingControl)')


def test_length_progress_and_numeric_detail_slider():
    browser=Browser('index');browser.run('fakeSnapshot.completed_strokes=1;runTimer(1500);')
    assert browser.value('nodes.jobProgress.value')==10 and '10.0%' in browser.value('nodes.jobStatusText.textContent')
    browser.run("fakeCurrent={job_id:null,phase:'IDLE',can_prepare:true};fakeSnapshot=null;runTimer(1500);")
    browser.run("nodes.photoFileInput.files=[{}];nodes.photoFileInput.fire('change');nodes.detailSelect.value='73';nodes.detailSelect.fire('input');runTimer(600);")
    assert browser.value("calls.filter(c=>c.url==='/api/kiosk/prepare').slice(-1)[0].body.data.find(p=>p[0]==='detail')[1]")=='73'


def test_reset_failure_receipt_and_new_run_acknowledgement():
    browser=Browser('index');browser.run('nodes.btnRestart.click();nodes.btnRestart.click();')
    assert browser.value("calls.filter(c=>c.url.endsWith('/control')).length")==1
    browser.run("fakeSnapshot.state='PAUSED';runTimer(1500);")
    assert not browser.value('Boolean(storage.a4PendingControl)')


def test_unknown_execution_allows_new_preview_and_draw_cleanup_request():
    browser=Browser('index')
    browser.run("fakeSnapshot=null;fakeCurrent={job_id:'NEW',execution_job_id:'OLD',phase:'PREVIEW',can_prepare:true,can_draw:true,ticket:'TICKET',status_error:'상태 미확정'};runTimer(1500);")
    assert not browser.value('nodes.photoFileInput.disabled')
    assert not browser.value('nodes.calligraphyText.disabled')
    browser.run("nodes.photoFileInput.files=[{}];nodes.photoFileInput.fire('change');runTimer(600);")
    assert not browser.value('nodes.btnDraw.disabled')
    assert '자동 확인' in browser.value('nodes.jobStatusText.textContent')
    assert browser.value("calls.filter(c=>c.url==='/api/kiosk/draw').length")==0


def test_new_drawing_has_no_manual_recovery_checkbox():
    browser=Browser('index')
    browser.run("fakeSnapshot=null;fakeCurrent={job_id:'NEW',execution_job_id:'OLD',phase:'PREVIEW',can_prepare:true,can_draw:true,ticket:'TICKET'};runTimer(1500);")
    assert not browser.value("Object.prototype.hasOwnProperty.call(nodes,'recoveryConfirmed')")
    assert not browser.value("Object.prototype.hasOwnProperty.call(nodes,'btnRecoverExecution')")
    browser.run("nodes.photoFileInput.files=[{}];nodes.photoFileInput.fire('change');runTimer(600);")
    assert not browser.value('nodes.btnDraw.disabled')
