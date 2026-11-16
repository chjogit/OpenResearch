"""v0.38 T2-3 화면 확인 반영: 「자세한 표」의 숫자 칸(16자 이하, 숫자가 든 칸)은 줄을 바꾸지 않는다(「1,040,200 / 원」처럼 끊기지 않게). 표가 넓으면 기존 .tw 상자가 가로로 밀림.
긴 글 칸은 그대로 줄바꿈. 고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'web/easy.js': ('class="${numCell(v)}"', [
        ("${t.rows.map(r => `<tr>${r.map(v => `<td>${cell(v)}</td>`).join('')}</tr>`).join('')}",
         "${t.rows.map(r => `<tr>${r.map(v => `<td class=\"${numCell(v)}\">${cell(v)}</td>`).join('')}</tr>`).join('')}"),
    ]),
    'web/easy.css': ('.tw td.n{', [
        (".tw{max-height:360px;overflow:auto}", ".tw{max-height:360px;overflow:auto}\n.tw td.n{white-space:nowrap}   /* v0.38 T2-3: 숫자 칸은 한 줄로 */"),
    ]),
}
EXTRA_JS = "\nfunction numCell(v){ const s = String(v ?? ''); return s.length <= 16 && /\\d/.test(s) ? 'n' : ''; }   // v0.38 T2-3: 숫자 칸 표시\n"
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
    if rel == 'web/easy.js':
        s = s.rstrip('\n') + '\n' + EXTRA_JS
    (N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(pairs)}곳 적용')
