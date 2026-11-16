"""v0.38 T2-3c 유상증자 계산을 엔진에 잇는다: filing.py(compute 가 기준 날짜까지의 시세와 종목코드를 받음 · 「추정」 줄) · nodes.py(N20 이 T06 시세를 넘김).
mrn/filing3.py · mrn/prob.py 는 new/ 에서 복사한다(통째로 더한 파일). 고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/filing.py': ('def compute(f, mkt, prices=None, ticker=None, snapshot=None):', [
        ("def compute(f, mkt):\n", "def compute(f, mkt, prices=None, ticker=None, snapshot=None):\n"),
        ("    def calc(name, claim, formula, value=None, unit=None):\n        F.append({'name': name, 'claim': claim, 'kind': 'derived', 'formula': formula, 'value': value, 'unit': unit})\n",
         "    def calc(name, claim, formula, value=None, unit=None):\n        F.append({'name': name, 'claim': claim, 'kind': 'derived', 'formula': formula, 'value': value, 'unit': unit})\n\n"
         "    def est(name, claim, formula, value=None, unit=None):          # v0.38 T2-3: 추정(시장 대비 확률 등) — 화면에서 「추정·가정」으로 보임\n"
         "        F.append({'name': name, 'claim': claim, 'kind': 'forecast_model', 'formula': formula, 'value': value, 'unit': unit})\n"),
        ("{'won': _won, 'p': _p, 'pct': _pct, 'check': stated_check})", "{'won': _won, 'p': _p, 'pct': _pct, 'check': stated_check, 'est': est, 'prices': prices, 'ticker': ticker or f.get('company'), 'snapshot': snapshot})"),
    ]),
    'mrn/nodes.py': ("FL.compute(f, mkt, prices=", [
        ("    F, h2, T, notes = FL.compute(f, mkt)\n    held += h2\n",
         "    F, h2, T, notes = FL.compute(f, mkt, prices=(pp['payload']['rows'] if pp else None), ticker=f['company'], snapshot=(psrc or {}).get('snapshot'))     # v0.38 T2-3: 발행가 산식은 기준 날짜까지의 시세를 씀(확률도 같은 사본)\n    held += h2\n"),
    ]),
}
todo = {}
for rel, (mark, pairs) in EDITS.items():
    s = (N / rel).read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); continue
    for old, _ in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:50]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
    todo[rel] = (s, pairs)
for rel, (s, pairs) in todo.items():
    for old, new in pairs:
        s = s.replace(old, new)
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
