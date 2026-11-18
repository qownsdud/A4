"""동일 Action·모션을 유지하는 중간 획 일시정지. 경로나 필압은 변경하지 않습니다."""
from collections import OrderedDict
import threading


class LiveMotionSession:
    """adapter.pause/resume/stop은 실제 관측 확인 뒤 반환해야 합니다.

    모션 생산자는 submit_motion으로 비동기 이동을 시작하고, 실제 종점 도달 후
    complete_motion을 호출합니다. 잠긴 동안 새 이동을 제출하거나 획을 완료하면 안 됩니다.
    """
    def __init__(self, job_id, execution_id, adapter, feedback):
        self.job_id, self.execution_id = job_id, execution_id
        self.adapter, self.feedback = adapter, feedback
        self.condition = threading.Condition(threading.RLock())
        self.state = 'RUNNING'
        self.inflight = False
        self.hold = None
        self.receipts = OrderedDict()
        self.operation = threading.Lock()

    def submit_motion(self, submit):
        """submit은 빨리 반환하는 비동기 모션 제출 함수여야 합니다."""
        with self.condition:
            if self.state != 'RUNNING' or self.inflight:
                raise RuntimeError('현재 상태에서는 새 모션을 제출할 수 없습니다.')
            self.inflight = True
            try:
                return submit()
            except Exception:
                self.state = 'FAILED'
                self.condition.notify_all()
                raise

    def complete_motion(self):
        """모션 완료 응답만으로 호출하지 말고 실제 목표 도달을 확인해야 합니다."""
        with self.condition:
            if self.state != 'RUNNING' or not self.inflight:
                return False
            self.inflight = False
            return True

    def wait_running(self, timeout=.1):
        with self.condition:
            self.condition.wait_for(lambda: self.state in ('RUNNING','STOPPING','STOPPED','FAILED','FINISHED'), timeout)
            return self.state == 'RUNNING'

    def control(self, execution_id, command, request_id):
        if execution_id != self.execution_id:
            return False, 'UNKNOWN', 'EXECUTION_MISMATCH'
        if command not in ('PAUSE','RESUME') or not request_id or len(request_id)>64:
            return False, 'UNKNOWN', 'INVALID_COMMAND'
        # 중복 요청은 드라이버를 다시 호출하지 않습니다. 동시에 온 다른 명령은 거절합니다.
        if not self.operation.acquire(blocking=False):
            return False, 'UNKNOWN', 'CONTROL_BUSY'
        try:
            with self.condition:
                if request_id in self.receipts:
                    previous, result = self.receipts[request_id]
                    if previous != command:
                        return False,'UNKNOWN','REQUEST_ID_CONFLICT'
                    current = {'RUNNING':'DRAWING','PAUSED':'PAUSED'}.get(self.state,'UNKNOWN')
                    if result[0] and result[1] != current:
                        return False,'UNKNOWN','STALE_CONTROL_RECEIPT'
                    return result
                expected = 'RUNNING' if command == 'PAUSE' else 'PAUSED'
                if self.state != expected:
                    return False, 'UNKNOWN', 'INVALID_TRANSITION'
                self.state = 'PAUSING' if command == 'PAUSE' else 'RESUMING'
                inflight = self.inflight
            try:
                if command == 'PAUSE':
                    observed = self.adapter.pause(inflight)
                else:
                    self.adapter.resume(self.hold, inflight)
                    observed = None
                with self.condition:
                    # 취소 요청이 들어온 뒤 지연된 재개 응답으로 생산 게이트를 열지 않습니다.
                    if self.state == 'STOPPING':
                        result = (False,'UNKNOWN','CANCEL_PENDING')
                    else:
                        self.hold = observed
                        self.state = 'PAUSED' if command == 'PAUSE' else 'RUNNING'
                        result = (True, 'PAUSED' if command == 'PAUSE' else 'DRAWING', '')
                    self.condition.notify_all()
            except Exception as exc:
                with self.condition:
                    if self.state != 'STOPPING':
                        self.state = 'FAILED'
                    self.condition.notify_all()
                result = (False,'UNKNOWN',str(exc)[:120])
            self.receipts[request_id] = (command,result)
            # 같은 실행 도중 영수증을 버리면 오래된 재개가 재실행될 수 있으므로 상한 초과 시 닫습니다.
            if len(self.receipts)>10000:
                with self.condition:
                    self.state='FAILED'
                return False,'UNKNOWN','CONTROL_LIMIT'
            return result
        finally:
            self.operation.release()

    def request_stop(self):
        """Action 취소 콜백이 즉시 생산 게이트를 닫습니다. 물리 정지는 worker가 확인합니다."""
        with self.condition:
            if self.state not in ('STOPPED','FINISHED'):
                self.state='STOPPING'
                self.condition.notify_all()

    def cancel(self):
        """Action Cancel 처리 경로. 실제 정지·이격을 확인한 경우만 true입니다."""
        with self.condition:
            if self.state == 'STOPPED':
                return True
            self.state = 'STOPPING'
            self.condition.notify_all()
        with self.operation:
            try:
                if self.adapter.stop() is not True:
                    raise RuntimeError('STOP_UNCONFIRMED')
                with self.condition:
                    self.state = 'STOPPED'
                    self.inflight = False
                return True
            except Exception:
                with self.condition:
                    self.state = 'FAILED'
                return False

    def finish(self):
        with self.condition:
            if self.state != 'RUNNING' or self.inflight:
                return False
            self.state = 'FINISHED'
            return True
