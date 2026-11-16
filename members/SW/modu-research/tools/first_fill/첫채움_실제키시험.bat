@echo off
chcp 65001 >nul
setlocal
rem 실제 키로 첫 채움 시험: 2개 회사·30일만, 시험용 폴더(tools\first_fill\out\neon)에만 씀. 진짜 자료 사본은 건드리지 않음.
set "ROOT=%~dp0..\.."
set "ENG=%ROOT%\engine"
if not exist "%ENG%\mrn" set "ENG=%ROOT%\modu-research-nodes"
if not exist "%ENG%\.venv\Scripts\python.exe" goto nosetup
if exist "%ENG%\local-env.cmd" call "%ENG%\local-env.cmd"
set "MODU_NODES_NEON_DIR=%~dp0out\neon"
echo 시험 폴더: %MODU_NODES_NEON_DIR%
echo 실제 KIS·DART 로 2개 회사만 받아 봅니다. 1~2분 걸립니다.
echo.
"%ENG%\.venv\Scripts\python.exe" -X utf8 "%~dp0first_fill.py" --tickers 005930,017670 --days 30 --new
echo.
echo 끝. 결과는 tools\first_fill\last-result.txt 에 있습니다. Claude 에게 끝났다고 알려 주세요.
pause
exit /b

:nosetup
echo [멈춤] 엔진 설치가 아직 안 됐어요. engine 폴더의 setup.cmd 를 먼저 실행하세요.
pause
exit /b 1
