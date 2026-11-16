@echo off
rem 계획 에이전트에 AI 모델을 쓰려면 이 파일을 local-env.cmd 로 복사한 뒤 아래 줄 앞의 rem 을 지우세요.
rem 설정하지 않으면 키워드 계획만 씁니다(앱은 그대로 동작).
rem 로컬 Ollama 예시 (OpenAI 호환 주소):
rem set MODU_NODES_LLM_URL=http://127.0.0.1:11434/v1
rem set MODU_NODES_LLM_MODEL=qwen3.8:27b
rem 클라우드 모델을 쓸 때만 키를 넣습니다. 키는 서버에서만 쓰이고 브라우저·로그에 나오지 않습니다.
rem set MODU_NODES_LLM_KEY=
rem set MODU_NODES_LLM_TIMEOUT=30
rem 한국투자증권 Open API (실전투자용 앱키 · 조회만). 첫 채움·가격/수급 갱신·장중 급등 확인에서 사용. 서버에서만 쓰이고 화면·로그·저장 파일에 남지 않습니다.
rem set KIS_APP_KEY=
rem set KIS_APP_SECRET=
rem DART OpenAPI 키 (재무데이터 XBRL 조회용). 서버에서만 쓰이며 화면·로그·저장 파일에 남지 않습니다.
rem set DART_API_KEY=
rem 사업보고서 검색용 임베딩 모델 (prepare-rag.cmd 에서 사용)
rem set MODU_NODES_EMBED_MODEL=embeddinggemma:300m
rem set MODU_NODES_OLLAMA=http://127.0.0.1:11434
rem 네이버 데이터랩 검색어 트렌드 (과거 검색량, _tools\datalab\run-datalab.cmd 에서 사용). 둘 중 하나만 넣으세요.
rem 새 키: 네이버 클라우드 콘솔 > NAVER API HUB 에서 애플리케이션 등록 후 발급 (검색어 트렌드 월 5만 회)
rem set NAVER_HUB_ID=
rem set NAVER_HUB_SECRET=
rem 옛 키: 개발자센터(developers.naver.com)에서 2026-07-31 이전에 발급받은 키만, 2027-06-30까지 사용 가능 (하루 1,000회)
rem set NAVER_CLIENT_ID=
rem set NAVER_CLIENT_SECRET=
