# 제2판 공통 리서치 구조와 A기업 예시

이번 구현은 파일 기반 공통 계약과 기존 Agent 입력 연결이다. DB 이행, 웹 화면,
공동 검토 서버 권한, 실제 LLM·DB 호출은 포함하지 않는다. 기존 페르소나 분류는 변경하지 않았다.

## 파일

- agent/research_contract.py: 참조·버전·digest 검사, 변경 스냅샷, Agent별 입력
- agent/persona_agents.py: build_linked_messages 추가
- members/CH/solar_pro_4.py: PerspectiveAgent.analyze의 research_report 선택 인수
- examples/data/a_company_report_v1.json: 최초 가상 분석·반론
- examples/data/a_company_report_v2.json: 주장 수정·재검토 대기 예시
- examples/data/a_company_business.md 및 a_company_prices.json: 실제 열어볼 수 있는 합성 원문
- examples/research_example.py: 예시 재생성 및 검증

## 공통 계약

schemaVersion은 자료 형식, contentRevision은 보고서 내용, claimVersion은 주장 의미의 버전이다.
reportId·claimId·evidenceId·documentId·calculationId·nodeId·edgeId·objectionId를 사용한다.
한 스냅샷에서 claimId는 유일하며 이전 주장 버전은 history의 이전 스냅샷에 보존한다.
문서는 version·sha256·원본 경로·공개/수집시각·사용 범위를 기록한다.
파일 해시는 예시 생성 때 계산한다. 현재 validator는 버전 연결을 검사하며 파일 변경·인용의 진실성은
직접 재검증하지 않는다. 체크섬은 서명이나 접근 권한 증명이 아니다.

주장은 fact·interpretation·forecast로 구분한다. evidenceLinks는 supports·opposes·context를
구분하며 계산값은 calculationIds로 입력 근거·식·방법 버전에 연결한다.
자료 부족은 missingInformation으로 남기고 assessment=withheld로 보류한다.
원문이 없는 자료는 근거 객체나 URL을 만들어 넣지 않는다. 기존 자료의 위치 미확인 표시는
후속 DB/UI 확장 사항이며 이번 예시는 확보된 원문과 부족한 항목을 분리한다.

산업 지도에는 여섯 노드를 두고 매출→이익 관계 하나만 검토 예시로 연결했다.
다른 연결은 근거가 없으므로 자동 생성하지 않았다. 경쟁 비교 점수도 null이다.
기술적 예시는 합성 종가 101·99·97의 3거래일 평균 99와 마지막 종가 97을 비교한다.
가상 T1~T5는 실제 거래일이 아니며 미래 성과나 매매 신호 검증을 뜻하지 않는다.
analysisRelations는 장기 사업 가설과 단기 가격 위치의 기간 차이를 설명한다.

## 실행

저장소 루트, Python 3.12 이상:

    python -m examples.research_example
    pytest -q
    ruff check .

외부 서비스 없이 공통 결과 읽기:

    import json
    from agent.research_contract import validate_report, agent_view
    from agent.persona_agents import build_linked_messages
    from agent.personas import PersonaProfile

    with open('examples/data/a_company_report_v1.json', encoding='utf-8') as f:
        report = json.load(f)
    validate_report(report)
    industry = agent_view(report, 'industry_business_model')
      technical = agent_view(report, 'technical_analysis')
    messages = build_linked_messages(
        report, PersonaProfile('L2', 'A', confirmed=True), data_key='industry_bm_data')

위 메시지는 입력이며 실제 모델 분석 결과가 아니다. 프로필 confirmed는 앱이 사용자의
명시적 확인을 받은 경우에만 설정한다.

기존 CH 코드에 연결할 때는 requirements-member-ch.txt와 기존 API 설정이 필요하다.
다음 코드는 실제 LLM 호출을 일으킨다. 두 Agent만 호출하며 다른 Agent에 실제·합성 자료를 섞지 않는다.

    from members.CH.solar_pro_4 import build_six_agents
    for agent in build_six_agents():
        if agent.data_key in {'industry_bm_data', 'technical_data'}:
            result = agent.analyze({}, research_report=report)
            assert result['report_ref']['digest'] == report['digest']

응답은 unverified_llm_explanation이다. 보고서의 검증된 주장·근거를 덮어쓰지 않는다.
기존 호출은 research_report를 생략하면 그대로 동작한다. 전체 6+1 파이프라인 자동 결합은
이번 범위에 없으며 사용자가 두 Agent의 결과를 동일 보고서 참조로 추적할 수 있다.

## 변경과 반론

revise_claim은 원본을 변경하지 않고 새 보고서와 parentDigest를 만든다.
변경 주장의 근거·계산 연결은 비우고 보류로 전환하며 지도는 needs_review,
해당 Agent 결과는 not_run, 보고서는 draft가 된다. 이전 검사·승인은 지운다.
분석 간 관계와 현재 반론 목록도 새 버전에서는 비운다. 과거 반론·응답은 history에 보존되며
검토자가 새 주장에 재연결해야 한다. 다른 주장을 대상으로 한 반론도 자동 재연결하지 않는다.
샘플 v2는 승인이나 반론 해결 완료가 아니라 수정 초안이다.

서버는 사용자 권한, 미해결 핵심 반론에 의한 발행 차단, 현재 revision·digest에 묶인 승인,
동시 수정, 중복 요청, 공유 허용 필드를 별도로 구현해야 한다.
agent_view는 개인 분석 입력이며 공개용 안전한 스냅샷이 아니다.
checks·approvals는 내용 digest에서 제외되므로 이번 로컬 구조로 승인 진위를 보장하지 않는다.
history는 작은 예시용 중첩 스냅샷이며 DB 도입 시 불변 버전 테이블로 분리하는 것이 필요하다.

## 검증 범위

65개 전체 테스트 통과, ruff 통과. 외부 SDK는 기존 CH 통합 테스트에서 대체 객체를 사용했다.
깨진 ID·잘못된 버전·자료 모드 혼합·중복 ID·무단 내용 변경, 수정 후 무효화,
원본 보존, 두 Agent 입력 연결을 검사했다. 실제 모델 품질·DB·웹 권한은 검증하지 않았다.

## A기업 화면 미리보기

저장소 루트에서 다음을 실행합니다. 외부 API·DB 없이 합성 JSON을 읽습니다.

    python -m examples.serve_research --port 8767

브라우저에서 http://127.0.0.1:8767/ 를 엽니다.
산업 또는 기술적 주장을 선택하면 근거 원문·반론·버전 이력이 나타납니다.
상단에서 1판/2판을 전환하며 이전 근거와 반론의 보존, 변경 후 재검토 상태를 비교합니다.
주소의 v·c 값으로 선택한 버전·주장을 유지하며 뒤로가기·새로고침을 지원합니다.
정해진 예시 파일만 읽기 전용으로 제공하며 .env·저장소 전체를 웹에 노출하지 않습니다.
이 서버는 개발용이며 인증·공유·발행 서버가 아닙니다.
