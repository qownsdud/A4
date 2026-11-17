"""설치된 패키지의 웹 서버를 실행합니다."""
import os
def main():
    import uvicorn
    uvicorn.run('art.kiosk.server:app', host=os.environ.get('ART_KIOSK_HOST','127.0.0.1'), port=int(os.environ.get('ART_KIOSK_PORT','8000')))
