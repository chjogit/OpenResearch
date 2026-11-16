@echo off
chcp 65001 >nul
setlocal
rem 처음부터 시험 준비: 팀원이 받는 것과 같은 깨끗한 작업 폴더를 원본 옆에 새로 만든다. 원본은 읽기만 한다.
set "R=%~dp0..\.."
set "PY=%R%\modu-research-nodes\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
"%PY%" -X utf8 "%~dp0fresh_copy.py"
echo.
echo 위에 나온 폴더를 열고, 따라하기_안내서.md 1단계부터 해 보세요.
pause
