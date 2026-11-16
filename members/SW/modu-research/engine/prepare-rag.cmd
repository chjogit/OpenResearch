@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist local-env.cmd call local-env.cmd
echo [1/3] 사업보고서 원문 색인 생성
.venv\Scripts\python.exe -X utf8 -m mrn.rag build || goto :err
echo [2/3] 임베딩 생성 (Ollama 필요, 모델: %MODU_NODES_EMBED_MODEL%)
.venv\Scripts\python.exe -X utf8 -m mrn.rag embed || echo 임베딩을 건너뜁니다. BM25 검색만 사용합니다.
echo [3/3] 검색 평가
.venv\Scripts\python.exe -X utf8 -m mrn.rag eval
echo 완료. 서버를 다시 시작하면 새 색인을 씁니다 (stop.cmd → start.cmd).
pause
exit /b 0
:err
echo 색인 생성 실패
pause
exit /b 1
