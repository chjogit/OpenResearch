@echo off
rem sw �귣ġ�� Ŀ�ԡ��ø��� �� PR ����� ȭ�� ����
set "G=D:\AI\Projects\OpenResearch"
chcp 65001 >nul
cd /d "%G%" || (pause & exit /b 1)
set "B="
for /f "delims=" %%b in ('git branch --show-current') do set "B=%%b"
if not "%B%"=="sw" (echo 지금 브랜치가 sw 가 아닙니다. PR_1 을 먼저 실행하세요. & pause & exit /b 1)
git add members/SW
git commit -m "SW: 모두의리서치 엔진·화면 통합 패치·운영 도구 v0.39.5 (코드만, 자료·키 제외)"
git push -u origin sw
if errorlevel 1 (echo. & echo 올리기에 실패했어요. GitHub 로그인 창이 뜨면 ai-mbc 계정으로 로그인 후 다시 실행하세요. 권한이 없다는 글이면 철현님께 저장소 쓰기 권한을 요청하세요. & pause & exit /b 1)
start "" "https://github.com/chjogit/OpenResearch/compare/main...sw?expand=1"
echo.
echo 열린 GitHub 화면에서 제목과 체크리스트를 확인하고 [Create pull request] 를 누르세요.
pause
