@echo off
rem ElevenLabs 목소리 시험(같은 문장을 한국어 목소리 4개로)
set "R=D:\AI\Projects\2차_모두의리서치_cluade"
cd /d "%R%\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
chcp 65001 >nul
".venv\Scripts\python.exe" -X utf8 "%R%\_tools\voice\tts_make.py" sample
echo.
start "" "%R%\_tools\voice\out"
pause
