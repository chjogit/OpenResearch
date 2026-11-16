@echo off
rem 화면 자동 녹화 도구 설치(한 번만): 녹화 전용 가상환경 + Playwright. 엔진 가상환경은 건드리지 않음
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
chcp 65001 >nul
cd /d "%R%\_tools\recorder"
if not exist .venv "%R%\modu-research-nodes\.venv\Scripts\python.exe" -m venv .venv
".venv\Scripts\python.exe" -m pip install --upgrade pip playwright
rem Edge 가 있으면 그것을 쓰고, 없을 때만 전용 크롬(약 150MB)을 받습니다
".venv\Scripts\python.exe" -c "import os;p=os.environ.get('ProgramFiles(x86)','')+r'\Microsoft\Edge\Application\msedge.exe';print('Edge 있음' if os.path.exists(p) else 'Edge 없음')"
if not exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" ".venv\Scripts\python.exe" -m playwright install chromium
echo.
echo 설치 끝. 이제 화면녹화.bat 을 실행하세요(시연이 켜져 있어야 합니다).
pause
