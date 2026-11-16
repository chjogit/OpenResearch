@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
if "%NAVER_HUB_ID%%NAVER_CLIENT_ID%"=="" (
  echo 데이터랩 키가 없어요. modu-research-nodes\local-env.cmd 에 NAVER_HUB_ID·NAVER_HUB_SECRET 를 넣어 주세요.
  pause
  exit /b 1
)
set FROM=2023-01-02
echo 네이버 데이터랩 검색어 트렌드 받기: Neon 사본의 국내 회사 전체, %FROM% 부터 어제까지 (회사마다 호출 1번, 몇 분 걸려요)
echo 중간에 끊기거나 호출 한도에 걸리면 다시 실행하세요. 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.datalab fetch --from %FROM%
".venv\Scripts\python.exe" -m mrn.datalab status
echo.
echo 끝. stop.cmd → start.cmd 로 앱을 다시 켜면 「사람들이 얼마나 몰렸나?」에 과거 검색량이 나와요.
pause
