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
echo v0.38 T2-4 시험용 표본 받기: 엔진 시세 사본 210개사의 「전환가액의 조정」 공시 (2021년 10월부터, 신주인수권 행사가액·교환가액 조정 포함)
echo 리픽싱 계산이 회사가 실제로 정한 조정 가액과 맞는지 대조하려는 것입니다. 근거 사본과 섞지 않고 _sources\dart_docs_samples 에 따로 둡니다.
echo 회사마다 한 줄씩 진행이 나옵니다. 30~60분쯤 걸려요. 중간에 끊기면 다시 실행하세요. 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartsamples fetch-snapshot --kinds cv_adjust --from 2021-10-01 --limit 1500
echo.
echo 끝. 이 창의 마지막 몇 줄을 확인해 주세요.
pause
