"""DB/API 키 없이 두 Agent 입력 확인: python -m examples.persona_agents"""
import json

from sh_agents.persona_agents import build_industry_messages, build_technical_messages
from sh_agents.personas import PersonaProfile


def main():
    persona = PersonaProfile("L2", "A", confirmed=True)
    # 사용자가 확인한 경우에만 confirmed=True. 아래 자료는 가상 예시다.
    context = {
        "stock_info": {"name": "가상 기업", "ticker": "DEMO", "sector": "가상 산업"},
        "industry_bm_data": {
            "source": "가상 사업 자료", "business_model": "가상 부품 제조",
            "not_available": "제품별 매출 비중·시장점유율 자료 미제공",
        },
        "technical_data": {
            "source": "가상 지표 계산", "rsi_14": "42.0", "as_of": "2026-10-26",
            "not_available": "실제 OHLCV 없음. 계산 검증·투자 판단에 사용 불가",
        },
    }
    for builder in (build_industry_messages, build_technical_messages):
        print(json.dumps(builder(context, persona), ensure_ascii=False, indent=2))
    # 실제 생성 시 모델 출력은 수치·출처 검증기로 별도 확인해야 한다.


if __name__ == "__main__":
    main()
