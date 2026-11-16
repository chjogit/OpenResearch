"""v0.38 T2-3b 손익구조 변경 계산을 엔진에 잇는다: filing.py(종류·읽기·계산 넘기기) · nodes.py(문구 2곳). mrn/filing2.py 는 new/ 에서 복사. 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/filing.py': ('from . import filing2 as F2', [
        ("RULE = 'filing-calc-v1'\n", "from . import filing2 as F2                                   # v0.38 T2-3 1등급 나머지 종류\n\nRULE = 'filing-calc-v1'\n"),
        ("KINDS = ('retire', 'buyback_decision', 'dividend', 'prelim')\n", "KINDS = ('retire', 'buyback_decision', 'dividend', 'prelim') + F2.KINDS2\n"),
        ("'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적'}\n_DEC", "'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적', **F2.KIND_LABEL2}\n_DEC"),
        ("'dividend': parse_dividend, 'prelim': parse_prelim}\n", "'dividend': parse_dividend, 'prelim': parse_prelim, **F2.PARSERS2}\n"),
        ("            out['docs'].append({'rcept_no': h['rcept_no'], 'sha256': h['sha256']})\n    return out\n",
         "            out['docs'].append({'rcept_no': h['rcept_no'], 'sha256': h['sha256']})\n"
         "    if d['kind'] in F2.KINDS2:                                # v0.38 T2-3: 같은 결산의 앞선 공시(정정 전)와 뒤의 정정본\n"
         "        F2.attach_history(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)\n    return out\n"),
        ("    if p.get('corrects'):\n        notes.append(f\"정정 공시입니다(원래 공시 {p['corrects']}). 이 공시의 본문 값을 썼습니다.\")\n",
         "    if p.get('corrects') and k not in F2.KINDS2:\n        notes.append(f\"정정 공시입니다(원래 공시 {p['corrects']}). 이 공시의 본문 값을 썼습니다.\")\n"),
        ("        notes.append('잠정실적은 회사가 감사 전에 알린 값입니다. 증권사 전망과의 비교는 다음 단계(v0.38 T2)에서 더합니다.')\n    return F, held, T, notes\n",
         "        notes.append('잠정실적은 회사가 감사 전에 알린 값입니다. 증권사 전망과의 비교는 다음 단계(v0.38 T2)에서 더합니다.')\n"
         "    elif k in F2.KINDS2:\n"
         "        F2.compute(k, f, mkt, fact, calc, held, T, notes, {'won': _won, 'p': _p, 'pct': _pct, 'check': stated_check})\n    return F, held, T, notes\n"),
    ]),
    'mrn/nodes.py': ("' 외 앞선 공시'", [
        ("(' 외 앞선 배당 결정' if len(f['docs']) > 1 else '')", "((' 외 앞선 배당 결정' if f['kind'] == 'dividend' else ' 외 앞선 공시') if len(f['docs']) > 1 else '')"),
        ("    elif f['kind'] != 'prelim':\n        held.append('가격 자료를 잇지 않아", "    elif f['kind'] not in ('prelim', 'pl_change'):\n        held.append('가격 자료를 잇지 않아"),
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
