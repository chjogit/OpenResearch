"""의미 점검: LLM 문장이 숫자 장부·코드 판정과 '방향'이 반대인지 코드로 확인합니다.

형식 검사(키 밖 숫자, 금지 표현)는 숫자가 장부 값인지만 봅니다. 그래서 값은 맞게 인용하고
뜻을 반대로 쓴 문장(예: 코스피 대비 +0.71%p 를 '초과 손실'로 해석)은 통과합니다. 여기서는 두 가지를 봅니다.

1. 판정 방향: 코드 판정에 쓰인 방향어(상회/하회, 가속/둔화, 개선/악화, 인상/인하, 원화 강세/약세,
   뚜렷한/약한)를 판정 속 키에 연결해 두고, 그 키를 인용한 문장이 반대 방향어만 쓰면 불일치로 봅니다.
2. 부호 방향: 증감을 나타내는 값(%, %p, 주, 원±, 점수)의 키 바로 뒤에 반대 부호의 서술어
   (값이 +인데 '감소·하락·순매도', 값이 -인데 '증가·상승·순매수')가 오면 불일치로 봅니다.

두 점검 모두 맞는 방향어가 함께 있으면 문제 삼지 않습니다(오탐을 줄이기 위해 보수적으로 판단).
"""
from __future__ import annotations

import re

from .facts import Facts

KEY_RE = re.compile(r"\{([A-Z]\d+)\}")

# (방향 이름, 이 방향을 뜻하는 표현, 반대 방향을 뜻하는 표현)
DIRECTIONS = [
    ("상회", ("상회", "웃돌", "앞서", "초과 수익", "덜 하락", "덜 빠"), ("하회", "밑돌", "뒤처", "초과 손실", "부진")),
    ("하회", ("하회", "밑돌", "뒤처", "초과 손실", "부진"), ("상회", "웃돌", "앞서", "초과 수익", "덜 하락", "덜 빠")),
    ("가속", ("가속",), ("둔화",)),
    ("둔화", ("둔화",), ("가속",)),
    ("개선", ("개선",), ("악화",)),
    ("악화", ("악화",), ("개선",)),
    ("인상", ("인상",), ("인하",)),
    ("인하", ("인하",), ("인상",)),
    ("원화 강세", ("원화 강세", "원화가 강세", "달러 약세"), ("원화 약세", "원화가 약세", "달러 강세")),
    ("원화 약세", ("원화 약세", "원화가 약세", "달러 강세"), ("원화 강세", "원화가 강세", "달러 약세")),
    ("뚜렷", ("뚜렷",), ("약한 동조", "약하게 동조", "동조가 약", "동조는 약", "약한 역방향")),
    ("약함", ("약한", "약하", "약함"), ("뚜렷",)),
]
# 판정 문장에서 방향어를 찾을 때 쓰는 대표 표현 (판정은 코드가 만든 정해진 문형)
FLAG_MARKERS = {
    "상회": ("상회",), "하회": ("하회",), "가속": ("가속",), "둔화": ("둔화",), "개선": ("개선",),
    "악화": ("악화",), "인상": ("인상 국면",), "인하": ("인하 국면",), "원화 강세": ("원화 강세",),
    "원화 약세": ("원화 약세",), "뚜렷": ("뚜렷",), "약함": ("약한", "약함"),
}

# 항목의 뜻과 다른 개념으로 부르는 표현 (항목 이름에 든 단어들 → 쓰면 안 되는 표현)
MISNAMED = [
    (("외국인", "평균 가격"), ("매입 단가", "매수 단가", "평균 단가", "평단")),   # 순매수일 종가 가중 평균일 뿐
    (("상관",), ("인과", "때문에", "덕분에")),                                    # 통계적 동조성
    (("대차잔고",), ("공매도 잔고", "공매도 물량")),                              # 공매도의 대용치일 뿐
]

SIGN_UNITS = {"%chg", "%p", "주", "KRW±", "score"}
POS_WORDS = ("증가", "상승", "늘어", "늘었", "개선", "확대", "순매수", "흑자", "플러스", "초과 수익", "올랐", "오름")
NEG_WORDS = ("감소", "하락", "줄어", "줄었", "악화", "축소", "순매도", "적자", "마이너스", "초과 손실", "내렸", "떨어")
WINDOW = 12  # 키 뒤 몇 글자까지 서술어로 볼지


def flag_directions(f: Facts) -> dict[str, set[str]]:
    """코드 판정 문장을 쉼표 단위로 나눠, 각 조각의 키에 그 조각의 방향어를 연결합니다."""
    out: dict[str, set[str]] = {}
    for fl in f.flags:
        for seg in re.split(r",\s*", fl):
            keys = KEY_RE.findall(seg)
            if not keys:
                continue
            text = KEY_RE.sub("", seg)
            found = set()
            for name, markers in FLAG_MARKERS.items():
                if any(mk in text for mk in markers):
                    found.add(name)
            if "뚜렷" in found:  # 한 조각에 둘 다 있으면 판정이 모호하므로 강도는 점검하지 않음
                found -= {"뚜렷", "약함"} if "약함" in found else set()
            for k in keys:
                out.setdefault(k, set()).update(found)
    return out


def _after(text: str, end: int) -> str:
    rest = text[end:end + WINDOW]
    cut = re.search(r"[{,.;]|이나|지만|으며|이며", rest)
    return rest[:cut.start()] if cut else rest


def direction_problems(text: str, f: Facts, refs: list[str] | None = None,
                       dirs: dict[str, set[str]] | None = None) -> list[str]:
    """문장 하나의 방향 불일치 목록. refs 는 주장의 근거 키(문장에 키가 없어도 근거로 연결)."""
    dirs = flag_directions(f) if dirs is None else dirs
    probs: list[str] = []
    plain = KEY_RE.sub("", text)
    keys = set(KEY_RE.findall(text)) | set(refs or [])
    by_name = {n: (own, opp) for n, own, opp in DIRECTIONS}
    for k in sorted(keys):
        for name in dirs.get(k, ()):
            own, opp = by_name[name]
            if any(w in plain for w in opp) and not any(w in plain for w in own):
                probs.append(f"판정 방향 불일치: {k} 는 '{name}' 판정인데 반대 표현 사용")
    for k in sorted(keys):
        label = (f.items.get(k) or {}).get("label", "")
        for need, words in MISNAMED:
            if all(w in label for w in need):
                used = [w for w in words if w in plain and not re.search(re.escape(w) + r"\S{0,3}\s*(아님|아니|이 아)", plain)]
                if used:
                    probs.append(f"개념 오용: {k}({label})를 '{used[0]}'로 표현")
    for m in KEY_RE.finditer(text):
        it = f.items.get(m.group(1))
        if not it or it["unit"] not in SIGN_UNITS or not it["value"]:
            continue
        after = _after(text, m.end())
        pos, neg = any(w in after for w in POS_WORDS), any(w in after for w in NEG_WORDS)
        if it["value"] > 0 and neg and not pos or it["value"] < 0 and pos and not neg:
            probs.append(f"부호 불일치: {m.group(1)}={it['text']} 인데 '{after.strip()}'")
    return probs
