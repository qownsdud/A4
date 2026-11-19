"""실행 UUID가 일치하는 활성 세션에만 정지·재개 요청을 전달합니다."""
import threading
from rclpy.callback_groups import ReentrantCallbackGroup
from art_interfaces.srv import ControlDrawing

class LiveControlServer:
    def __init__(self, node, on_recover=None):
        self.session = None
        self.on_recover = on_recover
        self.lock = threading.RLock()
        self.service = node.create_service(ControlDrawing, '/art/control_drawing', self.control,
                                           callback_group=ReentrantCallbackGroup())
        self.timer = node.create_timer(.5, self.heartbeat, callback_group=ReentrantCallbackGroup())

    def bind(self, session):
        with self.lock:
            if self.session is not None:
                raise RuntimeError('이미 활성 실행이 있습니다.')
            self.session = session

    def unbind(self, session):
        with self.lock:
            if self.session is session:
                self.session = None

    def heartbeat(self):
        with self.lock:
            session = self.session
        if session is not None:
            with session.condition:
                if session.state not in ('STOPPED','FAILED','FINISHED'):
                    session.feedback('HEARTBEAT')

    def control(self, request, response):
        with self.lock:
            session = self.session
        if request.command == 'RECOVER' and session is None and self.on_recover is not None:
            response.accepted, response.state, response.error_code = self.on_recover()
            response.message = '도구 반납 및 홈 복귀 처리 결과입니다.'
            return response
        if session is None or session.job_id != request.job_id:
            response.accepted=False
            response.state='UNKNOWN'
            response.error_code='NO_ACTIVE_EXECUTION'
            return response
        response.accepted, response.state, response.error_code = session.control(
            request.execution_id,request.command,request.request_id)
        response.message = '실제 모션 확인 결과입니다. 획 완료나 펜 이격을 뜻하지 않습니다.'
        return response
