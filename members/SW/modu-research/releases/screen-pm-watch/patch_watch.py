"""관심회사 공시함을 근거 리서치 화면으로 옮기기 (PM 2026-11-15). 엔진은 바꾸지 않음.
사용: python patch_watch.py <화면 폴더> · 되돌리기: before/research.js, before/research.html 을 제자리에 · 표식 '관심회사 공시함 (엔진 v0.38~v0.39'"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[1]).resolve()
MARK = "관심회사 공시함 (엔진 v0.38~v0.39"
JS = ROOT / "pages/static/pages/js/pages/research.js"
HTML = ROOT / "pages/templates/pages/research.html"
BLOCK = (HERE / "new/watch_block.js").read_text(encoding="utf-8")
EDITS = [
    (JS, "function route() {\n", BLOCK + "function route() {\n"),
    (JS, "  if (a === 'journal') return viewJournal();\n", "  if (a === 'watch') return viewWatch();   // 관심회사 공시함\n  if (a === 'journal') return viewJournal();\n"),
    (HTML, '        <a href="#/" data-tab="#/">질문하기</a>\n',
     '        <a href="#/" data-tab="#/">질문하기</a>\n        <a href="#/watch" data-tab="#/watch">관심회사 공시함</a>  {# 관심회사 공시함 (엔진 v0.38~v0.39 옮김, PM 2026-11-15) #}\n'),
]
texts, miss = {}, []
for p, old, new in EDITS:
    t = texts.get(p) or p.read_text(encoding="utf-8")
    if MARK in p.read_text(encoding="utf-8"):
        print("이미 적용:", p.name); continue
    if t.count(old) != 1: miss.append(f"{p.name}: {old[:40]!r}"); continue
    texts[p] = t.replace(old, new)
if miss: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다: " + " | ".join(miss))
for p, t in texts.items():
    p.write_text(t, encoding="utf-8", newline="\n"); print("고침:", p.name)
print("완료")
