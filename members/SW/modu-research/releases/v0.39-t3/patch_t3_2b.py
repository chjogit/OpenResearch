"""v0.39 T3-2b(J31·J32): 새 파일 mrn/filing4.py(공급계약·타법인 주식)를 공시 계산 틀에 잇는다. 더하기만.
- filing2: 종류별 정정 묶음 함수 ATTACH(없으면 지금 그대로) + 끝에서 filing4 등록.
- autocheck(J32): 원문 자동 받기의 등급 조건을 「1등급만」에서 「계산하는 종류이면서 3등급(숫자 없는 공시)이 아닌 것」으로.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/filing2.py': ("ATTACH = {}", [
        ("EXTRA = {}                                                    # 다른 파일(filing3 등)이 등록하는 종류 → 계산 함수\n",
         "EXTRA = {}                                                    # 다른 파일(filing3 등)이 등록하는 종류 → 계산 함수\n"
         "ATTACH = {}                                                   # v0.39 T3-2: 종류별 정정 묶음 함수(없으면 아래 attach_history 그대로)\n"),
        ("    kind, no = out['kind'], out['rcept_no']\n    keyf = _fy if kind == 'pl_change' else _decision_key\n",
         "    kind, no = out['kind'], out['rcept_no']\n"
         "    if kind in ATTACH:                                        # v0.39 T3-2 공급계약·타법인: 계약상대 + 정정의 정정까지 잇는 묶음\n"
         "        return ATTACH[kind](out, man, ticker, last, root, open_doc, own_exclude)\n"
         "    keyf = _fy if kind == 'pl_change' else _decision_key\n"),
        ("from . import filing3  # noqa: E402,F401  — 유상증자 등 나머지 종류를 등록한다(이 파일의 함수가 모두 정의된 뒤에 불러야 함)\n",
         "from . import filing3  # noqa: E402,F401  — 유상증자 등 나머지 종류를 등록한다(이 파일의 함수가 모두 정의된 뒤에 불러야 함)\n"
         "from . import filing4  # noqa: E402,F401  — v0.39 T3-2 공급계약·타법인 주식(2등급)을 등록한다\n"),
    ]),
    'mrn/autocheck.py': ("['grade'] == 3:", [
        ("        if D.OWN_EXCLUDE.search(r['report_nm'] or '') or G.classify(r['report_nm'])['grade'] != 1:\n"
         "            _mark(store, r['rcept_no'], doc_state='skipped', doc_note='자회사 공시이거나 1등급이 아니라 받지 않음'); continue\n",
         "        if D.OWN_EXCLUDE.search(r['report_nm'] or '') or G.classify(r['report_nm'])['grade'] == 3:      # v0.39 T3-2(J32) 2등급 중 계산하는 종류도 받음\n"
         "            _mark(store, r['rcept_no'], doc_state='skipped', doc_note='자회사 공시이거나 숫자 없는 공시라 받지 않음'); continue\n"),
    ]),
}
todo = {}
for rel, (mark, pairs) in EDITS.items():
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
    (N / rel).write_text(s, encoding='utf-8', newline='\n')
    print(f'{rel}: 고침')
