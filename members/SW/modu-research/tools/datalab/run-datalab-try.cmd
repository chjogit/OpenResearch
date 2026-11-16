@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
if "%NAVER_HUB_ID%%NAVER_CLIENT_ID%"=="" (
  echo 데이터랩 키가 없어요. modu-research-nodes\local-env.cmd 에 NAVER_HUB_ID·NAVER_HUB_SECRET 를 넣어 주세요.
  echo 예시는 local-env.example.cmd 맨 아래에 있어요.
  pause
  exit /b 1
)
echo [시험] 삼성전자·SK하이닉스 2곳만 받아 봅니다 (호출 2번).
".venv\Scripts\python.exe" -m mrn.datalab fetch --from 2023-01-02 --only 005930,000660
".venv\Scripts\python.exe" -m mrn.datalab status
echo.
echo 잘 되면 run-datalab.cmd 로 전체를 받으세요.
pause
