# Neon 기업별 데이터 현황 노트북 사용 안내

1. ZIP을 압축 해제하고 OpenResearch_Inventory 폴더에서 실행합니다.
2. Python 3.12 이상 환경에서 설치합니다.

    python -m pip install -r requirements-inventory.txt
    python -m jupyterlab

3. .env.example을 .env로 복사하고 팀에서 받은 agent_reader 접속 주소를 DATABASE_URL에 설정합니다.
   관리 계정을 쓰지 마세요. 접속 주소를 노트북 셀·GitHub·공개 채팅에 붙여 넣지 마세요.
4. notebooks/Neon_기업별_데이터_현황.ipynb를 열고 종목·시장·기간을 수정한 뒤 위에서부터 실행합니다.
5. 기업 목록, 테이블별 기간·건수·값 결측, 추가 확보 계획 표를 확인합니다.

기본 점검: core.price_daily, core.financial_fact, core.financial_quarter,
core.disclosure, rag.document. 실제 스키마를 조회하며 날짜/기업 연결 필드가 없거나 권한이
불분명하면 0건 대신 확인 필요로 표시합니다. 날짜 결측은 기간 구분이 불가능하여 기업 전체 기준입니다.
필드 NULL 합계는 행 수와 다를 수 있습니다.

공식 거래일 CSV를 지정하면 시세 누락·중복·달력 밖 날짜도 확인합니다.
거래일 달력 없이는 정확한 누락 거래일 수를 계산하지 않습니다. 상장 기간은 따로 맞춰 주세요.
재무자료 관측일 기준과 공개일 기준은 다르며 이 도구는 과거 시점 백테스트용이 아닙니다.
문서 건수로 사업 내용·경쟁 강도·원문 위치·문서 사용 권한 확보를 확정하지 않습니다.

읽기 전용 세션, 쿼리 15초 제한, 연결 10초 제한, 기본 역할 agent_reader 검사를 적용합니다.
계정 자체의 읽기 권한은 DB 관리자가 부여해야 합니다. 앱은 SELECT와 고정된 집계만 실행합니다.
종목은 한 번에 최대 20개입니다. 비용이 큰 테이블은 시간 제한에 걸리면 해당 행에 오류로 표시합니다.

실제 Neon 접속은 제작 중 실행하지 않았습니다. 가짜 DB로 노트북 셀 7개 실행, 전체 테스트 74개 통과.
공유 전 노트북 출력 지우기를 권장합니다. 로컬 CSV 저장은 EXPORT=False가 기본입니다.
.env·private_outputs·private_data는 패키지에 포함하지 않습니다.
