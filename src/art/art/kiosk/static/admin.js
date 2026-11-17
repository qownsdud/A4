(() => {
  const $ = (id) => document.getElementById(id);
  let token = "";
  let jobId = "";
  let snapshot = null;
  let busy = false;
  let timer = null;
  let statusExpiry = null;
  let generation = 0;
  const buttons = [...document.querySelectorAll("[data-command]")];
  // 토큰과 달리 요청 ID는 재접속 뒤에도 유지합니다. 원격 처리 여부가 불명확하면 같은 ID로 재시도합니다.
  let pending = null;
  try { pending = JSON.parse(sessionStorage.getItem("a4PendingCommand") || "null"); } catch { /* 저장소 사용 불가 */ }
  function savePending(value) {
    pending = value;
    try {
      if (value) sessionStorage.setItem("a4PendingCommand", JSON.stringify(value));
      else sessionStorage.removeItem("a4PendingCommand");
    } catch { /* 메모리의 ID는 유지합니다. */ }
  }
  function notice(message) { $("adminNotice").textContent = message; }
  function updateButtons() {
    const fresh = snapshot && !snapshot.stale && snapshot.state_confirmed;
    const allowed = {
      PAUSE: ["DISPATCHING", "DRAWING"], RESUME: ["PAUSED"],
      CANCEL: ["QUEUED", "DISPATCHING", "DRAWING", "PAUSING", "PAUSED"],
    };
    buttons.forEach((button) => {
      const retry = pending && pending.job_id === jobId && pending.command === button.dataset.command;
      button.disabled = !token || busy || !fresh || (pending && !retry)
        || (!retry && !allowed[button.dataset.command].includes(snapshot.state));
    });
    $("createJobButton").disabled = busy || Boolean(pending);
  }
  function logout() {
    token = "";
    generation += 1;
    clearTimeout(timer);
    clearTimeout(statusExpiry);
    snapshot = null;
    $("adminToken").value = "";
    $("loginPanel").hidden = false;
    $("adminPanel").hidden = true;
    $("adminProgress").hidden = true;
    $("adminStatus").textContent = "현재 상태 미확정";
    updateButtons();
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), path.includes('/artwork/') ? 155000 : 8000);
    try {
      const res = await fetch(path, {
        ...options, cache: "no-store", signal: controller.signal,
        headers: { "Authorization": `Bearer ${token}`, "Content-Type": "application/json" },
      });
      const data = await res.json();
      if (!res.ok) {
        if (res.status === 401 || res.status === 403) logout();
        const detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        const error = new Error(detail || `HTTP ${res.status}`);
        error.status = res.status;
        error.detail = data.detail;
        throw error;
      }
      return data;
    } finally { clearTimeout(timeout); }
  }
  async function poll(current) {
    const startedAt = performance.now();
    try {
      const data = await api(`/api/admin/jobs/${encodeURIComponent(jobId)}`);
      if (current !== generation) return;
      snapshot = data;
      clearTimeout(statusExpiry);
      $("adminProgress").hidden = data.stale || !data.state_confirmed;
      if (data.stale || !data.state_confirmed) {
        $("adminStatus").textContent = `실제 상태 미확정 · 마지막 보고 ${data.state} · ${data.error_code || "오래된 정보"}`;
      } else {
        $("adminProgress").max = data.total_strokes;
        $("adminProgress").value = data.completed_strokes;
        $("adminStatus").textContent = `${data.state} · ${data.completed_strokes}/${data.total_strokes}획 · 수신 ${data.age_sec.toFixed(1)}초 전`;
        statusExpiry = setTimeout(() => {
          if (current !== generation) return;
          snapshot = null;
          $("adminProgress").hidden = true;
          $("adminStatus").textContent = "상태 정보가 오래되었습니다. 실제 상태 미확정";
          updateButtons();
        }, Math.max(0, data.valid_for_sec * 1000 - (performance.now() - startedAt)));
      }
    } catch (error) {
      if (current !== generation) return;
      snapshot = null;
      clearTimeout(statusExpiry);
      $("adminProgress").hidden = true;
      $("adminStatus").textContent = `연결·상태 미확정: ${error.message}`;
    } finally {
      if (current === generation) {
        updateButtons();
        timer = setTimeout(() => poll(current), 1500);
      }
    }
  }
  function watch(id) {
    jobId = id;
    $("adminJobId").value = id;
    snapshot = null;
    $("adminProgress").hidden = true;
    $("adminStatus").textContent = "상태 확인 중...";
    clearTimeout(timer);
    clearTimeout(statusExpiry);
    generation += 1;
    updateButtons();
    poll(generation);
  }
  $("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    token = $("adminToken").value;
    $("adminToken").value = "";
    $("loginButton").disabled = true;
    try {
      await api("/api/admin/session");
      $("loginPanel").hidden = true;
      $("adminPanel").hidden = false;
      notice(pending ? "미확정 요청이 남아 있습니다. 해당 작업 상태 확인 후 같은 명령으로 재시도하세요." : "관리자 인증 완료");
      if (pending) watch(pending.job_id);
    } catch (error) {
      logout();
      notice(`인증 실패: ${error.message}`);
    } finally { $("loginButton").disabled = false; }
  });
  $("logoutButton").addEventListener("click", () => { logout(); notice("로그아웃했습니다."); });
  $("watchForm").addEventListener("submit", (event) => {
    event.preventDefault();
    if (!busy) watch($("adminJobId").value.trim());
  });
  buttons.forEach((button) => button.addEventListener("click", async () => {
    if (busy || button.disabled) return;
    const command = button.dataset.command;
    // randomUUID가 없는 브라우저에서도 암호학적 난수로 ID를 만듭니다.
    if (!pending) {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      const id = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
      savePending({ job_id: jobId, command, request_id: id });
    }
    busy = true;
    const sent = { ...pending };
    const current = generation;
    updateButtons();
    notice(`${command} 요청 중: 아직 실제 상태를 확정하지 않았습니다.`);
    try {
      const data = await api(`/api/admin/jobs/${encodeURIComponent(sent.job_id)}/control`, {
        method: "POST", body: JSON.stringify({ command: sent.command, request_id: sent.request_id }),
      });
      savePending(null);
      if (current === generation) notice(`${data.manager_state} · ${data.notice}`);
    } catch (error) {
      // 오래된 상태로 중계가 거부되어도 이전 전송은 처리되었을 수 있습니다.
      // Manager의 명시적 거부 응답과 입력 오류일 때만 ID를 해제합니다.
      if ([404, 422].includes(error.status)
          || (error.status === 409 && error.detail?.accepted === false)) savePending(null);
      if (current === generation) notice(`요청 결과 미확정 또는 거부: ${error.message}${pending ? " · 같은 명령 재시도 시 요청 ID를 유지합니다." : ""}`);
    } finally {
      busy = false;
      if (token && current === generation) watch(jobId);
      updateButtons();
    }
  }));
  $("prepareForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || pending) return;
    busy = true;
    $("prepareButton").disabled = true;
    updateButtons();
    const id = $("prepareJobId").value.trim();
    try {
      const data = await api(`/api/admin/artwork/${encodeURIComponent(id)}/prepare`, {
        method: "POST", body: JSON.stringify({text: $("calligraphyText").value}),
      });
      $("newJobId").value = data.job_id;
      $("planPath").value = data.plan_path;
      $("preparedInfo").textContent = `SVG: ${data.preview_path} · 생성된 계획을 검토 후 별도로 등록하세요.`;
      $("ackStart").checked = false;
    } catch (error) {
      notice(`계획 생성 실패 또는 결과 미확정: ${error.message}`);
    } finally {
      busy = false;
      $("prepareButton").disabled = false;
      updateButtons();
    }
  });
  $("createJobForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || pending) return;
    busy = true;
    updateButtons();
    const body = { job_id: $("newJobId").value.trim(), plan_path: $("planPath").value.trim() };
    const current = generation;
    try {
      const data = await api("/api/admin/jobs", { method: "POST", body: JSON.stringify(body) });
      if (current === generation) notice(`등록 요청 수락 · ${data.manager_state}. 완료 상태는 별도 확인하세요.`);
    } catch (error) {
      if (current === generation) notice(`등록 실패 또는 결과 미확정: ${error.message} · 새 작업 ID로 자동 재시도하지 마세요.`);
    } finally {
      busy = false;
      if (token && current === generation) watch(body.job_id);
      updateButtons();
    }
  });
})();
