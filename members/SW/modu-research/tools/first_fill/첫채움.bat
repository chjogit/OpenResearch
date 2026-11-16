@echo off
chcp 65001 >nul
setlocal
rem 첫 채움: 빈 PC에서 본인 KIS·DART 키로 처음 자료 사본을 만든다(안내서 3단계). 자료가 이미 있으면 덮지 않고 멈춘다.
set "ROOT=%~dp0..\.."
set "ENG=%ROOT%\engine"
if not exist "%ENG%\mrn" set "ENG=%ROOT%\modu-research-nodes"
if not exist "%ENG%\.venv\Scripts\python.exe" goto nosetup
if exist "%ENG%\local-env.cmd" call "%ENG%\local-env.cmd"
echo 첫 채움을 시작합니다. 기본 20개 회사, 보통 5~10분 걸립니다. 창을 닫지 마세요.
echo.
"%ENG%\.venv\Scripts\python.exe" -X utf8 "%~dp0first_fill.py" %*
echo.
echo 결과는 tools\first_fill\last-result.txt 에도 남습니다.
pause
exit /b

:nosetup
echo [멈춤] 엔진 설치가 아직 안 됐어요. engine 폴더의 setup.cmd 를 먼저 실행하세요. 안내서 1단계.
pause
exit /b 1
