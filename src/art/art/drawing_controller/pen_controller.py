"""논리 펜 검증과 실제 펜 교체 경계."""
class PenController:
    def __init__(self, adapter):
        self.adapter = adapter

    def select(self, pen_id):
        if pen_id not in ('PEN_1','PEN_2','PEN_3'):
            raise ValueError('지원하지 않는 논리 펜입니다.')
        self.adapter.require_ready()
