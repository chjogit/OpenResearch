@echo off
chcp 65001 >nul
set PYTHONUTF8=1
cd /d "%~dp0..\..\modu-research-nodes"
if exist local-env.cmd call local-env.cmd
if "%DART_API_KEY%%MODU_NODES_DART_KEY%"=="" (
  echo DART 키가 없어요. modu-research-nodes\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.
  pause
  exit /b 1
)
echo v0.38 T1 시험 받기: 배당 결정 · 잠정실적 원문 (10개 회사, 2025년부터)
echo 삼성전자 SK하이닉스 현대차 KB금융 기아 NAVER LG화학 한미반도체 유한양행 KT^&G — 몇 분, 수 MB 정도예요.
echo 중간에 끊기거나 하루 호출 한도에 걸리면 다시 실행하세요. 이미 받은 것은 건너뛰고 이어서 받습니다.
".venv\Scripts\python.exe" -m mrn.dartdocs fetch --companies 005930,000660,005380,105560,000270,035420,051910,042700,000100,033780 --kinds dividend,prelim --from 2025-01-01
".venv\Scripts\python.exe" -m mrn.dartdocs verify
echo.
echo 끝. 받은 원문은 _sources\dart_docs 에 있습니다(받은 그대로, 고치지 않음).
pause
