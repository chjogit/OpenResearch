"""v0.38 T2-4d 화면 확인에서 고친 것: 출처근거의 지문 줄에서 사본 이름이 없는 자료(공시 원문)는 앞에 「 · 」만 남던 것 → 사본 이름이 있을 때만 붙인다.
고칠 곳을 먼저 확인하고, 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1]); rel = 'web/easy.js'
OLD = """<span class="mono">${esc(s.snapshot || '')} · ${esc((s.sha256 || '').slice(0, 16))}…</span>"""
NEW = """<span class="mono">${s.snapshot ? esc(s.snapshot) + ' · ' : ''}${esc((s.sha256 || '').slice(0, 16))}…</span>"""
s = (N / rel).read_text(encoding='utf-8')
if NEW in s:
    print(f'{rel}: 이미 적용됨'); sys.exit(0)
if s.count(OLD) != 1:
    raise SystemExit(f'{rel}: 고칠 자리를 정확히 하나 찾지 못함({s.count(OLD)}) — 아무것도 바꾸지 않음')
(N / rel).write_text(s.replace(OLD, NEW), encoding='utf-8', newline=''); print(f'{rel}: 1곳 적용')
