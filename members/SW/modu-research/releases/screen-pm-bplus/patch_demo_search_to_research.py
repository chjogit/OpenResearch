"""시연용: 「AI에게 질문」 숨기고 질문은 모두 근거 리서치로 (PM 결정 2026-11-15). 사용: python patch_demo_search_to_research.py <화면 폴더>
- 「AI에게 질문」은 아직 AI에 연결되지 않은 임시 화면(정해 둔 예시 질문에만 답) → 시연에서 숨김
- 위쪽 검색창·용어사전·학습의 「AI에게 물어보기」 링크 → 근거 리서치(엔진)로
- 근거 리서치가 ?q=글 을 받으면: 회사 이름·종목코드가 있으면 그 회사를 고르고, 남은 글은 「자유 질문」 해석까지(실행은 사람이 누름)
- 근거 리서치 안의 「전문가 모드 열기」(엔진 주소 새 창) → 화면 틀 안의 전문가 모드(B+)로
- 화면 파일·주소(/chat/)는 지우지 않음. 이미 적용됐으면 건너뜀(표식 '시연: AI에게 질문 숨김')"""
import sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
MARK = "시연: AI에게 질문 숨김"
JS = "pages/static/pages/js/"
TAKE = r'''/* 시연: AI에게 질문 숨김 (PM 2026-11-15) — 위쪽 검색창 등에서 ?q=글 로 들어오면 근거 리서치가 받는다.
   글 안에 회사 이름·종목코드가 있으면 그 회사를 고르고, 남은 글은 「자유 질문」으로 해석까지 진행(실행은 사람이 「이대로 조사」를 눌러야 함).
   회사 이름 일부만 있으면(예: 삼성) 회사 고르기 목록을 띄운다. */
async function takeTopQuery() {
  const raw = (param('q') || '').trim(); if (!raw) return;
  history.replaceState(null, '', location.pathname + location.hash);   // 새로고침해도 다시 묻지 않게
  let rest = raw;
  try {
    const u = await ensureUniverse();
    let hit = u.companies.filter((c) => raw.includes(c.name) || raw.includes(c.ticker)).sort((a, b) => b.name.length - a.name.length)[0];
    if (!hit) {
      const part = u.companies.filter((c) => c.name.includes(raw));
      if (part.length === 1) hit = part[0];
      else if (part.length > 1) { const q = $('#co-q'); q.value = raw; q.dispatchEvent(new Event('input')); q.focus(); return; }
    }
    if (hit) {
      S.company = { ticker: hit.ticker, name: hit.name }; Store.set(KEY('company'), S.company);
      rest = raw.replace(hit.name, '').replace(hit.ticker, '').trim();
    }
  } catch (e) { /* 회사 목록을 못 받아도 자유 질문으로 진행 */ }
  if (rest && $('#free-q')) { $('#free-q').value = rest; freeAsk(); setTimeout(() => $('#free')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 300); }
}
'''
EDITS = [
    (JS + "common/core.js",
     "const homeUrl = () => getLevel() === 'expert' ? URLS.research : URLS[`home_${getLevel()}`];\n",
     "const homeUrl = () => getLevel() === 'expert' ? URLS.research : URLS[`home_${getLevel()}`];\n"
     "// 시연: AI에게 질문 숨김 (PM 2026-11-15) — 아직 AI에 연결되지 않은 임시 화면이라, 질문은 모두 근거 리서치(엔진)로 보낸다\n"
     "URLS.chat = URLS.research;\n"),
    (JS + "common/layout.js",
     "].filter((m) => !(m.key === 'home' && getLevel() === 'expert'));  // 시연: 숙련자 홈 숨김 (PM 2026-11-13)\n",
     "].filter((m) => !(m.key === 'home' && getLevel() === 'expert') && m.key !== 'chat');  // 시연: 숙련자 홈 숨김 (PM 2026-11-13) · 시연: AI에게 질문 숨김 (PM 2026-11-15)\n"),
    (JS + "common/layout.js",
     '<input name="q" placeholder="궁금한 종목·용어를 AI에게 질문" aria-label="AI에게 질문하기">',
     '<input name="q" placeholder="회사 이름이나 궁금한 것을 근거로 찾기" aria-label="근거 리서치에서 찾기">'),
    (JS + "pages/research.js",
     "  bindPicker(); renderPicked(); loadCards(); renderFree(); loadGuide();\n",
     "  bindPicker(); renderFree(); loadGuide();\n"
     "  takeTopQuery().finally(() => { renderPicked(); loadCards(); });   // 시연: AI에게 질문 숨김 — 위쪽 검색창 글을 먼저 받고 회사 카드 그리기\n"),
    (JS + "pages/research.js",
     "/* 직접 물어보기 (A7)",
     TAKE + "/* 직접 물어보기 (A7)"),
    (JS + "pages/research.js",
     '${esc(eng)}/expert" target="_blank" rel="noopener" aria-label="전문가 모드 열기 (새 창)"',
     '${URLS.expert_mode}" aria-label="전문가 모드 열기"'),
]
texts, missing = {}, []
for rel, old, new in EDITS:
    t = texts.get(rel) or (ROOT / rel).read_text(encoding="utf-8")
    if MARK in (ROOT / rel).read_text(encoding="utf-8"): print("이미 적용:", rel, "(한 곳)"); continue
    if t.count(old) != 1: missing.append(f"{rel}: {old[:40]}"); continue
    texts[rel] = t.replace(old, new)
if missing: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다:\n  " + "\n  ".join(missing))
for rel, t in texts.items():
    (ROOT / rel).write_text(t, encoding="utf-8", newline="\n"); print("고침:", rel)
print("완료")
