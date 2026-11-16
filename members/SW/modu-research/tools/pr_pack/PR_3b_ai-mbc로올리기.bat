@echo off
rem OpenResearch �� ai-mbc �������� �ø���(gregkim0704 �α����� �״�� ��). Ŀ���� PR_3 ���� �̹� ��
set "G=D:\AI\Projects\OpenResearch"
chcp 65001 >nul
cd /d "%G%" || (pause & exit /b 1)
git remote set-url origin https://ai-mbc@github.com/chjogit/OpenResearch.git
git log -1 --oneline
echo.
echo GitHub 로그인 창(또는 브라우저)이 뜨면 ai-mbc 계정으로 로그인하세요.
git push -u origin sw
if errorlevel 1 (echo. & echo 아직 안 됩니다. 화면을 Claude 에게 보여 주세요. ai-mbc 도 권한이 없으면 철현님께 쓰기 권한(Collaborator)을 요청해야 합니다. & pause & exit /b 1)
start "" "https://github.com/chjogit/OpenResearch/compare/main...sw?expand=1"
echo.
echo 올리기 완료. 열린 GitHub 화면에서 설명을 붙여 넣고 [Create pull request] 를 누르세요.
pause
