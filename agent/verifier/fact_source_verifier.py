"""fact_source_verifier (P0): 초안의 모든 수치를 도구 실행 기록과 1:1 대조합니다.

- 초안에서 숫자를 뽑아 ToolResult 의 값(반올림·%·억/조 단위 환산 포함)과 맞춰 봅니다.
- 하나라도 맞지 않으면 ok=False 와 불일치 목록을 돌려주고, 호출한 쪽이 Re-plan 합니다.
- 모두 맞으면 문단 끝에 출처 태그를 붙인 본문을 돌려줍니다.
"""
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from agent.db import ToolResult

NUM_RE = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+|-?\d+)(?:\.(\d+))?\s*(조|억|만|%|배)?")
UNIT = {"조": Decimal("1e12"), "억": Decimal("1e8"), "만": Decimal("1e4")}
# 문장 속 연도·분기 같은 숫자는 대조하지 않습니다
IGNORE_RE = re.compile(r"(19|20)\d{2}\s*(년|\.Q[1-4]|Q[1-4])|\bQ[1-4]\b|\d+\s*(분기|위|개|일|월)")


@dataclass
class VerifyResult:
    ok: bool
    unmatched: list[str]
    text: str


def _tool_values(results: list[ToolResult]) -> list[Decimal]:
    vals = []
    for r in results:
        for row in r.rows:
            for v in row.values():
                try:
                    vals.append(Decimal(str(v)))
                except (InvalidOperation, ValueError):
                    pass
    return vals


def _matches(num: Decimal, decimals: int, unit: str | None, vals: list[Decimal]) -> bool:
    q = Decimal(1).scaleb(-decimals)
    for v in vals:
        cands = [v]
        if unit == "%":
            cands = [v * 100, v]          # 0.1234 -> 12.34%
        elif unit in UNIT:
            cands = [v / UNIT[unit]]      # 원 단위 값을 조/억/만 으로
        for c in cands:
            if c.quantize(q) == num:
                return True
    return False


def verify(draft: str, results: list[ToolResult]) -> VerifyResult:
    vals = _tool_values(results)
    masked = IGNORE_RE.sub(lambda m: " " * len(m.group(0)), draft)
    unmatched = []
    for m in NUM_RE.finditer(masked):
        whole, frac, unit = m.group(1), m.group(2) or "", m.group(3)
        num = Decimal(whole.replace(",", "") + ("." + frac if frac else ""))
        if not _matches(num, len(frac), unit, vals):
            unmatched.append(m.group(0).strip())
    if unmatched:
        return VerifyResult(ok=False, unmatched=unmatched, text=draft)
    sources = sorted({r.source for r in results})
    tag = " ".join(f"[출처: {s}]" for s in sources)
    return VerifyResult(ok=True, unmatched=[], text=f"{draft.rstrip()} {tag}")
