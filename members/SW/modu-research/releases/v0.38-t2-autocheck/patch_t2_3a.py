"""v0.38 T2-3a 원문 받기 대상에 1등급 나머지 4종을 더한다(유상증자·감자·전환사채류·손익구조 변경). 계산은 T2-3b에서. 여러 번 돌려도 같은 결과.
자회사·종속회사 공시는 이 회사 숫자로 계산하지 않으므로 받지 않는다(제외 말)."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
p = N / 'mrn/dartdocs.py'; s = p.read_text(encoding='utf-8')
done = "'rights_issue'" in s
SUB = "('자회사의주요경영사항', '종속회사의주요경영사항')"
old1 = "    'prelim':           ('I', ('영업(잠정)실적',), ()),                                         # v0.38 T1 잠정실적(공정공시)\n}"
new1 = ("    'prelim':           ('I', ('영업(잠정)실적',), ()),                                         # v0.38 T1 잠정실적(공정공시)\n"
        f"    'rights_issue':     ('B', ('유상증자결정',), {SUB}),                                        # v0.38 T2-3 (무상증자는 계산이 달라 따로)\n"
        f"    'capital_reduction': ('B', ('감자결정',), {SUB}),\n"
        f"    'convertible':      ('B', ('전환사채권발행결정', '신주인수권부사채권발행결정', '교환사채권발행결정'), {SUB}),\n"
        f"    'pl_change':        ('I', ('매출액또는손익구조',), {SUB}),\n"
        "}")
old2 = "              'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적'}"
new2 = ("              'dividend': '현금·현물 배당 결정', 'prelim': '영업(잠정)실적',\n"
        "              'rights_issue': '유상증자 결정', 'capital_reduction': '감자 결정', 'convertible': '전환사채·신주인수권부사채·교환사채 발행 결정',\n"
        "              'pl_change': '매출액·손익구조 변경'}")
# 시험 자료: 「받지 않는 종류」의 본보기가 유상증자였음 → 이제 받는 종류이므로 본보기를 합병(2등급, 받지 않음)으로 바꾼다. 시험이 보는 것(받지 않는 종류는 건너뜀·거절)은 그대로.
t = N / 'tests/test_dartdocs.py'; ts = t.read_text(encoding='utf-8')
told = [("{'report_nm': '주요사항보고서(유상증자결정)', 'rcept_no': '20260601000009'", "{'report_nm': '주요사항보고서(회사합병결정)', 'rcept_no': '20260601000009'"),
        ("# 유상증자는 대상 아님", "# 합병은 대상 아님(v0.38 T2-3: 유상증자는 받는 종류가 됨)")]
tdone = '주요사항보고서(회사합병결정)' in ts
if not done:
    for o in (old1, old2):
        if s.count(o) != 1:
            raise SystemExit('mrn/dartdocs.py: 바꿀 자리를 정확히 하나 찾지 못함 — 아무것도 바꾸지 않음')
if not tdone:
    for o, _ in told:
        if ts.count(o) != 1:
            raise SystemExit('tests/test_dartdocs.py: 바꿀 자리를 정확히 하나 찾지 못함 — 아무것도 바꾸지 않음')
if done:
    print('mrn/dartdocs.py: 이미 적용됨')
else:
    p.write_text(s.replace(old1, new1).replace(old2, new2), encoding='utf-8', newline=''); print('mrn/dartdocs.py: 적용')
if tdone:
    print('tests/test_dartdocs.py: 이미 적용됨')
else:
    for o, n in told:
        ts = ts.replace(o, n)
    t.write_text(ts, encoding='utf-8', newline=''); print('tests/test_dartdocs.py: 적용')
