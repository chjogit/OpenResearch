"""v0.38 T2-4f 손익구조 변경 ↔ 잠정실적 교차 대조(J25): 손익구조 변경 공시 카드에 「같은 결산기간·같은 재무제표 종류의 앞선 잠정실적」과 견준 줄과 표를 더한다.
- 짝 찾기: 같은 회사, 이 공시보다 먼저 접수(기준 날짜 안), 잠정실적의 누계(또는 당기) 기간 = 이 공시의 결산기간(시작~끝). 정정이 있으면 가장 늦은 것.
- 재무제표 종류: 잠정실적 제목에 「연결」이 있으면 연결, 없으면 별도. 종류가 다르면 견주지 않고 그 사실만 한 줄.
- 판정: 차이가 잠정실적 표 단위(예: 억원) 안이면 「같음(반올림)」, 넘으면 금액·비율로 「다름」. 방향 판단 없음.
- 짝이 된 잠정실적 원문은 확인서 사슬(docs)에 들어간다. 다른 종류의 카드는 그대로.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
ATTACH = '''

def _basis(t):
    t = (t or '').replace(' ', '')
    return '연결' if '연결' in t else '별도' if ('별도' in t or '개별' in t) else None


def attach_prelim(out, man, ticker, last, root, open_doc, own_exclude):
    """v0.38 T2-4f: 같은 회사·같은 결산기간(시작~끝)의 앞선 잠정실적(이 공시보다 먼저 접수, 기준 날짜 안). 정정이 있으면 가장 늦은 것.
    out['prelim'] = {rcept_no, rcept_dt, url, report_nm, basis, unit, rows{항목: 원}} 또는 None. 재무제표 종류가 달라 견주지 않은 것은 out['prelim_other']."""
    from .filing import parse as fl_parse
    out['prelim'] = out['prelim_other'] = None
    per = out['parsed'].get('period') or {}
    if not (per.get('start') and per.get('end') and per['start'][0] and per['end'][0]):
        return
    rng, mine = (per['start'][0], per['end'][0]), _basis(out['parsed'].get('basis'))
    for n, x in sorted(man['docs'].items()):
        if n >= out['rcept_no'] or x['ticker'] != ticker or x['kind'] != 'prelim' or x['rcept_dt'] > last or own_exclude.search(x.get('report_nm') or ''):
            continue
        files, _ = open_doc(n, root, man)
        try:
            p = fl_parse('prelim', '\\n'.join(t for _, t in files))
        except (ValueError, KeyError, TypeError):
            continue
        pp = p.get('period') or {}
        col = 'ytd' if tuple(pp.get('ytd') or ()) == rng else 'cur' if tuple(pp.get('cur') or ()) == rng else None
        if not col:
            continue
        b = '연결' if '연결' in (x.get('report_nm') or '').replace(' ', '') else '별도'
        row = {'rcept_no': n, 'rcept_dt': x['rcept_dt'], 'url': x['url'], 'report_nm': x['report_nm'], 'basis': b, 'unit': p.get('unit'),
               'rows': {k: (r or {}).get(col) for k, r in (p.get('rows') or {}).items()}}
        if mine and b != mine:
            out['prelim_other'] = row
        else:
            out['prelim'] = row
    if out['prelim']:
        out['docs'].append({'rcept_no': out['prelim']['rcept_no'], 'sha256': man['docs'][out['prelim']['rcept_no']]['sha256']})


def _vs_prelim(f, rows, calc, notes, T, H):
    """v0.38 T2-4f(J25): 같은 결산의 앞선 잠정실적과 이 공시의 값을 견준다. 잠정실적 표 단위 안의 차이는 반올림으로 본다. 방향 판단 없음."""
    from .filing import MONEY_UNIT
    pr, po = f.get('prelim'), f.get('prelim_other')
    if not pr:
        if po:
            notes.append(f"앞서 낸 잠정실적({po['rcept_dt']}, {po['basis']} 기준)은 이 공시와 재무제표 종류가 달라 견주지 않았습니다.")
        return
    um = MONEY_UNIT.get(pr.get('unit') or '', 1)
    R = []
    for key, name in PL_NAME.items():
        a, b = (rows.get(key) or {}).get('cur'), pr['rows'].get(key)
        if a is None:
            continue
        if b is None:
            R.append([name, '잠정실적에 없음', H['won'](a), '—', '—']); continue
        d = a - b
        if d == 0:
            v = '같음'
        elif abs(d) <= 2 * um:                                           # J3와 같은 기준: 표 단위 2칸 안은 반올림·끝수 처리 차이
            v = f"같음(잠정실적 표 단위 {pr['unit']} 반올림 안)"
        else:
            pc = d / abs(b) * 100 if b else None
            v = f"{H['won'](d)} 다름" + ('' if pc is None else f" ({pc:+.2f}%)" if abs(pc) >= 0.01 else ' (0.01% 미만)')
        calc(f"{name} — 앞서 낸 잠정실적과 대조", f"잠정 {H['won'](b)} → 이 공시 {H['won'](a)} · {v}",
             f"이 공시 값 − 잠정실적({pr['rcept_dt']}, 접수번호 {pr['rcept_no']}) 값", d, '원')
        R.append([name, H['won'](b), H['won'](a), H['won'](d), v])
    if R:
        T.append({'title': f"앞서 낸 잠정실적과 대조 — {pr['rcept_dt']} 「{pr['report_nm']}」", 'cols': ['구분', '잠정실적', '이 공시', '차이', '판정'], 'rows': R,
                  'hint': '같은 결산기간·같은 재무제표 종류의 앞선 잠정실적(공정공시)과 견준 값입니다. 잠정실적은 표 단위(예: 억원)로 반올림돼 있어 표 단위 2칸 안의 차이는 같다고 봅니다. 좋다·나쁘다를 뜻하지 않습니다.'})
'''
EDITS = {
    'mrn/filing.py': ("attach_prelim", [
        ("        F2.attach_history(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)\n",
         "        F2.attach_history(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)\n"
         "    if d['kind'] == 'pl_change':                              # v0.38 T2-4f 같은 결산의 앞선 잠정실적과 대조\n"
         "        F2.attach_prelim(out, man, ticker, last, root, D.open_doc, D.OWN_EXCLUDE)\n"),
    ]),
    'mrn/filing2.py': ("def attach_prelim", [
        ("\n\ndef _turn(cur, prev):\n", ATTACH + "\n\ndef _turn(cur, prev):\n"),
        ("                  'hint': '회사가 감사 전에 알린 결산 값입니다. 감사보고서 제출 뒤 달라질 수 있습니다.'})\n",
         "                  'hint': '회사가 감사 전에 알린 결산 값입니다. 감사보고서 제출 뒤 달라질 수 있습니다.'})\n"
         "    _vs_prelim(f, rows, calc, notes, T, H)                            # v0.38 T2-4f\n"),
        ("    notes.append('회사가 감사 전에 알린 결산 값입니다. 같은 기간 영업(잠정)실적 공시와의 대조는 다음 단계에서 더합니다.')\n",
         "    notes.append('회사가 감사 전에 알린 결산 값입니다. ' + ('같은 결산기간의 앞선 잠정실적과 견준 값을 함께 보입니다.' if f.get('prelim') else\n"
         "                 '같은 결산기간·같은 재무제표 종류의 앞선 잠정실적이 사본에 없어 견주지 않았습니다.'))      # v0.38 T2-4f\n"),
    ]),
}
todo = {}
for rel, (mark, pairs) in EDITS.items():
    if not (N / rel).exists() and rel == 'mrn/filing2.py':          # 통째로 더한 파일(T2-3) — 되짚기 때는 new/ 사본으로 대조한다
        print(f'{rel}: 없음 — 통째로 더한 파일이라 new/ 에서 가져옴'); continue
    s = (N / rel).read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); continue
    for old, _ in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:60]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
    todo[rel] = (s, pairs)
for rel, (s, pairs) in todo.items():
    for old, new in pairs:
        s = s.replace(old, new)
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
