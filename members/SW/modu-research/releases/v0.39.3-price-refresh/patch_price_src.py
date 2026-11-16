"""v0.39.3 엔진: 가격 사본에 KIS로 보충한 날(kis 행)도 계산에 씀(연구용 스위치 MODU_PRICE_KIS, 기본 켬). 출처 표시에 「KIS n일 보충」을 붙임.
쓰는 법: python patch_price_src.py <modu-research-nodes 경로>. 고칠 곳을 모두 먼저 확인, 못 찾으면 아무것도 안 바꿈, 두 번 돌려도 같음."""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; N = Path(sys.argv[1]); MARK = 'v0.39.3'
IMP = 'from . import price_src as _PS   # v0.39.3 가격 출처(금융위 + KIS 보충, 연구용 스위치)\n'
EDITS = {
    'mrn/market.py': [
        ('from pathlib import Path\n', 'from pathlib import Path\n\n' + IMP, 1),
        ("    mine = sorted((r for r in rows if r['trade_date'] <= last and r.get('source') == 'fsc'), key=lambda r: r['trade_date'])\n",
         "    mine = _PS.pick(r for r in rows if r['trade_date'] <= last)   # v0.39.3: 금융위 + KIS 보충, 같은 날은 금융위 우선\n", 1),
        ("    collected = max((r['collected_at'] for r in mine), default=None)\n    return {\n        'company': company, 'name': names.get(company, company), 'cutoff': cutoff, 'last_usable_date': last,\n",
         "    collected = max((r['collected_at'] for r in mine), default=None)\n    nk = _PS.kis_count(mine)   # v0.39.3\n    return {\n        'company': company, 'name': names.get(company, company), 'cutoff': cutoff, 'last_usable_date': last,\n", 1),
        ("                   'origin': '금융위원회 주식시세정보(fsc) — Neon 공용 DB 경유', 'collected_at_max': collected},\n",
         "                   'origin': '금융위원회 주식시세정보(fsc) — Neon 공용 DB 경유' + (f' + 한국투자증권 일별 시세(kis) {nk}거래일 보충(연구용·재배포 계약 전)' if nk else ''),\n"
         "                   'collected_at_max': collected, 'kis_rows': nk},\n", 1),
    ],
    'mrn/edi_market.py': [
        ('from . import edi as E\n', 'from . import edi as E\n' + IMP, 1),
        ("x.get('source') == 'fsc'", "_PS.ok(x.get('source'))", 1),
    ],
    'mrn/reaction.py': [
        ('from .market import (SnapshotError, _src, companies, index_series, last_usable_date, load_manifest, read_rows, resolve)\n',
         'from .market import (SnapshotError, _src, companies, index_series, last_usable_date, load_manifest, read_rows, resolve)\n' + IMP, 1),
        ("r.get('source') == 'fsc'", "_PS.ok(r.get('source'))", 2),
    ],
    'mrn/prob.py': [
        ('"""\nimport math\n', '"""\nimport math\n\n' + IMP, 1),
        ("r.get('source') == 'fsc'", "_PS.ok(r.get('source'))", 1),
    ],
}
todo, miss = [], []
for f, eds in EDITS.items():
    s = (N / f).read_text(encoding='utf-8')
    if 'price_src as _PS' in s:
        print(f'{f}: 이미 적용됨'); continue
    for old, new, want in eds:
        if s.count(old) != want:
            miss.append(f'{f}: {old[:50]!r} ({s.count(old)}/{want})'); continue
        s = s.replace(old, new)
    todo.append((f, s))
if miss:
    raise SystemExit('고칠 자리를 못 찾아 아무것도 바꾸지 않음:\n  ' + '\n  '.join(miss))
for f, s in todo:
    (N / f).write_text(s, encoding='utf-8', newline='\n'); print(f'{f}: 고침')
for f in ['mrn/price_src.py', 'tests/test_v0393_price_src.py']:
    if (HERE / 'new' / f).exists():
        shutil.copyfile(HERE / 'new' / f, N / f); print('새 파일:', f)
