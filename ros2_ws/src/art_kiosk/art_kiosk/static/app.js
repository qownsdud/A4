(() => {
  const $ = (id) => document.getElementById(id);
  const labels = {QUEUED: '작업 대기', DISPATCHING: '실행 시작 확인 중', DRAWING: '그리는 중',
    PAUSING: '일시정지 확인 중', PAUSED: '일시정지 확인됨', RESUMING: '멈춘 위치에서 재개 확인 중', STOPPING: '중단 확인 중',
    RESETTING: '중단점 보존 확인 중', FORCE_STOPPED: '외력 또는 보호 정지 감지', STOPPED: '중단 확인됨', COMPLETED: '작업 완료 확인됨', RECOVERY_REQUIRED: '실제 상태 확인 필요'};
  const state = {photo: null, stream: null, mirrored: true, revision: 0, readyRevision: -1,
    ticket: '', jobId: '', requestId: '', inflightRequestId: '', preparing: false, submitting: false, pending: false,
    blocked: false, prepareBlocked: false, lastPhase: 'IDLE', autoTimer: null, snapshot: null, expiry: null, resultUrl: null,
    photoUrl: null, countdown: null, forceSeen:false};
  let controlPending=null, controlSending=false;
  try { controlPending=JSON.parse(sessionStorage.getItem('a4PendingControl')||'null'); } catch {}
  function persistControl() {
    try { if(controlPending) sessionStorage.setItem('a4PendingControl',JSON.stringify(controlPending)); else sessionStorage.removeItem('a4PendingControl'); } catch { /* 저장소가 막혀도 현재 페이지의 요청 ID는 유지합니다. */ }
  }
  let resume = null;
  try { resume = JSON.parse(sessionStorage.getItem('a4CurrentPreview') || 'null'); } catch { /* 저장소 사용 불가 */ }
  if (resume) {
    state.ticket = resume.ticket || ''; state.requestId = resume.request_id || ''; state.jobId = resume.job_id || '';
    $('calligraphyText').value = resume.text || '';
    if (resume.detail) $('detailSelect').value = ({low:0,medium:50,high:100})[resume.detail] ?? resume.detail;
  }

  function saveResume() {
    try { sessionStorage.setItem('a4CurrentPreview', JSON.stringify({
      ticket: state.ticket, request_id: state.requestId, job_id: state.jobId,
      text: $('calligraphyText').value, detail: $('detailSelect').value,
    })); } catch { /* 현재 페이지 메모리로 계속합니다. */ }
  }
  function error(message) { $('errorBanner').textContent = message; $('errorBanner').hidden = !message; }
  function updateButtons() {
    $('btnDraw').disabled = !state.ticket || state.readyRevision !== state.revision
      || state.preparing || state.submitting || state.blocked;
    for (const id of ['calligraphyText', 'detailSelect', 'btnResetAll', 'btnStartCam', 'btnMirror', 'btnRetake']) {
      $(id).disabled = state.submitting;
    }
    // 사진은 다음 입력으로 선택할 수 있지만 실행 상태 미확정 중에는 서버에 보내지 않습니다.
    $('photoFileInput').disabled = state.submitting;
    $('inputNotice').textContent = state.blocked
      ? '사진·문구 입력과 새 경로 생성은 가능합니다. 그리기를 누르면 이전 그림을 안전하게 정리한 뒤 새 그림을 시작합니다.' : '';
    $('btnCaptureNow').disabled = !state.stream || state.submitting || Boolean(state.countdown);
    $('btnCaptureTimer').disabled = $('btnCaptureNow').disabled;
    const snapshot=state.snapshot;
    const previousTerminal=snapshot && snapshot.job_id!==state.jobId && ['COMPLETED','STOPPED'].includes(snapshot.state);
    const force=state.forceSeen || Boolean(snapshot?.external_force);
    $('forceNotice').hidden=!force;
    for(const [id,cmd,allowed] of [['btnPause','PAUSE',['DRAWING']],['btnResume','RESUME',['PAUSED','FORCE_STOPPED','RECOVERY_REQUIRED']],
      ['btnRestart','STOP',['DRAWING','PAUSING','PAUSED','RESUMING','FORCE_STOPPED']]]) {
      const retry=controlPending && controlPending.job_id===snapshot?.job_id && controlPending.command===cmd;
      const supersede=cmd==='STOP' && controlPending?.accepted && ['PAUSE','RESUME'].includes(controlPending.command);
      $(id).disabled=!snapshot || previousTerminal || controlSending || (force && !['RESUME','STOP'].includes(cmd)) || (controlPending ? !(retry||supersede) : !allowed.includes(snapshot.state));
    }

  }
  function newId() {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  }
  async function api(path, options = {}, timeoutMs = 7000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, {...options, cache: 'no-store', signal: controller.signal});
      const data = await response.json();
      if (!response.ok) {
        const exception = new Error(typeof data.detail === 'string' ? data.detail : (data.detail?.message || JSON.stringify(data.detail)));
        exception.status = response.status;
        throw exception;
      }
      return data;
    } finally { clearTimeout(timer); }
  }
  function invalidate() {
    state.revision += 1;
    state.readyRevision = -1;
    state.ticket = '';
    state.requestId = '';
    saveResume();
    clearTimeout(state.autoTimer);
    $('resultImage').hidden = true;
    $('resultEmpty').hidden = false;
    error('');
    updateButtons();
    if (!state.photo) return;
    $('prepareStatus').textContent = '입력이 끝나면 경로를 자동 생성합니다.';
    state.autoTimer = setTimeout(() => {
      if (state.preparing) { state.pending = true; return; }
      preparePreview();
    }, 600);
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
      $('resultImage').alt = '로봇 드로잉 경로 미리보기';
      $('resultImage').src = state.resultUrl;
      $('resultImage').hidden = false;
      $('resultEmpty').hidden = true;
      state.readyRevision = revision;
      $('prepareStatus').textContent = '그림과 문구의 경로를 확인하고 그리기를 눌러주세요.';
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
    if (!state.photo || state.preparing || state.submitting) return;
    if (state.prepareBlocked) return;
    const revision = state.revision;
    const text = $('calligraphyText').value.trim();
    if (!/^[A-Za-z ]*$/.test(text)) { error('영문 대소문자와 공백만 입력해 주세요.'); return; }
    error('');
    state.preparing = true;
    state.pending = false;
    state.ticket = '';
    state.requestId = newId();
    state.inflightRequestId = state.requestId;
    saveResume();
    updateButtons();
    $('prepareStatus').textContent = '사진과 문구의 경로를 만들고 있습니다…';
    const form = new FormData();
    form.append('photo', state.photo, 'photo.png');
    form.append('text', text);
    form.append('detail', $('detailSelect').value);
    form.append('request_id', state.requestId);
    try {
      const result = await api('/api/kiosk/prepare', {method: 'POST', body: form}, 310000);
      if (revision !== state.revision) return;
      state.jobId = result.job_id;
      state.ticket = result.ticket;
      saveResume();
      await showPreview(state.ticket, revision);
      $('btnRetry').hidden = true;
    } catch (exception) {
      if (revision !== state.revision) return;
      error(exception.name === 'AbortError' ? '처리 응답이 지연됩니다. 현재 상태를 다시 확인하세요.' : exception.message);
      $('btnRetry').hidden = false;
    } finally {
      state.preparing = false;
      updateButtons();
      if ((state.pending || revision !== state.revision) && state.photo && !state.prepareBlocked) {
        state.pending = false;
        clearTimeout(state.autoTimer);
        state.autoTimer = setTimeout(preparePreview, 0);
      }
    }
  }
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
    if (state.submitting) return;
    const file = $('photoFileInput').files?.[0];
    if (file) setPhoto(file);
    $('photoFileInput').value = '';
  });
  $('calligraphyText').addEventListener('input', invalidate);
  function updateDetail() {const level=Number($('detailSelect').value);$('detailValue').textContent=`${level} · ${level<34?'간략하게':level>66?'세밀하게':'표준'}`;}
  $('detailSelect').addEventListener('input',()=>{updateDetail();invalidate();});
  $('detailSelect').addEventListener('change',()=>{updateDetail();invalidate();});
  updateDetail();
  function mirror() {
    $('camVideo').classList.toggle('mirrored', state.mirrored);
    $('btnMirror').textContent = state.mirrored ? '좌우 반전 ON' : '좌우 반전 OFF';
  }
  $('btnMirror').addEventListener('click', () => { state.mirrored = !state.mirrored; mirror(); });
  $('btnStartCam').addEventListener('click', async () => {
    if (state.submitting) return;
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
    if (!state.stream || state.submitting || !video.videoWidth) return;
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
    canvas.toBlob(blob => { if (blob && revision === state.revision && !state.submitting) setPhoto(blob); }, 'image/png');
  }
  $('btnCaptureNow').addEventListener('click', capture);
  $('btnCaptureTimer').addEventListener('click', () => {
    if (state.countdown || !state.stream || state.submitting) return;
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
    if (state.submitting) return;
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
    if (!state.ticket || state.submitting || state.blocked) return;
    state.submitting = true;
    updateButtons();
    error('');
    $('jobStatusText').textContent = '작업 등록 및 실행을 시작하고 있습니다…';
    try {
      await api('/api/kiosk/draw', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ticket: state.ticket})}, 45000);
      state.readyRevision = -1;
      $('prepareStatus').textContent = '작업이 등록되어 바로 실행을 시작했습니다. 아래 상태를 확인하세요.';
    } catch (exception) { error(exception.message); }
    finally { state.submitting = false; updateButtons(); pollCurrent(); }
  }
  $('btnDraw').addEventListener('click', () => {
    if (!$('btnDraw').disabled) submitDraw();
  });

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
      const status = data.status;
      if(status?.external_force) state.forceSeen=true;
      else if(status && !status.stale && status.state_confirmed) state.forceSeen=false;
      state.prepareBlocked=data.can_prepare===false;
      state.blocked=data.can_draw===false || (data.can_draw===undefined && data.can_prepare===false)
        || ['SUBMITTING','UNKNOWN_SUBMISSION'].includes(data.phase)
        ;
      clearTimeout(state.expiry);
      if (status && !status.stale && status.state_confirmed) {
        state.snapshot = status;
        $('jobProgress').hidden = false;
        const total=status.total_length_mm,done=status.completed_length_mm;
        const valid=Number.isFinite(total)&&Number.isFinite(done)&&total>0&&done>=0&&done<=total+0.000001;
        $('jobProgress').hidden=!valid;$('jobProgress').max=valid?total:100;$('jobProgress').value=valid?Math.min(done,total):0;
        $('jobStatusText').textContent=`${labels[status.state]||status.state} · ${valid?`${(done/total*100).toFixed(1)}% (${done.toFixed(1)} / ${total.toFixed(1)} mm)`:'선 길이 진행률 확인 중'}`;
        if(status.message) $('controlNotice').textContent=status.message;
        if(controlPending && controlPending.job_id===status.job_id) {
          const confirmed=(controlPending.command==='PAUSE'&&status.state==='PAUSED') || (controlPending.command==='RESUME'&&status.state==='DRAWING')
            || (controlPending.command==='STOP'&&['PAUSED','STOPPED'].includes(status.state)) || (controlPending.command==='STOP'&&status.external_force)
            || (status.control_request_id===controlPending.request_id && Boolean(status.control_error)) || status.state==='RECOVERY_REQUIRED';
          if(confirmed) {controlPending=null;persistControl();}
        }
        state.expiry = setTimeout(() => {
          state.snapshot = null;
          $('jobProgress').hidden = true;
          $('jobStatusText').textContent = '상태 정보가 오래되어 실제 상태가 미확정입니다.';
          updateButtons();
        }, Math.max(0, status.valid_for_sec * 1000 - (performance.now() - startedAt)));
      } else {
        state.snapshot = null;
        $('jobProgress').hidden = true;
        const phases = {IDLE: '아직 시작한 작업이 없습니다.', PREPARING: '경로를 준비하고 있습니다.',
          PREVIEW: '미리보기 준비 완료 · 그리기 승인 대기', PREPARE_FAILED: '사진·문구를 수정해 다시 입력하세요.'};
        $('jobStatusText').textContent = status ? `${labels[status.state]||status.state} · 실제 상태 미확정 · ${status.message||''}` : (data.status_error ? `이전 작업 ${data.execution_job_id||data.job_id||''}의 실행 상태를 확인할 수 없습니다. 새 도안의 그리기를 누르면 실제 정지와 기존 그림의 정리를 자동 확인합니다.` : (phases[data.phase]||'작업 상태 확인 중'));
      }
      if (data.phase === 'PREVIEW' && data.ticket && !state.preparing && !state.submitting
          && data.prepare_request_id === state.requestId && state.readyRevision !== state.revision) {
        $('calligraphyText').value = data.text || '';
        state.ticket = data.ticket; state.jobId = data.job_id; saveResume();
        await showPreview(state.ticket, state.revision);
      }
      if (!state.prepareBlocked && state.pending && state.photo && !state.preparing && !state.submitting) {
        state.pending = false;
        clearTimeout(state.autoTimer);
        state.autoTimer = setTimeout(preparePreview, 0);
      }
      if(controlPending && status && controlPending.job_id!==status.job_id) {
        const previous=await api(`/api/kiosk/jobs/${encodeURIComponent(controlPending.job_id)}`);
        if(!previous.stale && previous.state_confirmed && ['COMPLETED','STOPPED'].includes(previous.state)) {controlPending=null;persistControl();}
      }
      updateButtons();
    } catch (exception) {
      state.snapshot = null;state.blocked=true;
      clearTimeout(state.expiry);
      $('jobProgress').hidden = true;
      $('jobStatusText').textContent = `연결 상태 미확정: ${exception.message}`;
      updateButtons();
    } finally { polling = false; pollTimer = setTimeout(pollCurrent, 1500); }
  }
  async function sendControl(command) {
    const snapshot=state.snapshot;
    if(!snapshot || controlSending) return;
    const supersede=command==='STOP'&&controlPending?.accepted&&['PAUSE','RESUME'].includes(controlPending.command);
    if(controlPending&&!supersede&&(controlPending.command!==command||controlPending.job_id!==snapshot.job_id)) return;
    if(supersede) controlPending=null;
    if(!controlPending) {controlPending={job_id:snapshot.job_id,command,request_id:newId(),run_id:snapshot.run_id||0};persistControl();}
    controlSending=true;updateButtons();
    try {
      await api('/api/kiosk/current/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_job_id:controlPending.job_id,command,request_id:controlPending.request_id})});
      if(controlPending) {controlPending.accepted=true;persistControl();}
      $('controlNotice').textContent='명령 수락 후 실제 정지·중단점 복귀 상태를 확인합니다.';
    } catch(exception) {
      if([404,409,422].includes(exception.status)){controlPending=null;persistControl();}
      $('controlNotice').textContent=exception.message+' · 응답 미확정 시 같은 버튼으로 같은 요청을 확인하세요.';
    } finally {controlSending=false;updateButtons();pollCurrent();}
  }
  $('btnPause').addEventListener('click',()=>{if(!$('btnPause').disabled)sendControl('PAUSE');});
  $('btnResume').addEventListener('click',()=>{if(!$('btnResume').disabled)sendControl('RESUME');});
  $('btnRestart').addEventListener('click',()=>{if(!$('btnRestart').disabled)sendControl('STOP');});
  $('btnRetry').addEventListener('click', async () => {
    await pollCurrent();
    // 원격 처리 종료가 확인된 실패에서만 새 준비 요청을 만듭니다.
    if (state.lastPhase === 'PREPARE_FAILED' && state.photo && !state.prepareBlocked) preparePreview();
  });
  api('/api/health').then(data => { $('engineStatus').textContent = data.engine === 'cv' ? 'OpenCV 선화' : 'DL 선화'; })
    .catch(() => { $('engineStatus').textContent = '연결 확인 필요'; });
  updateButtons();
  pollCurrent();
})();
