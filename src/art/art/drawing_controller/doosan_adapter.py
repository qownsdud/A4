"""실물 연동은 의도적으로 닫혀 있습니다. 환경변수로 우회할 수 없습니다."""
class DoosanAdapter:
    def require_ready(self):
        raise RuntimeError('M0609 모션·RG2 펜 선택·실제 이격 센서 검증이 필요합니다.')

    def move(self, pose):
        self.require_ready()
