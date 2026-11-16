@echo off
rem ElevenLabs 목소리목록 (키는 local-env.cmd 에서만 읽음)
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
cd /d "%R%\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
chcp 65001 >nul
".venv\Scripts\python.exe" -X utf8 "%R%\_tools\voice\tts_make.py" voices
echo.
pause
