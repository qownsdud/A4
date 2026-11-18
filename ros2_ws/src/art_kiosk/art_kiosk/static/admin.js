(() => {
  const $ = id => document.getElementById(id);
  const buttons = [...document.querySelectorAll('[data-command]')];
  let jobId = '', snapshot = null, busy = false, timer = null, expiry = null;
  let generation = 0, polling = false, pending = null;
  const mediaKeys = {}, mediaUrls = {};
  try { pending = JSON.parse(sessionStorage.getItem('a4PendingCommand') || 'null'); } catch { /* 저장소 사용 불가 */ }
  function savePending(value) {
    pending = value;
    try {
      if (value) sessionStorage.setItem('a4PendingCommand', JSON.stringify(value));
      else sessionStorage.removeItem('a4PendingCommand');
    } catch { /* 메모리의 요청 ID는 유지합니다. */ }
  }
  function notice(text) { $('adminNotice').textContent = text; }
  function updateButtons() {
    const fresh = snapshot && !snapshot.stale && snapshot.state_confirmed;
    const allowed = {PAUSE: ['DISPATCHING', 'DRAWING'], RESUME: ['PAUSED'],
      CANCEL: ['QUEUED', 'DISPATCHING', 'DRAWING', 'PAUSING', 'PAUSED', 'RESUMING']};
    buttons.forEach(button => {
      const retry = pending && pending.job_id === jobId && pending.command === button.dataset.command;
      button.disabled = Boolean(busy || !fresh || (pending && !retry)
        || (!retry && !allowed[button.dataset.command].includes(snapshot.state)));
    });
  }
  function clearMedia() {
    for (const kind of ['Photo', 'Preview']) {
      if (mediaUrls[kind]) URL.revokeObjectURL(mediaUrls[kind]);
      delete mediaUrls[kind]; delete mediaKeys[kind];
      $('admin' + kind).hidden = true;
    }
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(path, {...options, cache: 'no-store', signal: controller.signal,
        headers: {'Content-Type': 'application/json'}});
      const data = await response.json();
      if (!response.ok) {
        const exception = new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
        exception.status = response.status; exception.detail = data.detail;
        throw exception;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function showMedia(kind, url, id, current) {
    if (!url || mediaKeys[kind] === id) return;
    mediaKeys[kind] = id;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(url, {cache: 'no-store', signal: controller.signal,
        headers: {'X-Expected-Job-Id': id}});
      if (!response.ok) throw new Error('미디어 준비 중');
      const blob = await response.blob();
      if (current !== generation || id !== jobId) return;
      if (mediaUrls[kind]) URL.revokeObjectURL(mediaUrls[kind]);
      mediaUrls[kind] = URL.createObjectURL(blob);
      $('admin' + kind).src = mediaUrls[kind]; $('admin' + kind).hidden = false;
    } catch {
      if (current === generation && id === jobId) delete mediaKeys[kind];
    } finally { clearTimeout(timeout); }
  }
  async function poll(current) {
    if (polling) {
      clearTimeout(timer);
      timer = setTimeout(() => poll(current), 100);
      return;
    }
    polling = true;
    clearTimeout(timer);
    const startedAt = performance.now();
    try {
      const data = await api('/api/admin/current');
      if (current !== generation) return;
      if (jobId !== (data.job_id || '')) { clearMedia(); jobId = data.job_id || ''; }
      $('adminText').textContent = data.text || '없음';
      snapshot = data.status;
      clearTimeout(expiry);
      if (snapshot && !snapshot.stale && snapshot.state_confirmed) {
        $('adminProgress').hidden = false;
        $('adminProgress').max = snapshot.total_strokes; $('adminProgress').value = snapshot.completed_strokes;
        $('adminStatus').textContent = `${snapshot.state} · ${snapshot.completed_strokes}/${snapshot.total_strokes}획`;
        if (pending && pending.job_id === jobId && ['COMPLETED', 'STOPPED'].includes(snapshot.state)) savePending(null);
        expiry = setTimeout(() => {
          if (current !== generation) return;
          snapshot = null; $('adminProgress').hidden = true;
          $('adminStatus').textContent = '상태 정보가 오래되었습니다. 실제 상태 미확정'; updateButtons();
        }, Math.max(0, snapshot.valid_for_sec * 1000 - (performance.now() - startedAt)));
      } else {
        $('adminProgress').hidden = true;
        const phases = {IDLE: '사용자 입력 대기', PREPARING: '사진·문구 경로 생성 중', PREVIEW: '사용자 그리기 승인 대기',
          PREPARE_FAILED: '이미지 처리 실패 · 사용자 재입력 대기'};
        $('adminStatus').textContent = phases[data.phase] || `실제 상태 미확정 · ${snapshot?.state || data.phase}`;
      }
      if (jobId) {
        showMedia('Photo', data.photo_url, jobId, current);
        showMedia('Preview', data.preview_url, jobId, current);
      }
      if (pending && pending.job_id !== jobId) {
        // 화면 전환 전에 놓친 이전 작업의 최종 상태를 확인합니다.
        const oldId = pending.job_id;
        try {
          const previous = await api(`/api/admin/jobs/${encodeURIComponent(oldId)}`);
          if (current === generation && pending?.job_id === oldId && !previous.stale
              && previous.state_confirmed && ['COMPLETED', 'STOPPED'].includes(previous.state)) savePending(null);
        } catch { /* 확인되지 않은 명령은 새 작업으로 재전송하지 않습니다. */ }
        if (current === generation && pending) notice('이전 작업의 명령 결과가 미확정입니다. 현재 작업으로 명령 대상을 바꾸지 않았습니다.');
      }
    } catch (exception) {
      if (current !== generation) return;
      snapshot = null; clearTimeout(expiry);
      $('adminProgress').hidden = true; $('adminStatus').textContent = `연결·상태 미확정: ${exception.message}`;
    } finally {
      polling = false;
      if (current === generation) { updateButtons(); timer = setTimeout(() => poll(current), 1500); }
    }
  }
  buttons.forEach(button => button.addEventListener('click', async () => {
    if (busy || button.disabled) return;
    if (!pending) {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      savePending({job_id: jobId, command: button.dataset.command,
        request_id: Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')});
    }
    busy = true; updateButtons();
    const sent = {...pending}, current = generation;
    notice(`${sent.command} 요청 중 · 실제 정지는 상태로 확인합니다.`);
    try {
      const data = await api('/api/admin/current/control', {method: 'POST', body: JSON.stringify({
        expected_job_id: sent.job_id, command: sent.command, request_id: sent.request_id,
      })});
      savePending(null);
      if (current === generation) notice(`${data.manager_state} · ${data.notice}`);
    } catch (exception) {
      if ([404, 422].includes(exception.status)
          || (exception.status === 409 && exception.detail?.accepted === false)) savePending(null);
      if (current === generation) notice(`요청 결과 미확정 또는 거부: ${exception.message}${pending ? ' · 재시도 시 같은 요청 ID를 유지합니다.' : ''}`);
    } finally {
      busy = false;
      if (current === generation) { clearTimeout(timer); poll(current); }
      updateButtons();
    }
  }));
  updateButtons();
  poll(generation);
})();
