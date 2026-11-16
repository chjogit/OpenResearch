"""AI 길잡이를 「자유 질문」에 실제로 잇기 (PM 2026-11-15, Claude API 연결). 사용: python patch_demo_ai_guide.py <화면 폴더>
- 전에는 「켜기」가 켜짐 표시만 저장하고 아무 데서도 부르지 않았음(엔진 원래 화면 easy.js 의 guideOffer/guide 가 옮겨지지 않음)
- 이제: 길잡이가 켜져 있고 엔진이 available 이면, 자유 질문 결과 아래에
  · 규칙이 다 알아들은 경우 → 「원하던 내용이 아니면 AI 길잡이에게 바꿔 달라고 하기」 링크
  · 규칙이 못 알아들은 경우 → 「질문을 다 알아듣지 못했어요 [AI 길잡이에게 바꿔 달라고 하기]」
  · 누르면 /api/guide/translate(use_model) → AI가 바꾼 질문·가까운 카드·규칙 후보를 보여 줌. 실행은 사람이 누름. 숫자·판단 없음(엔진 검사)
- 이미 적용됐으면 건너뜀(표식 '시연: AI 길잡이 연결')"""
import sys
from pathlib import Path
ROOT = Path(sys.argv[1]).resolve()
MARK = "시연: AI 길잡이 연결"
REL = "pages/static/pages/js/pages/research.js"
FN = r'''/* 시연: AI 길잡이 연결 (PM 2026-11-15) — 엔진 원래 화면(easy.js)의 guideOffer/guide 를 옮김. 실행은 사람이 누름 */
const guideOn = () => !!(S.guideAvail && Store.get(KEY('guideOn'), false));
function guideOffer(q, understood) {
  if (!guideOn()) return;
  const out = $('#free-out'); if (!out) return;
  out.insertAdjacentHTML('beforeend', `<div id="free-guide" style="margin-top:12px">${understood
    ? '<p class="rs-note">원하던 내용이 아니면 <a href="#" id="g-go">AI 길잡이에게 바꿔 달라고 하기</a></p>'
    : '<div class="rs-box unk"><b>질문을 다 알아듣지 못했어요.</b> <button class="btn btn-v" type="button" id="g-go">AI 길잡이에게 바꿔 달라고 하기</button></div>'}</div>`);
  $('#g-go').onclick = (e) => { e.preventDefault(); guideAsk(q); };
}
async function guideAsk(q) {
  const box = $('#free-guide'); if (!box) return;
  box.innerHTML = '<div class="rs-empty">AI 길잡이가 질문을 살펴보는 중…</div>';
  let r; try { r = await api('/api/guide/translate', { method: 'POST', body: { question: q, company: S.company.ticker, use_model: true } }); }
  catch (e) { box.innerHTML = errBox(e); return; }
  const ai = r.mode === 'model' && r.ai_written;
  const sug = (r.suggestions || []).map((s) => `<button class="chip rs-ex" type="button" data-gcard="${esc(s.id)}">${esc(s.title)}</button>`).join(' ');
  box.innerHTML = `<div class="rs-box ${ai ? 'not' : 'unk'}">
    <h3>${ai ? `<span class="chip chip-ai">AI 작성 · ${esc(r.model || '')}</span> AI 길잡이 제안` : r.refused ? '판단은 드리지 않아요' : '가까운 질문 <span class="muted" style="font-size:13px">· 규칙으로 찾음 (AI 아님)</span>'}</h3>
    ${r.why ? `<p>${esc(r.why)}</p>` : ''}
    ${r.rewrite ? `<p>이렇게 물어볼까요? <b>「${esc(r.rewrite)}」</b> <button class="btn" type="button" id="g-use">이 질문으로 물어보기</button></p>` : ''}
    ${r.card ? `<p>가장 가까운 질문 카드: <button class="chip rs-ex" type="button" data-gcard="${esc(r.card.id)}">${esc(r.card.title)}</button></p>` : ''}
    ${sug ? `<p>${r.refused ? '판단 재료를 볼 수 있는 질문' : (r.card || r.rewrite) ? '규칙으로 찾은 다른 후보' : '이 질문들이 가까워요'}: ${sug}</p>` : ''}
    ${ai ? `<p class="muted" style="font-size:13px">AI 호출 ${esc(r.model_calls)}회 · 숫자·판단 없음 · 실행은 직접 누름</p>` : ''}
    ${(r.checks || []).length ? `<p class="muted" style="font-size:13px">안전 검사로 뺀 것: ${r.checks.map(esc).join(' / ')}</p>` : ''}</div>`;
  box.querySelectorAll('[data-gcard]').forEach((b) => { b.onclick = () => runCard(b.dataset.gcard); });
  if ($('#g-use')) $('#g-use').onclick = () => { $('#free-q').value = r.rewrite; freeAsk(); };
}

'''
EDITS = [
    ("  out.querySelectorAll('[data-pick]').forEach((b) => { b.onclick = () => freeAsk(b.dataset.pick); });\n",
     "  out.querySelectorAll('[data-pick]').forEach((b) => { b.onclick = () => freeAsk(b.dataset.pick); });\n"
     "  guideOffer(q, !!ok);   // 시연: AI 길잡이 연결\n"),
    ("  let g; try { g = await api('/api/guide/status'); } catch (e) { return; }\n",
     "  let g; try { g = await api('/api/guide/status'); } catch (e) { return; }\n"
     "  S.guideAvail = !!g.available;   // 시연: AI 길잡이 연결\n"),
    ("async function loadGuide() {", FN + "async function loadGuide() {"),
]
p = ROOT / REL; t = p.read_text(encoding="utf-8")
if MARK in t: print("이미 적용:", REL); sys.exit(0)
miss = [o[:50] for o, _ in EDITS if t.count(o) != 1]
if miss: sys.exit("바꿀 자리를 못 찾아 아무것도 바꾸지 않았습니다: " + " | ".join(miss))
for o, n in EDITS: t = t.replace(o, n)
p.write_text(t, encoding="utf-8", newline="\n"); print("고침:", REL); print("완료")
