"""v0.39 T3-2c(J32 뒤따름): 관심회사 공시함 안내 문장을 사실대로 — 원문까지 받는 것이 1등급만이 아니게 됨. 글자만 바꿈.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/autocheck.py': ("공급계약·타법인 주식)은 원문까지", [
        ("f\"앱이 계산하는 1등급 공시는 원문까지 받아 미리 계산해 둡니다(",
         "f\"앱이 계산하는 공시(1등급과, 2등급 중 공급계약·타법인 주식)은 원문까지 받아 미리 계산해 둡니다("),
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
