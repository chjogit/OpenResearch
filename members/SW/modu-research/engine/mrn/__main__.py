"""Start: python -m mrn  (port MODU_NODES_PORT, default 4395; data MODU_NODES_DATA_DIR, default ./data).
Refuses to start if the port is already in use, so an existing app is never overwritten."""
import os
import socket
import sys


def port_free(port):
    """True unless something is already listening on 127.0.0.1:port.
    (A bind test would also fail on TIME_WAIT right after our own restart.)"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) != 0


def main():
    port = int(os.environ.get('MODU_NODES_PORT', '4395'))
    if not port_free(port):
        print(f'[중단] 포트 {port}가 이미 사용 중입니다. 기존 앱을 건드리지 않기 위해 시작하지 않습니다. '
              f'MODU_NODES_PORT로 다른 포트를 지정하세요.', file=sys.stderr)
        sys.exit(3)
    import secrets
    from pathlib import Path
    import uvicorn
    from .server import create_app, ROOT
    data_dir = Path(os.environ.get('MODU_NODES_DATA_DIR') or ROOT / 'data')
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(24)
    (data_dir / 'stop-token.txt').write_text(token, encoding='utf-8')  # only stop.cmd of this app can stop it
    app = create_app(str(data_dir), port=port, stop_token=token)
    from .autocheck import start_scheduler                     # v0.38 T2-1: 앱이 켜져 있는 동안만 관심 종목 공시 목록 확인(MODU_AUTOCHECK=0이면 끔)
    start_scheduler(app.state.store)
    print(f'모두의리서치 노드 0.1.0 → http://127.0.0.1:{port}/  (종료: Ctrl+C 또는 stop.cmd)')
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


if __name__ == '__main__':
    main()
