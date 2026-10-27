import json
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # members/CH → ch_agents 패키지

AS_OF = "2026-10-26"
CO = {"company_id": 1, "market": "KR", "ticker": "005930", "name": "삼성전자", "krx_sector": None,
      "peer_method": "manual:반도체"}


def trading_days(n: int, end: str = "2026-10-23") -> list[str]:
    d, out = date.fromisoformat(end), []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d -= timedelta(days=1)
    return out[::-1]


def months(n: int, end: str = "2026-09-01") -> list[str]:
    y, m = int(end[:4]), int(end[5:7])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}-01")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


@pytest.fixture
def rng():
    return random.Random(7)


class FakeLLM:
    """정해 둔 응답을 차례로 돌려주는 가짜 LLM. 예외 객체를 넣으면 그 예외를 던집니다."""

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = []

    def invoke(self, msgs):
        self.calls.append(msgs)
        out = self.outputs.pop(0) if self.outputs else self.outputs_last
        self.outputs_last = out
        if isinstance(out, Exception):
            raise out
        if isinstance(out, dict):
            out = json.dumps(out, ensure_ascii=False)

        class R:
            content = out
        return R()
