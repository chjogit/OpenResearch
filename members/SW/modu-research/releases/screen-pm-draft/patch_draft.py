"""보고서 초안 · 근거 고정 화면 (PM 2026-11-15). 사용: python patch_draft.py <화면 폴더>
- research.js: 답 카드 「확인 · 비교」에 「보고서 초안 (근거 고정)」 · accounts/usage.py: /api/report/draft 도 AI 한도에 셈
- 되돌리기: before/research.js, before/usage.py · 표식 '보고서 초안 · 근거 고정'"""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent; ROOT = Path(sys.argv[1]).resolve()
MARK = "보고서 초안 · 근거 고정"
JS = ROOT / "pages/static/pages/js/pages/research.js"; US = ROOT / "accounts/usage.py"
BLOCK = (HERE / "new/draft_block.js").read_text(encoding="utf-8")
TOOL = ('    <div class="rs-tool"><p><b>보고서 초안 (근거 고정)</b> <span class="muted">문장마다 [E번호] 근거 · 근거 밖 숫자·판단 문장은 자동 제외</span></p>\n'
        '      <div class="rs-actions"><button class="btn btn-v" type="button" id="draft-go">초안 만들기</button><button class="btn" type="button" id="draft-copy" disabled>글로 복사</button></div>\n'
        '      <div id="draft-out"></div></div>\n')
EDITS = [
    (JS, "function route() {\n", BLOCK + "function route() {\n"),
    (JS, '    <div class="rs-tool"><p><b>그때 vs 지금</b>', TOOL + '    <div class="rs-tool"><p><b>그때 vs 지금</b>'),
    (JS, "  $('#dl-receipt').onclick = () => downloadReceipt(id);\n",
     "  $('#dl-receipt').onclick = () => downloadReceipt(id);\n  $('#draft-go').onclick = () => draftMake(id); $('#draft-copy').onclick = draftCopy;   // 보고서 초안 · 근거 고정\n"),
    (US, 'AI_PATHS = {"guide/translate", "agent/plan"}', 'AI_PATHS = {"guide/translate", "agent/plan", "report/draft"}   # 보고서 초안 · 근거 고정(PM 2026-11-15)도 셈'),
    (US, '    if sub == "guide/translate":\n        return bool(data.get("use_model"))', '    if sub in ("guide/translate", "report/draft"):\n        return bool(data.get("use_model"))'),
    (US, '    if sub == "guide/translate":\n        return (resp.get("model_calls") or 0) > 0', '    if sub in ("guide/translate", "report/draft"):\n        return (resp.get("model_calls") or 0) > 0'),
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
