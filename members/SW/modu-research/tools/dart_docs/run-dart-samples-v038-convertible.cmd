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
echo v0.38 T2-3 시험용 표본 받기: 상장사 전체의 전환사채·신주인수권부사채·교환사채 발행 결정 원문 (2026년부터, 자회사 공시 제외)
echo 전환가액 조정(리픽싱) 조건 읽기와 희석 계산을 실제 원문으로 검증하려는 것입니다. 근거 사본과 섞지 않고 _sources\dart_docs_samples 에 따로 둡니다.
echo 20~40분쯤 걸려요. 20쪽마다·10건마다 진행 줄이 나옵니다. 400건을 받으면 스스로 멈춥니다. 중간에 끊기면 다시 실행하세요. 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartsamples fetch --kinds convertible --from 2026-01-01 --limit 400
echo.
echo 끝. 이 창의 마지막 몇 줄을 확인해 주세요.
pause
