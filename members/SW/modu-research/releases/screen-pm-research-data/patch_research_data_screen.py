"""연구용 데이터 화면 (PM 2026-11-15): 고른 회사·관심회사 옆 KIS 현재가(엔진 스위치가 켜졌을 때만) + 「컨센서스(연구용)」 탭.
사용: python patch_research_data_screen.py <화면 폴더> · 되돌리기: before/ 두 파일 · 표식 '연구용 데이터: KIS 현재가 · 컨센서스'"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = Path(sys.argv[1]).resolve()
MARK = "연구용 데이터: KIS 현재가 · 컨센서스"
JS = ROOT / "pages/static/pages/js/pages/research.js"; HTML = ROOT / "pages/templates/pages/research.html"
BLOCK = (HERE / "new/rd_block.js").read_text(encoding="utf-8")
EDITS = [
    (JS, "function route() {\n", BLOCK + "function route() {\n"),
    (JS, "  if (a === 'watch') return viewWatch();   // 관심회사 공시함\n",
     "  if (a === 'watch') return viewWatch();   // 관심회사 공시함\n  if (a === 'consensus') return viewConsensus();   // 연구용 데이터: 컨센서스\n"),
    (JS, "<span class=\"chip\">살펴본 질문 ${n}개</span>`;\n}\n",
     "<span class=\"chip\">살펴본 질문 ${n}개</span>`;\n  showQuote(S.company.ticker, $('#co-picked'));   // 연구용 데이터: KIS 현재가(스위치)\n}\n"),
    (JS, "        <div style=\"display:flex;gap:8px;align-items:center;flex-wrap:wrap\"><b>${esc(r.name)}</b> <span class=\"muted rs-date\">${esc(r.ticker)}</span>\n",
     "        <div style=\"display:flex;gap:8px;align-items:center;flex-wrap:wrap\" data-qt=\"${esc(r.ticker)}\"><b>${esc(r.name)}</b> <span class=\"muted rs-date\">${esc(r.ticker)}</span>\n"),
    (JS, "  $('#wList').querySelectorAll('[data-x]').forEach((b) => { b.onclick = async () => {\n",
     "  $('#wList').querySelectorAll('[data-qt]').forEach((el, i) => { if (i < 20) showQuote(el.dataset.qt, el); });   // 연구용 데이터: KIS 현재가(앞 20곳)\n"
     "  $('#wList').querySelectorAll('[data-x]').forEach((b) => { b.onclick = async () => {\n"),
    (HTML, '        <a href="#/watch" data-tab="#/watch">관심회사 공시함</a>',
     '        <a href="#/watch" data-tab="#/watch">관심회사 공시함</a>\n        <a href="#/consensus" data-tab="#/consensus">컨센서스(연구용)</a>  {# 연구용 데이터: KIS 현재가 · 컨센서스 (PM 2026-11-15) #}\n       '),
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
print("완료")
