@echo off
rem members/SW ·Î ¿Ã¸± ¹­À½ ¸¸µé±â(ÄÚµå¸¸). ÀÌ PCÀÇ ½ÇÁ¦ Å° °ªÀ¸·Î ºñ¹Ğ °Ë»çµµ ÇÔ
set "R=D:\AI\Projects\2Â÷_¸ğµÎÀÇ¸®¼­Ä¡_cluade"
set "G=D:\AI\Projects\OpenResearch"
chcp 65001 >nul
cd /d "%R%\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
".venv\Scripts\python.exe" -X utf8 "%R%\_tools\pr_pack\pr_pack.py" "%G%"
if errorlevel 1 (echo. & echo ë¬¶ìŒì„ ë§Œë“¤ì§€ ëª»í–ˆì–´ìš”. ìœ„ ê¸€ì„ Claude ì—ê²Œ ë³´ì—¬ ì£¼ì„¸ìš”. & pause & exit /b 1)
cd /d "%G%"
echo.
echo [ë°”ë€ íŒŒì¼ ìˆ˜]
git status --short members/SW | find /c /v ""
pause
