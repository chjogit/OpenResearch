"""v0.38 T2-3 마무리: 관심회사 공시함 안내 문구와 「아직 계산하는 종류가 아님」 오류 문장에 새로 더한 공시 종류(손익구조 변경·감자·유상증자·전환사채류)를 넣는다.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'web/easy.html': ('유상증자 · 감자 · 전환사채', [
        ('title="관심 있는 회사를 담아 두고, 그 회사의 소각·자기주식·배당·잠정실적 공시를 숫자로 봐요"',
         'title="관심 있는 회사를 담아 두고, 그 회사의 주요 공시(소각·자기주식·배당·실적·유상증자·감자·전환사채 등)를 숫자로 봐요"'),
        ('그 회사의 <b>주식 소각 · 자기주식 취득 · 배당 · 잠정실적</b> 공시를 원문 숫자와 식으로 봐요.',
         '그 회사의 <b>주식 소각 · 자기주식 취득 · 배당 · 잠정실적 · 손익구조 변경 · 유상증자 · 감자 · 전환사채(신주인수권부·교환사채 포함)</b> 공시를 원문 숫자와 식으로 봐요. '
         '유상증자·전환사채는 주가가 달라지면 값이 어떻게 바뀌는지 시나리오 표와 「추정」 확률도 함께 보여요.'),
    ]),
    'mrn/dartdocs.py': ('유상증자·감자·전환사채', [
        ("(지금은 소각·자기주식·배당·잠정실적 등)", "(지금은 소각·자기주식·배당·잠정실적·손익구조 변경·유상증자·감자·전환사채류 등)"),
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
