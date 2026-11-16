"""v0.38 T2-4b 리픽싱 대조용: 「전환가액의 조정」(신주인수권 행사가액·교환가액 조정 포함) 공시를 받는 종류(cv_adjust)로 등록하고,
엔진 시세 사본에 있는 회사만 골라 시험용 표본 폴더로 받는 명령(python -m mrn.dartsamples fetch-snapshot)을 더한다. 계산하는 종류는 아님(받아서 대조만).
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/dartdocs.py': ("'cv_adjust'", [
        ("    'pl_change':        ('I', ('매출액또는손익구조',), ('자회사의주요경영사항', '종속회사의주요경영사항')),\n}\n",
         "    'pl_change':        ('I', ('매출액또는손익구조',), ('자회사의주요경영사항', '종속회사의주요경영사항')),\n"
         "    'cv_adjust':        ('I', ('전환가액의조정', '행사가액의조정', '교환가액의조정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),   # v0.38 T2-4b 리픽싱 대조용(계산하지 않음)\n}\n"),
        ("              'pl_change': '매출액·손익구조 변경'}\n", "              'pl_change': '매출액·손익구조 변경', 'cv_adjust': '전환가액·행사가액·교환가액의 조정'}\n"),
    ]),
    'mrn/dartsamples.py': ("fetch-snapshot", [
        ("    sub.add_parser('status'); sub.add_parser('verify')\n    a = ap.parse_args(argv)\n",
         "    g = sub.add_parser('fetch-snapshot', help='엔진 시세 사본에 있는 회사만, 회사마다 목록을 훑어 받는다(기간 제한 없음)')\n"
         "    g.add_argument('--kinds', required=True); g.add_argument('--from', dest='start', required=True); g.add_argument('--to', dest='end', default=None)\n"
         "    g.add_argument('--limit', type=int, default=None)\n"
         "    sub.add_parser('status'); sub.add_parser('verify')\n    a = ap.parse_args(argv)\n"),
        ("        if a.cmd in ('fetch', 'status'):\n",
         "        if a.cmd == 'fetch-snapshot':                                   # v0.38 T2-4b\n"
         "            kinds = [k.strip() for k in a.kinds.split(',') if k.strip()]\n"
         "            for k in kinds:\n"
         "                if k not in D.KINDS:\n"
         "                    raise D.DartDocsError('bad_kind', f'{k}: 받는 종류 이름이 아닙니다({\", \".join(D.KINDS)}).')\n"
         "            cos = D._companies()\n"
         "            print(f'시험용 표본 받기: 종류 {kinds}, {a.start} ~ {a.end or \"오늘\"} (엔진 시세 사본의 국내 회사 {len(cos)}곳, 회사마다 목록을 훑음)')\n"
         "            print(f'새로 받은 원문 {D.fetch(cos, kinds, a.start, a.end, out_root=samples_dir(), limit=a.limit, get=D.metered_get())}건.')\n"
         "        if a.cmd in ('fetch', 'fetch-snapshot', 'status'):\n"),
        ("        if a.cmd in ('fetch', 'verify'):\n", "        if a.cmd in ('fetch', 'fetch-snapshot', 'verify'):\n"),
    ]),
}
todo = {}
for rel, (mark, pairs) in EDITS.items():
    if not (N / rel).exists() and rel == 'mrn/dartsamples.py':           # 통째로 더한 파일(T2-3) — 되짚기 때는 new/ 사본으로 대조한다
        print(f'{rel}: 없음 — 통째로 더한 파일이라 new/ 에서 가져옴'); continue
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
