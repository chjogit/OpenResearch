"""미확인 항목을 '어떻게 채울 수 있는지'로 나눕니다 (데이터 계약 r4-1.1 unverified[].availability).

화면이 "모른다"를 "아직 수집 중"·"공시에 일부 있음"·"공시 없음"으로 구분해 보여 주게 하려는 것입니다.
규칙은 위에서부터 처음 맞는 것을 씁니다. 항목 이름을 먼저 보고, 맞는 규칙이 없으면 사유까지 봅니다.
"""
from __future__ import annotations

import re

AVAILABILITY = {
    "collecting": "수집 중 (시간이 지나거나 수집이 돌면 채워짐)",
    "partial_disclosure": "공시에 일부 있음 (원문 추가 추출 필요)",
    "not_disclosed": "공시 없음 (대용치로만 짐작 가능)",
    "not_verified": "검증 미통과 (해당 문장을 출력에서 뺌)",
    "unclassified": "분류 전",
}
AVAIL_SHORT = {"collecting": "수집 중", "partial_disclosure": "공시에 일부 있음", "not_disclosed": "공시 없음",
               "not_verified": "검증 미통과", "unclassified": "분류 전"}
AVAILABILITY_RULES = (
    ("not_verified", re.compile(r"반대 근거·하방 위험")),
    ("not_disclosed", re.compile(r"판가\s*전가|결제\s*통화|달러\s*비용|원재료.{0,6}통화|계약\s*구조|경쟁\s*강도")),
    ("collecting", re.compile(r"수집|감성|수급|거래일\s*미만|\d+일\s*미만|문서\s*\d+건|기간\s*짧|지연|분기\s*재무|최소\s*\d+건|적용\s*전")),
    ("partial_disclosure", re.compile(r"헤지|파생|차입|변동.{0,3}고정|금리\s*비중|만기|지분율|금액|공시|수출\s*매출\s*비중")),
)


def availability(item: str, reason: str = "") -> str:
    """미확인 항목 → AVAILABILITY 키. 항목 이름을 먼저 보고, 맞는 규칙이 없으면 사유까지 봅니다."""
    for text in (item, f"{item} {reason}"):
        for code, rx in AVAILABILITY_RULES:
            if rx.search(text or ""):
                return code
    return "unclassified"
