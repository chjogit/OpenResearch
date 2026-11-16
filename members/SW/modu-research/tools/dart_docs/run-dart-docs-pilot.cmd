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
echo DART 공시 원문 받기 (시험: 8개 회사, 2023년부터)
echo 삼성전자 SK하이닉스 셀트리온 LG에너지솔루션 삼성바이오로직스 현대차 기아 NAVER — 몇 분 걸리고 수백 MB가 될 수 있어요.
echo 중간에 끊기거나 하루 호출 한도에 걸리면 다시 실행하세요. 이미 받은 것은 건너뛰고 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartdocs fetch --companies 005930,000660,068270,373220,207940,005380,000270,035420 --from 2023-01-01
".venv\Scripts\python.exe" -m mrn.dartdocs verify
echo.
echo 끝. 받은 원문은 _sources\dart_docs 에 있습니다(받은 그대로, 고치지 않음).
pause
