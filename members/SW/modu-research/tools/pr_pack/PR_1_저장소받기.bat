@echo off
rem OpenResearch(°ø¿ë ÀúÀå¼Ò) ¹Ş±â + sw ºê·£Ä¡·Î ¹Ù²Ù±â. Ã³À½ ÇÑ ¹ø(ÀÌ¹Ì ÀÖÀ¸¸é ÃÖ½ÅÀ¸·Î)
set "G=D:\AI\Projects\OpenResearch"
chcp 65001 >nul
where git >nul 2>&1
if errorlevel 1 (echo git ì´ ì—†ìŠµë‹ˆë‹¤. https://git-scm.com ì—ì„œ Git for Windows ë¥¼ ì„¤ì¹˜í•œ ë’¤ ë‹¤ì‹œ ì‹¤í–‰í•˜ì„¸ìš”. & pause & exit /b 1)
if not exist "%G%\.git" git clone https://github.com/chjogit/OpenResearch.git "%G%"
cd /d "%G%" || (pause & exit /b 1)
git fetch origin
git checkout sw 2>nul
if errorlevel 1 git checkout -b sw origin/sw 2>nul
if errorlevel 1 git checkout -b sw origin/main
git pull --no-edit origin main
set "GN="
for /f "delims=" %%a in ('git config user.name') do set "GN=%%a"
if defined GN goto named
set /p GN=ì»¤ë°‹ì— ì“¸ ì´ë¦„ì„ ì…ë ¥í•˜ì„¸ìš”: 
git config user.name "%GN%"
set /p GE=GitHub ê°€ì… ì´ë©”ì¼ì„ ì…ë ¥í•˜ì„¸ìš”: 
git config user.email "%GE%"
:named
echo.
git branch
echo ìœ„ ëª©ë¡ì—ì„œ * sw ì´ë©´ ì •ìƒì…ë‹ˆë‹¤. ë‹¤ìŒ: PR_2_ë¬¶ìŒë§Œë“¤ê¸°.bat
pause
