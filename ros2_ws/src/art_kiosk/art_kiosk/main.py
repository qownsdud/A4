"""설치된 패키지의 웹 서버를 실행합니다."""
import os


def main():
    import uvicorn
    host = os.environ.get('ART_KIOSK_HOST', '0.0.0.0')
    port = int(os.environ.get('ART_KIOSK_PORT', '8000'))
    ssl_certfile = os.environ.get('ART_KIOSK_SSL_CERTFILE') or None
    ssl_keyfile = os.environ.get('ART_KIOSK_SSL_KEYFILE') or None
    kwargs = {}
    if ssl_certfile and ssl_keyfile:
        kwargs['ssl_certfile'] = ssl_certfile
        kwargs['ssl_keyfile'] = ssl_keyfile
    uvicorn.run('art_kiosk.server:app', host=host, port=port, **kwargs)

