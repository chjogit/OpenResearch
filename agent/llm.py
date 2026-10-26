"""Upstage Solar 모델 생성."""
from langchain_upstage import ChatUpstage

from agent import config


def get_llm(temperature: float = 0.0) -> ChatUpstage:
    if not config.UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY 가 비어 있습니다. .env 를 확인하세요.")
    return ChatUpstage(api_key=config.UPSTAGE_API_KEY, model=config.SOLAR_MODEL, temperature=temperature)
