(() => {
  const $ = (id) => document.getElementById(id);
  const labels = {QUEUED: '작업 대기', DISPATCHING: '실행 시작 확인 중', DRAWING: '그리는 중',
    PAUSING: '일시정지 확인 중', PAUSED: '일시정지 확인됨', RESUMING: '멈춘 위치에서 재개 확인 중', STOPPING: '중단 확인 중',
    FORCE_STOPPED: '외력 또는 보호 정지 감지', STOPPED: '중단 확인됨', COMPLETED: '작업 완료 확인됨', RECOVERY_REQUIRED: '실제 상태 확인 필요'};
  const state = {photo: null, stream: null, mirrored: true, revision: 0, readyRevision: -1,
    ticket: '', jobId: '', requestId: '', inflightRequestId: '', preparing: false, submitting: false, pending: false,
    blocked: false, lastPhase: 'IDLE', autoTimer: null, snapshot: null, expiry: null, resultUrl: null,
    photoUrl: null, countdown: null, forceSeen: false,
    prepareEstimate: {lineart_sec: 7.0, plan_sec: 3.5, total_sec: 10.5},
    prepareStartedAt: 0, prepareTick: null, serverPrepare: null, prepareAbortController: null,
    previewEstSec: null, previewStrokes: null, etaAnchor: null, etaTick: null};
  function formatDuration(sec) {
    if (typeof sec !== 'number' || !Number.isFinite(sec) || sec < 0) return '--';
    const total = Math.round(sec);
    if (total <= 0) return '0초';
    if (total < 60) return `약 ${total}초`;
    const mins = Math.floor(total / 60);
    const rem = total % 60;
    return rem > 0 ? `약 ${mins}분 ${rem}초` : `약 ${mins}분`;
  }
  function renderPrepareProgress() {
    let pct = 5.0;
    let rem = state.prepareEstimate.total_sec;
    let label = '선화 변환 중 (MFL-LD)';
    const now = performance.now();
    if (state.serverPrepare) {
      const sp = state.serverPrepare;
      const dt = Math.max(0, (now - sp.atMs) / 1000);
      label = sp.stage_label || label;
      const stageCap = sp.stage === 'PLAN' ? 98.0 : 82.0;
      const estSpan = Math.max(1.0, sp.stage === 'PLAN' ? state.prepareEstimate.plan_sec : state.prepareEstimate.lineart_sec);
      const rate = (sp.stage === 'PLAN' ? 18.0 : 72.0) / estSpan;
      pct = Math.min(stageCap, Math.max(sp.percent, sp.percent + dt * rate * 0.7));
      rem = Math.max(1.0, sp.remaining_sec - dt);
    } else if (state.prepareStartedAt > 0) {
      const elapsed = Math.max(0, (now - state.prepareStartedAt) / 1000);
      const estL = Math.max(1.0, state.prepareEstimate.lineart_sec);
      const estP = Math.max(0.5, state.prepareEstimate.plan_sec);
      const estT = estL + estP;
      if (elapsed <= estL) {
        pct = 4.0 + 72.0 * (elapsed / estL);
        label = '선화 변환 중 (MFL-LD)';
      } else {
        const over = (elapsed - estL) / estP;
        pct = over <= 1.0 ? 76.0 + 19.0 * over : 95.0 + 3.0 * (1 - Math.exp(-(over - 1.0)));
        label = '경로 추출 및 최적화 중';
      }
      rem = Math.max(1.0, estT - elapsed);
    }
    const pctRound = Math.round(Math.min(98.5, Math.max(1.0, pct)));
    $('prepareProgressWrap').hidden = false;
    $('prepareProgress').value = pctRound;
    $('preparePercent').textContent = `${pctRound}% · ${label}`;
    $('prepareStatus').textContent = `${label} (${pctRound}%)`;
    $('resultLoading').hidden = false;
    $('resultLoadingPercent').textContent = `${pctRound}%`;
    $('resultLoadingText').textContent = `${label}`;
  }
  function startPrepareUi() {
    state.prepareStartedAt = performance.now();
    state.serverPrepare = null;
    clearInterval(state.prepareTick);
    renderPrepareProgress();
    state.prepareTick = setInterval(renderPrepareProgress, 250);
  }
  function stopPrepareUi(completed) {
    clearInterval(state.prepareTick);
    state.prepareTick = null;
    state.serverPrepare = null;
    state.prepareStartedAt = 0;
    $('prepareProgress').value = completed ? 100 : 0;
    $('preparePercent').textContent = completed ? '100% · 완료' : '0%';
    $('resultLoadingPercent').textContent = completed ? '100%' : '0%';
    $('resultLoadingText').textContent = completed ? '완료' : '선화 변환 중…';
    $('prepareProgressWrap').hidden = true;
    $('resultLoading').hidden = true;
  }
  function renderJobEta() {
    const anchor = state.etaAnchor;
    if (!anchor) return;
    if (anchor.state === 'COMPLETED') {
      $('jobEta').textContent = typeof anchor.totalSec === 'number'
        ? `완료 · 전체 시간 ${formatDuration(anchor.totalSec)}`
        : '완료';
      return;
    }
    const elapsed = anchor.state === 'DRAWING' ? Math.max(0, (performance.now() - anchor.atMs) / 1000) : 0;
    const rem = Math.max(0, anchor.remSec - Math.min(elapsed, 4.0));
    const totalPart = typeof anchor.totalSec === 'number' ? ` · 전체 시간 ${formatDuration(anchor.totalSec)}` : '';
    if (['PAUSED', 'PAUSING', 'FORCE_STOPPED'].includes(anchor.state)) {
      $('jobEta').textContent = `일시정지 · 남은 시간 ${formatDuration(rem)}${totalPart}`;
    } else if (anchor.state === 'STOPPED') {
      $('jobEta').textContent = '중단됨';
    } else {
      $('jobEta').textContent = `남은 시간 ${formatDuration(rem)}${totalPart}`;
    }
  }
  function setEtaAnchor(anchor) {
    state.etaAnchor = anchor;
    clearInterval(state.etaTick);
    state.etaTick = null;
    if (anchor) {
      renderJobEta();
      if (anchor.state === 'DRAWING') {
        state.etaTick = setInterval(renderJobEta, 1000);
      }
    }
  }
  let controlPending = null, controlSending = false;
  try { controlPending = JSON.parse(sessionStorage.getItem('a4PendingControl') || 'null'); } catch {}
  function persistControl() {
    try {
      if (controlPending) sessionStorage.setItem('a4PendingControl', JSON.stringify(controlPending));
      else sessionStorage.removeItem('a4PendingControl');
    } catch {}
  }
  let resume = null;
  try { resume = JSON.parse(sessionStorage.getItem('a4CurrentPreview') || 'null'); } catch { /* 저장소 사용 불가 */ }
  if (resume) {
    state.ticket = resume.ticket || ''; state.requestId = resume.request_id || ''; state.jobId = resume.job_id || '';
    $('calligraphyText').value = resume.text || '';
    if (resume.detail !== undefined && resume.detail !== '') {
      $('detailSelect').value = ({low: 0, medium: 50, high: 100})[resume.detail] ?? resume.detail;
    }
  }

  function saveResume() {
    try { sessionStorage.setItem('a4CurrentPreview', JSON.stringify({
      ticket: state.ticket, request_id: state.requestId, job_id: state.jobId,
      text: $('calligraphyText').value, detail: $('detailSelect').value,
    })); } catch { /* 현재 페이지 메모리로 계속합니다. */ }
  }
  function error(message) { $('errorBanner').textContent = message; $('errorBanner').hidden = !message; }
  function updateButtons() {
    $('btnExtract').disabled = !state.photo || state.preparing || state.submitting || state.blocked;
    $('btnExtract').textContent = state.preparing ? '경로 추출 중…' : '경로 추출';
    $('btnDraw').disabled = !state.ticket || state.readyRevision !== state.revision
      || state.preparing || state.submitting;
    for (const id of ['photoFileInput', 'calligraphyText', 'detailSelect', 'btnResetAll', 'btnStartCam', 'btnMirror', 'btnRetake']) {
      $(id).disabled = state.submitting;
    }
    $('btnCaptureNow').disabled = !state.stream || state.submitting || Boolean(state.countdown);
    $('btnCaptureTimer').disabled = $('btnCaptureNow').disabled;
    const snapshot = state.snapshot;
    const previousTerminal = snapshot && snapshot.job_id !== state.jobId && ['COMPLETED', 'STOPPED'].includes(snapshot.state);
    const force = state.forceSeen || (snapshot && (snapshot.state === 'FORCE_STOPPED' || snapshot.error_code === 'EXTERNAL_FORCE_DETECTED'));
    $('forceNotice').hidden = !force;
    for (const [id, cmd, allowed] of [
      ['btnPause', 'PAUSE', ['DRAWING']],
      ['btnResume', 'RESUME', ['PAUSED', 'FORCE_STOPPED', 'RECOVERY_REQUIRED']],
      ['btnRestart', 'CANCEL', ['QUEUED', 'DISPATCHING', 'DRAWING', 'PAUSING', 'PAUSED', 'RESUMING', 'FORCE_STOPPED', 'RECOVERY_REQUIRED']],
    ]) {
      const retry = controlPending && controlPending.job_id === snapshot?.job_id && controlPending.command === cmd;
      const supersede = cmd === 'CANCEL' && controlPending?.accepted && ['PAUSE', 'RESUME'].includes(controlPending.command);
      $(id).disabled = !snapshot || previousTerminal || controlSending
        || (force && !['RESUME', 'CANCEL'].includes(cmd))
        || (controlPending ? !(retry || supersede) : !allowed.includes(snapshot.state));
    }
  }
  function newId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  }
  async function api(path, options = {}, timeoutMs = 7000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const extSignal = options.signal;
    const onExtAbort = () => controller.abort();
    if (extSignal) {
      if (extSignal.aborted) controller.abort();
      else extSignal.addEventListener('abort', onExtAbort, {once: true});
    }
    try {
      const response = await fetch(path, {...options, cache: 'no-store', signal: controller.signal});
      const data = await response.json();
      if (!response.ok) {
        const exception = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
        exception.status = response.status;
        throw exception;
      }
      return data;
    } finally {
      clearTimeout(timer);
      if (extSignal) extSignal.removeEventListener('abort', onExtAbort);
    }
  }
  function cancelInflightPrepare() {
    if (state.prepareAbortController) {
      state.prepareAbortController.abort();
      state.prepareAbortController = null;
    }
    if (state.preparing) {
      state.preparing = false;
      state.pending = false;
      stopPrepareUi(false);
      fetch('/api/kiosk/prepare/cancel', {method: 'POST', cache: 'no-store'}).catch(() => {});
    }
  }
  function invalidate() {
    state.revision += 1;
    state.readyRevision = -1;
    state.ticket = '';
    state.requestId = '';
    cancelInflightPrepare();
    saveResume();
    clearTimeout(state.autoTimer);
    $('resultImage').hidden = true;
    $('resultEmpty').hidden = false;
    error('');
    updateButtons();
    if (!state.photo) return;
    $('prepareStatus').textContent = "설정이 준비되었습니다. '경로 추출' 버튼을 눌러주세요.";
  }
  async function showPreview(ticket, revision) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/kiosk/preview', {cache: 'no-store', signal: controller.signal,
        headers: {'X-Preview-Ticket': ticket}});
      if (!response.ok) throw new Error('미리보기를 읽을 수 없습니다. 현재 상태를 다시 확인하세요.');
      const blob = await response.blob();
      if (revision !== state.revision || ticket !== state.ticket) return;
      if (state.resultUrl) URL.revokeObjectURL(state.resultUrl);
      state.resultUrl = URL.createObjectURL(blob);
      $('resultImage').src = state.resultUrl;
      $('resultImage').hidden = false;
      $('resultEmpty').hidden = true;
      state.readyRevision = revision;
      const etaHint = typeof state.previewEstSec === 'number'
        ? ` (예상 그리기 시간 ${formatDuration(state.previewEstSec)}${state.previewStrokes ? `, ${state.previewStrokes}획` : ''})`
        : '';
      $('prepareStatus').textContent = `그림과 문구의 경로를 확인하고 그리기를 눌러주세요.${etaHint}`;
      updateButtons();
      if (!state.photo) restorePhoto(ticket, revision);
    } finally { clearTimeout(timer); }
  }
  async function restorePhoto(ticket, revision) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch('/api/kiosk/current/photo', {cache: 'no-store', signal: controller.signal,
        headers: {'X-Preview-Ticket': ticket}});
      if (!response.ok) return;
      const blob = await response.blob();
      if (revision !== state.revision || ticket !== state.ticket || state.photo) return;
      state.photo = blob;
      if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
      state.photoUrl = URL.createObjectURL(blob);
      $('capturedPreview').src = state.photoUrl; $('capturedPreview').hidden = false;
      $('camPlaceholder').hidden = true; $('btnRetake').hidden = false;
    } catch { /* 경로는 그대로 표시하고, 사진 복구 실패 시 새 첨부를 받습니다. */ }
    finally { clearTimeout(timer); }
  }
  async function preparePreview() {
    if (!state.photo || state.preparing || state.blocked || state.submitting) return;
    const revision = state.revision;
    const text = $('calligraphyText').value.trim();
    if (/[\x00-\x1f]/.test(text)) { error('제어 문자나 줄바꿈은 입력할 수 없습니다.'); return; }
    error('');
    state.preparing = true;
    state.pending = false;
    state.ticket = '';
    state.previewEstSec = null;
    state.previewStrokes = null;
    state.requestId = newId();
    state.inflightRequestId = state.requestId;
    const ctrl = new AbortController();
    state.prepareAbortController = ctrl;
    saveResume();
    updateButtons();
    startPrepareUi();
    clearTimeout(pollTimer);
    pollTimer = setTimeout(pollCurrent, 400);
    const form = new FormData();
    form.append('photo', state.photo, 'photo.png');
    form.append('text', text);
    form.append('detail', $('detailSelect').value);
    form.append('method', 'mfl_ld');
    form.append('request_id', state.requestId);
    try {
      const result = await api('/api/kiosk/prepare', {method: 'POST', body: form, signal: ctrl.signal}, 310000);
      if (revision !== state.revision) return;
      state.jobId = result.job_id;
      state.ticket = result.ticket;
      state.previewEstSec = typeof result.estimated_total_sec === 'number' ? result.estimated_total_sec : null;
      state.previewStrokes = typeof result.total_strokes === 'number' ? result.total_strokes : null;
      saveResume();
      stopPrepareUi(true);
      await showPreview(state.ticket, revision);
      $('btnRetry').hidden = true;
    } catch (exception) {
      if (revision !== state.revision || ctrl.signal.aborted) return;
      stopPrepareUi(false);
      error(exception.name === 'AbortError' ? '처리 응답이 지연됩니다. 현재 상태를 다시 확인하세요.' : exception.message);
      $('btnRetry').hidden = false;
    } finally {
      if (state.prepareAbortController === ctrl) {
        state.prepareAbortController = null;
        state.preparing = false;
        if (state.prepareTick) stopPrepareUi(false);
        updateButtons();
      }
    }
  }
  $('btnExtract').addEventListener('click', () => {
    if (!$('btnExtract').disabled) preparePreview();
  });
  function setPhoto(blob) {
    state.photo = blob;
    if (state.photoUrl) URL.revokeObjectURL(state.photoUrl);
    state.photoUrl = URL.createObjectURL(blob);
    $('capturedPreview').src = state.photoUrl;
    $('capturedPreview').hidden = false;
    $('camVideo').hidden = true;
    $('camPlaceholder').hidden = true;
    $('btnRetake').hidden = false;
    invalidate();
  }
  $('photoFileInput').addEventListener('change', () => {
    if (state.blocked) return;
    const file = $('photoFileInput').files?.[0];
    if (file) setPhoto(file);
  });
  $('calligraphyText').addEventListener('input', invalidate);
  function updateDetail() {
    const level = Number($('detailSelect').value);
    $('detailValue').textContent = `${level} · ${level < 34 ? '간략하게' : level > 66 ? '세밀하게' : '표준'}`;
  }
  $('detailSelect').addEventListener('input', () => { updateDetail(); invalidate(); });
  $('detailSelect').addEventListener('change', () => { updateDetail(); invalidate(); });
  updateDetail();
  function mirror() {
    $('camVideo').classList.toggle('mirrored', state.mirrored);
    $('btnMirror').textContent = state.mirrored ? '좌우 반전 ON' : '좌우 반전 OFF';
  }
  $('btnMirror').addEventListener('click', () => { state.mirrored = !state.mirrored; mirror(); });
  $('btnStartCam').addEventListener('click', async () => {
    if (state.blocked) return;
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('카메라를 사용할 수 없습니다. 사진을 첨부하세요.');
      const stream = await navigator.mediaDevices.getUserMedia({video: {width:{ideal:1280},height:{ideal:720},facingMode: 'user'}, audio: false});
      if (state.stream) state.stream.getTracks().forEach(track => track.stop());
      state.stream = stream;
      $('camVideo').srcObject = stream;
      $('camVideo').hidden = false;
      $('capturedPreview').hidden = true;
      $('camPlaceholder').hidden = true;
      mirror();
      updateButtons();
    } catch (exception) { error(exception.message); }
  });
  function capture() {
    const video = $('camVideo');
    if (!state.stream || state.blocked || !video.videoWidth) return;
    const revision = state.revision;
    const canvas = $('captureCanvas');
    canvas.width = 771; canvas.height = 510;
    const context = canvas.getContext('2d');
    const targetRatio=771/510, videoRatio=video.videoWidth/video.videoHeight;
    const sw=videoRatio>targetRatio ? video.videoHeight*targetRatio : video.videoWidth;
    const sh=videoRatio>targetRatio ? video.videoHeight : video.videoWidth/targetRatio;
    context.save();
    if (state.mirrored) { context.translate(771, 0); context.scale(-1, 1); }
    context.drawImage(video,(video.videoWidth-sw)/2,(video.videoHeight-sh)/2,sw,sh,0,0,771,510);
    context.restore();
    canvas.toBlob(blob => { if (blob && revision === state.revision && !state.blocked) setPhoto(blob); }, 'image/png');
  }
  $('btnCaptureNow').addEventListener('click', capture);
  $('btnCaptureTimer').addEventListener('click', () => {
    if (state.countdown || !state.stream || state.blocked) return;
    let seconds = 3;
    $('countdownOverlay').hidden = false;
    $('countdownOverlay').textContent = seconds;
    state.countdown = setInterval(() => {
      seconds -= 1;
      $('countdownOverlay').textContent = seconds;
      if (seconds <= 0) {
        clearInterval(state.countdown); state.countdown = null;
        $('countdownOverlay').hidden = true;
        capture(); updateButtons();
      }
    }, 1000);
    updateButtons();
  });
  function resetPhoto() {
    if (state.blocked || state.submitting) return;
    if (state.countdown) { clearInterval(state.countdown); state.countdown = null; }
    $('countdownOverlay').hidden = true;
    state.photo = null;
    state.pending = false;
    $('photoFileInput').value = '';
    $('capturedPreview').hidden = true;
    $('camVideo').hidden = !state.stream;
    $('camPlaceholder').hidden = Boolean(state.stream);
    $('btnRetake').hidden = true;
    invalidate();
    $('prepareStatus').textContent = '사진을 촬영하거나 첨부해 주세요.';
  }
  $('btnRetake').addEventListener('click', resetPhoto);
  $('btnResetAll').addEventListener('click', () => { $('calligraphyText').value = ''; resetPhoto(); });
  async function submitDraw() {
    if (!state.ticket || state.submitting) return;
    state.submitting = true;
    updateButtons();
    error('');
    $('jobStatusText').textContent = '작업 등록 및 실행을 시작하고 있습니다…';
    try {
      await api('/api/kiosk/draw', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ticket: state.ticket})});
      state.readyRevision = -1;
      $('prepareStatus').textContent = '작업이 등록되어 바로 실행을 시작했습니다. 아래 상태를 확인하세요.';
    } catch (exception) { error(exception.message); }
    finally { state.submitting = false; updateButtons(); pollCurrent(); }
  }
  $('btnDraw').addEventListener('click', () => {
    if (!$('btnDraw').disabled) submitDraw();
  });
  async function sendControl(cmd) {
    const snapshot = state.snapshot;
    if (!snapshot || controlSending) return;
    if (!controlPending || controlPending.job_id !== snapshot.job_id || controlPending.command !== cmd) {
      controlPending = {job_id: snapshot.job_id, command: cmd, request_id: newId(), accepted: false};
      persistControl();
    }
    controlSending = true;
    updateButtons();
    $('controlNotice').textContent = `${cmd} 요청을 전송하고 있습니다…`;
    try {
      await api('/api/kiosk/current/control', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          expected_job_id: snapshot.job_id,
          command: cmd,
          request_id: controlPending.request_id,
        }),
      });
      controlPending.accepted = true;
      persistControl();
      $('controlNotice').textContent = '요청이 수락되었습니다. 실제 로봇 상태를 확인 중입니다.';
    } catch (exception) {
      $('controlNotice').textContent = `제어 요청 오류: ${exception.message}`;
    } finally {
      controlSending = false;
      updateButtons();
      pollCurrent();
    }
  }
  $('btnPause').addEventListener('click', () => sendControl('PAUSE'));
  $('btnResume').addEventListener('click', () => sendControl('RESUME'));
  $('btnRestart').addEventListener('click', () => sendControl('CANCEL'));

  let pollTimer = null, polling = false;
  async function pollCurrent() {
    if (polling) return;
    polling = true;
    clearTimeout(pollTimer);
    const startedAt = performance.now();
    try {
      const data = await api('/api/kiosk/current', {headers: {
        'X-Prepare-Request': state.preparing ? state.inflightRequestId : state.requestId,
      }});
      state.lastPhase = data.phase;
      if (state.preparing && data.phase === 'PREPARING' && data.prepare_progress
          && data.prepare_request_id === state.inflightRequestId) {
        state.serverPrepare = {...data.prepare_progress, atMs: performance.now()};
        renderPrepareProgress();
      } else if (!state.preparing && state.prepareTick) {
        stopPrepareUi(false);
      }
      if (data.phase === 'PREVIEW' && typeof data.estimated_total_sec === 'number') {
        state.previewEstSec = data.estimated_total_sec;
        state.previewStrokes = typeof data.total_strokes === 'number' ? data.total_strokes : state.previewStrokes;
      }
      const status = data.status;
      clearTimeout(state.expiry);
      if (status && (status.error_code || (['STOPPED', 'FORCE_STOPPED', 'RECOVERY_REQUIRED'].includes(status.state) && status.message))) {
        const detail = [status.error_code, status.message].filter(Boolean).join(': ');
        $('jobErrorLog').textContent = `[${labels[status.state] || status.state}] ${detail || '오류 세부 내용 없음'}`;
        $('jobErrorLog').hidden = false;
      } else {
        $('jobErrorLog').hidden = true;
      }
      if (status && !status.stale && (status.state_confirmed || ['FORCE_STOPPED', 'RECOVERY_REQUIRED'].includes(status.state))) {
        state.snapshot = status;
        if (controlPending && controlPending.job_id === status.job_id && ['PAUSED', 'DRAWING', 'STOPPED', 'COMPLETED'].includes(status.state)) {
          controlPending = null;
          persistControl();
          $('controlNotice').textContent = '';
        }
        state.forceSeen = status.state === 'FORCE_STOPPED' || status.error_code === 'EXTERNAL_FORCE_DETECTED';
        const hasLengthPct = typeof status.progress_percent === 'number';
        const pct = hasLengthPct
          ? status.progress_percent
          : (status.total_strokes > 0 ? (status.completed_strokes / status.total_strokes) * 100 : 0);
        $('jobProgressWrap').hidden = false;
        $('jobProgress').max = 100;
        $('jobProgress').value = pct;
        const progressText = `${pct.toFixed(1)}% (${status.completed_strokes}/${status.total_strokes}획)`;
        $('jobPercent').textContent = progressText;
        if (typeof status.estimated_remaining_sec === 'number') {
          setEtaAnchor({
            remSec: status.estimated_remaining_sec,
            totalSec: typeof status.estimated_total_sec === 'number' ? status.estimated_total_sec : null,
            atMs: performance.now(),
            state: status.state,
          });
        } else {
          setEtaAnchor(null);
          $('jobEta').textContent = '';
        }
        $('jobStatusText').textContent = `${labels[status.state] || status.state} · ${progressText}`
          + (status.message ? ` — ${status.message}` : '');
        state.expiry = setTimeout(() => {
          state.snapshot = null;
          setEtaAnchor(null);
          $('jobProgressWrap').hidden = true;
          $('jobStatusText').textContent = '상태 정보가 오래되었습니다.';
          updateButtons();
        }, Math.max(0, status.valid_for_sec * 1000 - (performance.now() - startedAt)));
      } else {
        state.snapshot = null;
        setEtaAnchor(null);
        $('jobProgressWrap').hidden = true;
        const previewEta = typeof data.estimated_total_sec === 'number'
          ? ` · 예상 그리기 시간 ${formatDuration(data.estimated_total_sec)}`
          : '';
        const phases = {IDLE: '아직 시작한 작업이 없습니다.', PREPARING: '선화 변환 및 경로를 준비하고 있습니다.',
          PREVIEW: `미리보기 준비 완료${previewEta} · 그리기 승인 대기`, PREPARE_FAILED: '사진·문구를 수정해 다시 입력하세요.',
          SUBMITTING: '작업을 로봇에 전달하고 있습니다.', UNKNOWN_SUBMISSION: '로봇 상태를 확인하고 있습니다.',
          REGISTERED: '로봇 상태를 확인하고 있습니다.'};
        $('jobStatusText').textContent = phases[data.phase] || '대기 중 · 새 사진을 입력할 수 있습니다.';
      }
      if (data.phase === 'PREVIEW' && data.ticket && !state.preparing && !state.submitting
          && data.prepare_request_id === state.requestId && state.readyRevision !== state.revision) {
        $('calligraphyText').value = data.text || '';
        state.ticket = data.ticket; state.jobId = data.job_id; saveResume();
        await showPreview(state.ticket, state.revision);
      }
      updateButtons();
    } catch (exception) {
      state.snapshot = null;
      setEtaAnchor(null);
      clearTimeout(state.expiry);
      $('jobProgressWrap').hidden = true;
      $('jobStatusText').textContent = `상태 조회 대기 중: ${exception.message}`;
      updateButtons();
    } finally {
      polling = false;
      const nextMs = (state.preparing || state.lastPhase === 'PREPARING') ? 500 : 1500;
      pollTimer = setTimeout(pollCurrent, nextMs);
    }
  }
  $('btnRetry').addEventListener('click', async () => {
    await pollCurrent();
    // 원격 처리 종료가 확인된 실패에서만 새 준비 요청을 만듭니다.
    if (state.lastPhase === 'PREPARE_FAILED' && state.photo && !state.blocked) preparePreview();
  });
  api('/api/health').then(data => {
    $('engineStatus').textContent = 'MFL-LD 선화';
    if (data.prepare_estimate) {
      state.prepareEstimate = {
        lineart_sec: Number(data.prepare_estimate.lineart_sec) || 7.0,
        plan_sec: Number(data.prepare_estimate.plan_sec) || 3.5,
        total_sec: Number(data.prepare_estimate.total_sec) || 10.5,
      };
    }
  }).catch(() => { $('engineStatus').textContent = '연결 확인 필요'; });
  updateButtons();
  pollCurrent();
})();
