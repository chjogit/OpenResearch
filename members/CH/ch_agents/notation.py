"""값 표기 바로잡기(#60): 부호 중복('+-0.250'), 같은 단위 연속('8일일'), 값 뒤 조사 불일치('1일가'). 숫자·장부 키는 바꾸지 않고 글자 표기만 고친다.

질의응답 답(qa.agent.render)과 계약 문장(contract.plain)이 같은 함수를 쓴다.
"""
from __future__ import annotations

import re

DIGIT_BATCHIM = {"0": True, "1": True, "2": False, "3": True, "4": False, "5": False, "6": True, "7": True, "8": True, "9": False}      # 영·일·이·삼·사·오·육·칠·팔·구
UNIT_BATCHIM = {"%": False, "p": False, "배": False, "주": False, "위": False, "원": True, "일": True, "건": True, "개": False, "점": True}  # 퍼센트·포인트·배·주·위·원·일·건·개·점
JOSA = {"이": ("이", "가"), "가": ("이", "가"), "은": ("은", "는"), "는": ("은", "는"), "을": ("을", "를"), "를": ("을", "를"),
        "과": ("과", "와"), "와": ("과", "와"), "으로": ("으로", "로"), "로": ("으로", "로")}
UNITS = "백분위|%p|%|배|조원|억원|원|주|일|건|개|점"
VALUE_JOSA_RE = re.compile(rf"(\d[\d,]*(?:\.\d+)?(?:{UNITS})?)(으로|이|가|은|는|을|를|과|와|로)(?![가-힣])")
DOUBLE_SIGN_RE = re.compile(r"[+\-\u2212]\s*([+\-\u2212])(?=\d)")
DUP_UNIT_RE = re.compile(r"(\d)(백분위|%p|%|배|조원|억원|원|주|일)\2(?!차|간|째|부|분|치)")


def has_batchim(token: str) -> tuple[bool, bool]:
    """값 표기 끝 글자를 읽는 소리 기준으로 (받침 있음, ㄹ받침)."""
    c = token[-1]
    if c in DIGIT_BATCHIM:
        return DIGIT_BATCHIM[c], c in "178"
    if c in UNIT_BATCHIM:
        return UNIT_BATCHIM[c], c == "일"
    if "가" <= c <= "힣":
        b = (ord(c) - 0xAC00) % 28
        return b != 0, b == 8
    return False, False


def _fix_josa(text: str) -> str:
    def josa(m: re.Match) -> str:
        batchim, rieul = has_batchim(m.group(1))
        with_b, without = JOSA[m.group(2)]
        if with_b == "으로":
            return m.group(1) + ("로" if (not batchim or rieul) else "으로")
        return m.group(1) + (with_b if batchim else without)

    return VALUE_JOSA_RE.sub(josa, text)


def fix_notation(text: str) -> str:
    """부호 중복은 값에 붙은 부호만 남기고, 같은 단위 연속은 한 번만, 값 뒤 조사는 읽는 소리에 맞게 고친다(멱등)."""
    text = DOUBLE_SIGN_RE.sub(lambda m: m.group(1), text)
    return _fix_josa(DUP_UNIT_RE.sub(r"\1\2", text))


def notation_problems(text: str) -> list[str]:
    """화면에 나가기 전 검사. fix_notation 을 거친 글은 빈 목록이어야 한다."""
    bad = []
    if DOUBLE_SIGN_RE.search(text):
        bad.append("부호 중복")
    if DUP_UNIT_RE.search(text):
        bad.append("같은 단위 연속")
    if _fix_josa(text) != text:
        bad.append("값 뒤 조사 불일치")
    return bad
