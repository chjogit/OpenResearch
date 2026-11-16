@echo off
chcp 65001 >nul
setlocal
rem 매일 갱신: 가격(KIS 일별 시세) 다음 수급(KIS 투자자별 매매)을 차례로 채운다(안내서 5단계). 장 마감 16시 뒤에 실행.
set "ROOT=%~dp0..\.."
set "ENG=%ROOT%\engine"
set "TOOLS=%ROOT%\tools"
if not exist "%ENG%\mrn" set "ENG=%ROOT%\modu-research-nodes"
if not exist "%TOOLS%\price_refresh" set "TOOLS=%ROOT%\_tools"
if not exist "%ENG%\.venv\Scripts\python.exe" goto nosetup
if exist "%ENG%\local-env.cmd" call "%ENG%\local-env.cmd"
echo [1/2] 가격 갱신
"%ENG%\.venv\Scripts\python.exe" -X utf8 "%TOOLS%\price_refresh\price_refresh.py" --auto
echo.
echo [2/2] 수급 갱신
"%ENG%\.venv\Scripts\python.exe" -X utf8 "%TOOLS%\flow_refresh\flow_refresh.py" --auto
echo.
echo 끝. 화면이 켜져 있으면 새로고침하면 새 자료가 보입니다.
pause
exit /b

:nosetup
echo [멈춤] 엔진 설치가 아직 안 됐어요. engine 폴더의 setup.cmd 를 먼저 실행하세요. 안내서 1단계.
pause
exit /b 1
