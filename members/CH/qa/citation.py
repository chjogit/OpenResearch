"""뉴스·공시 인용 숫자 대조(#66): 답 문장 속 '키 밖 숫자'를 인용한 문서 본문과 맞춰 보는 순수 함수 모음.

질의응답(`qa/`)의 답 검사에서만 쓴다. 에이전트 3·4·6 기본 경로의 Verifier(`ch_agents/llm.py`)는 바꾸지 않는다.
허용 조건: ① 문장이 문서 번호를 단다 ② 그 문서가 뉴스·공시다(개인 작성 글은 장부에 들어오지 않음) ③ 숫자가 **단위까지 같은 값으로**
문서 본문(제목·요약·근거 청크)에 있다('1.8조'='1조 8천억') ④ 문서 날짜 ≤ 기준일. 증권사 목표·가격 수준 숫자는 문서에 있어도 불허.
"""
from __future__ import annotations

import math
import re

_NUM = r"\d[\d,]*(?:\.\d+)?"
_CHUNK = rf"{_NUM}(?:\s*천)?\s*(?:조|억|만)"
# 금액: '53억', '1조 8천억', '29만500원'(원 단위 가격), '154,400원', '12.6%', '1.5배', '-507,069주' …
_MENTION = re.compile(
    rf"(?P<won_man>{_NUM}\s*만\s*(?P<rest>\d[\d,]*)\s*원)"
    rf"|(?P<amt>(?:{_CHUNK})(?:\s*(?:{_CHUNK}))*)(?:\s*(?P<cur>원|달러)|(?P<cnt>\s*(?:명|건)|개|곳|\s*주(?![가-힣])|주(?!식)))?"
    rf"|(?P<num>[-+]?{_NUM})\s*(?P<unit>%p|%|원|배|달러|bp|주|백분위)"
)
_MULT = {"조": 1e12, "억": 1e8, "만": 1e4}
TARGET_RE = re.compile(r"목표\s*(주가|가|가격)|적정\s*(주가|가격)|\bTP\b|투자의견|주가\s*(전망|예상)|상승\s*여력")
PRICE_CTX_RE = re.compile(r"주가|종가|시가|고가|저가|가격|시세|애프터마켓|호가|마감|장중|급락|급등|하락|상승|반등|올랐|내렸|거래됐")
CAUSAL_RE = re.compile(r"때문|영향으로|영향을\s*받|로\s*인해|으로\s*인해|관련(된다|이\s*있)|풀이|해석|원인|덕분")
SUBJECT_WORDS = ("합산", "두 종목", "시장 전체", "코스피", "코스닥", "우선주", "그룹")


# 방향어(#72): 같은 축에서 부호가 반대면 같은 숫자라도 다른 사실. 축: flow(순매수·순매도·유입·유출), chg(증감·등락·확대·축소), pl(흑자·적자)
DIR_WORDS = (
    ("flow", 1, re.compile(r"순매수|순유입|유입")), ("flow", -1, re.compile(r"순매도|순유출|유출")),
    ("chg", 1, re.compile(r"증가|늘었|늘어|늘며|늘고|상승|올랐|올라|급등|확대|개선|증액|반등")),
    ("chg", -1, re.compile(r"감소|줄었|줄어|줄며|줄고|하락|내렸|내려|급락|축소|악화|감액")),
    ("pl", 1, re.compile(r"흑자")), ("pl", -1, re.compile(r"적자")),
)
FORECAST_RE = re.compile(r"전망|추정|예상|컨센서스|추산|예측|내다")
_NOT_FORECAST = re.compile(r"예상\s*(?:보다|을\s*(?:웃|밑|넘|뛰))|(?:예상치|컨센서스)(?:를|에)?\s*(?:상회|하회|웃|밑|부합)")
RESIDUE_RES = (
    re.compile(r"\(\s*(?:사실|계산|예측|해석)\s*(?:[,，/][^()]*)?\)"),                 # '(사실, 부정, [S1…])'
    re.compile(r"\(\s*(?:긍정|부정|중립)\s*[,，][^()]*\)"),
    re.compile(r"\[\s*[A-Z]\d+(?:\s*[,，·]\s*(?:[A-Z]\d+|…|\.\.\.))*\s*(?:…|\.\.\.)?\s*\]"),   # '[S1,S2…]'
)


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def mentions(text: str) -> list[dict]:
    """텍스트 속 단위 있는 수치. 각 항목: {raw, value, unit, sign}. unit 은 정규화(KRW·USD·%·%p·배·주·bp·백분위), 금액은 원 단위 값."""
    out = []
    for m in _MENTION.finditer(text or ""):
        raw = m.group(0).strip()
        if m.group("won_man"):
            head = re.match(rf"({_NUM})\s*만", m.group("won_man"))
            out.append({"raw": raw, "value": _f(head.group(1)) * 1e4 + _f(m.group("rest")), "unit": "KRW", "sign": "", "span": m.span()})
        elif m.group("amt"):
            v = 0.0
            for c in re.finditer(rf"({_NUM})(\s*천)?\s*(조|억|만)", m.group("amt")):
                v += _f(c.group(1)) * (1000 if c.group(2) else 1) * _MULT[c.group(3)]
            unit = (m.group("cnt") or "").strip() or ("USD" if m.group("cur") == "달러" else "KRW")        # '1만명'(사람)·'1만원' 은 다른 값
            out.append({"raw": raw, "value": v, "unit": unit, "sign": "", "span": m.span()})
        else:
            unit = {"원": "KRW", "달러": "USD"}.get(m.group("unit"), m.group("unit"))
            n = m.group("num")
            out.append({"raw": raw, "value": abs(_f(n)), "unit": unit, "sign": n[0] if n[0] in "+-" else "", "span": m.span()})
    return out


def _window(text: str, span: tuple[int, int], width: int, clause: bool = True) -> str:
    """숫자 앞뒤 width 글자(같은 문장 안, clause 면 쉼표·세미콜론에서도 끊음)."""
    a, b = max(0, span[0] - width), min(len(text), span[1] + width)
    head = text[a:span[0]]
    for sep in (". ", ".\n", "\n", "…") + ((", ", "，", "; ") if clause else ()):
        i = head.rfind(sep)
        if i >= 0:
            a += i + len(sep)
            head = text[a:span[0]]
    tail = text[span[1]:b]
    cut = re.search(r"\.(?:\s|$)|\n|…|,\s|，|;\s" if clause else r"\.(?:\s|$)|\n|…", tail)
    if cut:
        b = span[1] + cut.start()
    return text[a:b]


def directions(win: str) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for axis, sign, rx in DIR_WORDS:
        if rx.search(win):
            out.setdefault(axis, set()).add(sign)
    return out


def direction_conflict(sent_dirs: dict[str, set[int]], doc_dirs: dict[str, set[int]]) -> bool:
    """문장의 방향어와 문서의 같은 숫자 주변 방향어가 같은 축에서 서로 반대일 때만 충돌(문서에 그 축이 없으면 충돌 아님)."""
    return any(axis in doc_dirs and not (signs & doc_dirs[axis]) for axis, signs in sent_dirs.items())


def is_forecast(*windows: str) -> bool:
    return any(FORECAST_RE.search(_NOT_FORECAST.sub("", w)) for w in windows if w)


def strip_residue(text: str) -> tuple[str, bool]:
    """답 문장에 남은 내부 표기('(사실, 부정, [S1…])', '[S1,S2]')를 지운다. 반환: (정리한 문장, 바뀌었는지)."""
    out = text
    for rx in RESIDUE_RES:
        out = rx.sub("", out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,。])", r"\1", out)
    return out, out != text


def _same(a: dict, b: dict) -> bool:
    if a["unit"] != b["unit"] or not math.isclose(a["value"], b["value"], rel_tol=1e-9, abs_tol=1e-9):
        return False
    return not (a["sign"] and b["sign"] and a["sign"] != b["sign"])      # 둘 다 부호가 있는데 다르면 다른 값


def check_numbers(text: str, docs: list[dict], as_of: str, skip: set[str] = frozenset()) -> tuple[list[dict], list[dict]]:
    """문장 속 수치를 인용 문서 본문과 대조. docs: [{key, text, published, kind}]. 반환: (통과 [{raw, doc}], 실패 [{raw, reason}]).
    skip: 허용 목록에 이미 있는 표기(질문 속 숫자·'52주' 등)."""
    ok, bad = [], []
    target = bool(TARGET_RE.search(text))
    price_ctx = bool(PRICE_CTX_RE.search(text))
    usable = [d for d in docs if str(d.get("published") or "")[:10] <= as_of]
    for m in mentions(text):
        if m["raw"] in skip:
            continue
        if target:
            bad.append({"raw": m["raw"], "reason": "증권사 목표·가격 전망 수치는 인용 불가"})
        elif m["unit"] == "KRW" and price_ctx and m["value"] < 1e7:
            bad.append({"raw": m["raw"], "reason": "주가·가격 수준 숫자는 인용 불가"})
        elif not docs:
            bad.append({"raw": m["raw"], "reason": "근거 문서 번호 없음"})
        elif not usable:
            bad.append({"raw": m["raw"], "reason": "인용 문서가 기준일 이후"})
        else:
            sent_dirs = directions(_window(text, m["span"], 10))
            hit, flipped, forecast = None, False, False
            for d in usable:
                for x in mentions(d["text"]):
                    if not _same(m, x):
                        continue
                    doc_win = _window(d["text"], x["span"], 10)
                    if direction_conflict(sent_dirs, directions(doc_win)):
                        flipped = True
                        continue
                    hit, forecast = d, is_forecast(text, _window(d["text"], x["span"], 25))
                    break
                if hit:
                    break
            if hit:
                ok.append({"raw": m["raw"], "doc": hit["key"], "forecast": forecast})
            elif flipped:
                bad.append({"raw": m["raw"], "reason": "인용 문서와 방향이 반대인 숫자"})
            elif any(x["unit"] == m["unit"] for d in usable for x in mentions(d["text"])):
                bad.append({"raw": m["raw"], "reason": "인용 문서의 값과 다른 숫자"})
            else:
                bad.append({"raw": m["raw"], "reason": "인용 문서에 없는 숫자"})
    return ok, bad


def citation_kind(doc: dict) -> str:
    return "공시" if "공시" in str(doc.get("kind") or "") else "뉴스"


def subject_note(doc: dict, sentence: str, company: str, other_names: set[str]) -> str:
    """근거 문서의 대상이 질문 종목과 다르면(우선주·다른 종목·합산·시장 전체) 그 사실. 문장에 이미 있으면 빈 문자열."""
    title = str(doc.get("title") or "")
    found = []
    if company and re.search(re.escape(company) + r"우\b", title) and company + "우" not in sentence:
        found.append(company + "우")
    for n in sorted(other_names, key=len, reverse=True):
        if len(n) >= 3 and n not in company and company not in n and n in title and n not in sentence and not any(n in f for f in found):
            found.append(n)
    found += [w for w in SUBJECT_WORDS if w in title and w not in sentence]
    return ", ".join(dict.fromkeys(found))


def strip_targets(text: str) -> str:
    """답 작성기에 주는 발췌에서 증권사 목표주가·투자의견 구절을 뺀다(어차피 인용 불가라, 보여 주면 쓰려다 문장째 제거됨)."""
    parts = re.split(r"(?<=[.!?…])\s+|\n", text or "")
    return " ".join(p for p in parts if p and not TARGET_RE.search(p))
