@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
if "%DART_API_KEY%%MODU_NODES_DART_KEY%"=="" (
  echo DART 키가 없어요. modu-research-nodes\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.
  pause
  exit /b 1
)
echo v0.38 T1 전체 받기: 배당 결정 · 잠정실적 원문 (사본의 국내 회사 전체, 2025년부터)
echo 회사 210곳이라 30분~1시간 걸릴 수 있어요. 이미 받은 것은 건너뜁니다. 엔진은 켜 둔 채로 실행해도 돼요.
echo 중간에 끊기거나 하루 호출 한도에 걸리면 다시 실행하세요. 이미 받은 것은 건너뛰고 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartdocs fetch --kinds dividend,prelim --from 2025-01-01
".venv\Scripts\python.exe" -m mrn.dartdocs verify
echo.
echo 끝. 받은 원문은 _sources\dart_docs 에 있습니다(받은 그대로, 고치지 않음).
pause
