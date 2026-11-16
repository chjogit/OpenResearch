"""여러 회사 한꺼번에 + 엑셀 (PM 2026-11-15). 사용: python patch_batch.py <화면 폴더>
- research.js: 「여러 회사 한꺼번에」 탭(#/batch) · research.html: 탭 링크 · pages/urls.py: /export/xlsx/ · 새 파일 pages/xlsx_export.py
- 되돌리기: before/ 세 파일을 제자리에, pages/xlsx_export.py 지우기 · 표식 '여러 회사 한꺼번에 + 엑셀'"""
import shutil, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = Path(sys.argv[1]).resolve()
MARK = "여러 회사 한꺼번에 + 엑셀"
JS = ROOT / "pages/static/pages/js/pages/research.js"; HTML = ROOT / "pages/templates/pages/research.html"; URLS = ROOT / "pages/urls.py"
BLOCK = (HERE / "new/batch_block.js").read_text(encoding="utf-8")
EDITS = [
    (JS, "function route() {\n", BLOCK + "function route() {\n"),
    (JS, "  if (a === 'watch') return viewWatch();   // 관심회사 공시함\n", "  if (a === 'watch') return viewWatch();   // 관심회사 공시함\n  if (a === 'batch') return viewBatch();   // 여러 회사 한꺼번에 + 엑셀\n"),
    (HTML, '        <a href="#/consensus" data-tab="#/consensus">컨센서스(연구용)</a>',
     '        <a href="#/batch" data-tab="#/batch">여러 회사 한꺼번에</a>  {# 여러 회사 한꺼번에 + 엑셀 (PM 2026-11-15) #}\n        <a href="#/consensus" data-tab="#/consensus">컨센서스(연구용)</a>'),
    (URLS, "from . import views\n", "from . import views\nfrom .xlsx_export import export_xlsx   # 여러 회사 한꺼번에 + 엑셀 (PM 2026-11-15)\n"),
    (URLS, '    path("research/", views.research, name="research"),',
     '    path("export/xlsx/", export_xlsx, name="export_xlsx"),   # 여러 회사 한꺼번에 + 엑셀: 화면 표 → .xlsx\n    path("research/", views.research, name="research"),'),
]
texts, miss = {}, []
for p, old, new in EDITS:
    t = texts.get(p) or p.read_text(encoding="utf-8")
    if MARK in p.read_text(encoding="utf-8"):
        print("이미 적용:", p.name); continue
    if t.count(old) != 1: miss.append(f"{p.name}: {old[:50]!r} ({t.count(old)})"); continue
    texts[p] = t.replace(old, new)
if miss: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다:\n  " + "\n  ".join(miss))
for p, t in texts.items():
    p.write_text(t, encoding="utf-8", newline="\n"); print("고침:", p.name)
for f in ("pages/xlsx_export.py", "pages/test_xlsx_export.py"):
    shutil.copyfile(HERE / "new" / f, ROOT / f); print("새 파일:", f)
print("완료")
