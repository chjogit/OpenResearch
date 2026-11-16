/* ---------- 보고서 초안 · 근거 고정 (엔진 v0.39.4, PM 2026-11-15) ----------
   답 카드의 줄들만 재료로, 문장마다 [E번호] 근거를 단 초안. 근거에 없는 숫자·판단 표현 문장은 엔진이 빼고 이유를 알려 준다.
   AI 길잡이가 켜져 있으면 AI 초안(하루 한도에 셈), 꺼져 있으면 규칙 초안(AI 호출 0회). 저장하지 않음 — 복사해서 씀. */
let DR = null;
async function draftMake(id) {
  const box = $('#draft-out'); const useAi = guideOn();
  box.innerHTML = `<div class="rs-empty">${useAi ? 'AI가 근거 줄만 보고 초안을 쓰는 중…(10~30초)' : '규칙으로 초안을 만드는 중…'}</div>`;
  $('#draft-go').disabled = true;
  try { DR = await api('/api/report/draft', { method: 'POST', body: { run_id: id, use_model: useAi } }); }
  catch (e) { box.innerHTML = errBox(e); $('#draft-go').disabled = false; return; }
  $('#draft-go').disabled = false; $('#draft-copy').disabled = false;
  const ev = Object.fromEntries((DR.evidence || []).map((e) => [e.id, e]));
  const cite = (t) => esc(t).replace(/\[E(\d+)\]/g, (m, n) => (ev[n] ? `<sup><span class="chip" title="${esc(`E${n} · ${ev[n].kind} — ${ev[n].text}${ev[n].source ? ` (${ev[n].source})` : ''}`)}">E${n}</span></sup>` : m));
  const ai = DR.mode === 'model';
  box.innerHTML = `<div class="rs-box ${ai ? 'not' : 'unk'}" style="margin-top:10px">
      <p>${ai ? `<span class="chip chip-ai">AI 작성 · ${esc(DR.model || '')}</span>` : '<span class="chip">규칙 초안 · AI 호출 0회</span>'} ${DR.why ? `<span class="muted">${esc(DR.why)}</span>` : ''}${!useAi ? ' <span class="muted">AI 초안은 아래 「AI 길잡이」를 켜면 써요.</span>' : ''}</p>
      ${(DR.sentences || []).map((s) => (s.heading ? `<h3 style="font-size:15px;margin-top:8px">${esc(s.text.replace(/^#+\s*/, ''))}</h3>` : `<p>${cite(s.text)}</p>`)).join('')}
    </div>
    ${(DR.dropped || []).length ? `<details class="rs-fold"><summary>검사에서 뺀 문장 ${DR.dropped.length}개</summary><div><ul style="padding-left:20px">${DR.dropped.map((d) => `<li><span class="muted">${esc(d.why)}</span> — ${esc(d.text)}</li>`).join('')}</ul></div></details>` : ''}
    <details class="rs-fold"><summary>근거 줄 ${(DR.evidence || []).length}개</summary><div><ol style="padding-left:24px;font-size:13px">${(DR.evidence || []).map((e) => `<li value="${e.id}"><span class="muted">${esc(e.kind)}</span> ${esc(e.text)}${e.source ? ` <span class="muted">(${esc(e.source)})</span>` : ''}</li>`).join('')}</ol></div></details>
    <p class="muted" style="font-size:12px">ⓘ ${esc(DR.notice || '')}</p>`;
  if (DR.ai_usage && $('#ai-left')) $('#ai-left').textContent = aiLeftText(DR.ai_usage);
}
function draftCopy() {
  if (!DR) return;
  const text = `${DR.draft_md}\n\n[근거]\n${(DR.evidence || []).map((e) => `[E${e.id}] ${e.text}${e.source ? ` (${e.source})` : ''}`).join('\n')}\n\n${DR.notice}`;
  navigator.clipboard.writeText(text).then(() => toast('초안과 근거를 글로 복사했어요.'), () => toast('복사하지 못했어요.'));
}

