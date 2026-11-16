"""v0.38 곁가지(이름 바꿈 화면 점검 중 발견): 화면 폭 760~1100px에서 맨 위 띠의 안내 글(「지금은 쉬운 화면 — 계산은 두 화면이 똑같아요」)이
줄바꿈 없이 오른쪽으로 넘쳐 가로 스크롤이 생김(이름 바꾸기 전부터 있던 문제). 1100px 이하에서는 이 안내 글을 감춤(760px 이하는 원래 감춤).
쉬운 화면(easy.css)·전문가 모드(app.css) 둘 다. 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
RULE = '@media (max-width:1100px){.modebar .mb-note{display:none}}   /* v0.38 중간 폭 가로 넘침 막기 */'
for rel in ('web/app.css', 'web/easy.css'):
    p = N / rel; s = p.read_text(encoding='utf-8')
    if 'v0.38 중간 폭 가로 넘침 막기' in s:
        print(f'{rel}: 이미 적용됨'); continue
    lines = s.split('\n')
    idx = [i for i, l in enumerate(lines) if l.startswith('@media (max-width:760px){.modebar .mb-note')]
    if len(idx) != 1:
        raise SystemExit(f'{rel}: 바꿀 자리를 정확히 하나 찾지 못함({len(idx)})')
    lines.insert(idx[0] + 1, RULE)
    p.write_text('\n'.join(lines), encoding='utf-8', newline=''); print(f'{rel}: 적용')
