@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
set LOG=%~dp0snapshot.log
echo [%date% %time%] start > "%LOG%"
where uv >nul 2>nul || (echo uv 가 없습니다. & echo no uv >> "%LOG%" & pause & exit /b 1)
if exist "..\..\modu-research-nodes\local-env.cmd" call "..\..\modu-research-nodes\local-env.cmd"
if not exist ".venv\Scripts\python.exe" (
  echo 준비 중... 처음 한 번만 1~2분 걸립니다.
  uv --cache-dir ..\..\modu-research-nodes\.uv-cache venv --python 3.12 .venv >> "%LOG%" 2>&1
  uv --cache-dir ..\..\modu-research-nodes\.uv-cache pip install --python .venv\Scripts\python.exe "psycopg[binary]" >> "%LOG%" 2>&1
)
echo DB 주소를 미리 복사(Ctrl+C)해 두었다면 자동으로 읽습니다.
".venv\Scripts\python.exe" neon_snapshot.py
echo exit=%errorlevel% >> "%LOG%"
echo.
echo 끝났습니다. 이 창을 닫아도 됩니다.
pause
