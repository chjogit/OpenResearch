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
echo v0.38 T2-3 받기: 유상증자 · 감자 · 전환사채류 · 손익구조 변경 원문 (사본의 국내 회사 전체, 2025년부터)
echo 원문은 300건 안팎이고 10~20분쯤 걸려요. 이미 받은 것은 건너뜁니다. 엔진은 켜 둔 채로 실행해도 돼요.
echo 중간에 끊기면 다시 실행하세요. 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartdocs fetch --kinds rights_issue,capital_reduction,convertible,pl_change --from 2025-01-01
".venv\Scripts\python.exe" -m mrn.dartdocs verify
echo.
echo 끝. 이 창의 마지막 몇 줄(사본 건수와 해시 대조)을 확인해 주세요.
pause
