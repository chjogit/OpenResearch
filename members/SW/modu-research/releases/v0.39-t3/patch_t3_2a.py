"""v0.39 T3-2a(J31): 원문 받는 종류에 2등급 4종을 더한다 — 단일판매·공급계약 체결 / 해지, 타법인 주식 취득·처분(거래소 공시) / 양수·양도(주요사항보고서).
더하기만(기존 종류·순서·문구는 그대로). 고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EX = "('자회사의주요경영사항', '종속회사의주요경영사항')"
EDITS = {
    'mrn/dartdocs.py': ("'supply_contract'", [
        ("    'cv_adjust':        ('I', ('전환가액의조정', '행사가액의조정', '교환가액의조정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),   # v0.38 T2-4b 리픽싱 대조용(계산하지 않음)\n}\n",
         "    'cv_adjust':        ('I', ('전환가액의조정', '행사가액의조정', '교환가액의조정'), ('자회사의주요경영사항', '종속회사의주요경영사항')),   # v0.38 T2-4b 리픽싱 대조용(계산하지 않음)\n"
         f"    'supply_contract':  ('I', ('단일판매ㆍ공급계약체결', '단일판매·공급계약체결'), {EX}),        # v0.39 T3-2(J31) 2등급 — 공시 숫자로만 계산\n"
         f"    'supply_cancel':    ('I', ('단일판매ㆍ공급계약해지', '단일판매·공급계약해지'), {EX}),\n"
         f"    'equity_deal':      ('I', ('타법인주식및출자증권취득결정', '타법인주식및출자증권처분결정'), {EX}),\n"
         f"    'equity_deal_major': ('B', ('타법인주식및출자증권양수결정', '타법인주식및출자증권양도결정'), {EX}),\n"
         "}\n"),
        ("              'pl_change': '매출액·손익구조 변경', 'cv_adjust': '전환가액·행사가액·교환가액의 조정'}\n",
         "              'pl_change': '매출액·손익구조 변경', 'cv_adjust': '전환가액·행사가액·교환가액의 조정',\n"
         "              'supply_contract': '단일판매·공급계약 체결', 'supply_cancel': '단일판매·공급계약 해지',                   # v0.39 T3-2\n"
         "              'equity_deal': '타법인 주식 취득·처분 결정', 'equity_deal_major': '타법인 주식 양수·양도 결정(주요사항보고서)'}\n"),
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
