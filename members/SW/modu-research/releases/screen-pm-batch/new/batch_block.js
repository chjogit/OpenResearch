/* ---------- 여러 회사 한꺼번에 + 엑셀 (PM 2026-11-15) ----------
   같은 질문 카드를 여러 회사에 차례로 실행(엔진은 한 번에 하나 — 바쁘면 기다렸다 다시) → 핵심 숫자 비교표 → 엑셀(.xlsx).
   엑셀: 「비교표」(회사×핵심 숫자) · 「모든 숫자와 출처」(값 종류·계산 단계·원문 제목·주소·실행 번호) · 「안내」.
   엔진이 준 글자·값을 그대로 옮기고 새로 계산하지 않는다. 판단(사라·팔아라) 없음. */
const BT = { running: false, stop: false, results: [] };
const BT_CARDS = ['earnings', 'events', 'holders', 'price', 'macro', 'relations', 'forecasts', 'edi', 'nowcast'];
const btSleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const btLabel = (it, name) => String(it.label || '').replace(name || '', '').trim() || String(it.label || '');
async function viewBatch() {
  crumbs(-1); tab('#/batch');
  let wl = []; try { wl = (await api('/api/watch')).rows || []; } catch (e) { /* 관심회사가 없어도 됨 */ }
  view().innerHTML = `<section class="rs-head"><h2>여러 회사 한꺼번에</h2><p>같은 질문 카드를 여러 회사에 차례로 → 핵심 숫자 비교표 → 엑셀 · 기준 ${esc(fmtCut(cutoff()))}</p></section>
    <section class="card" style="display:flex;flex-direction:column;gap:12px">
      <div class="rs-actions"><label class="rs-label" for="bt-card" style="margin:0">질문 카드</label>
        <select class="rs-input" style="width:auto" id="bt-card">${BT_CARDS.map((c) => `<option value="${c}">${esc(CARD[c] || c)}</option>`).join('')}</select></div>
      <div><label class="rs-label" for="bt-cos">회사 (종목코드 또는 이름, 쉼표·줄바꿈으로 · 최대 30곳)</label>
        <textarea class="rs-input" id="bt-cos" rows="3" style="width:100%" placeholder="예: 005930, 000660, 현대차">${esc(wl.map((r) => r.ticker).join(', ') || S.company.ticker)}</textarea>
        <p class="muted" style="font-size:13px">${wl.length ? `관심회사 ${wl.length}곳을 넣어 두었어요.` : '관심회사가 없어 지금 고른 회사만 넣어 두었어요.'} 기준 날짜는 「질문하기」에서 바꿔요.</p></div>
      <div class="rs-actions"><button class="btn btn-v" type="button" id="bt-go">한꺼번에 실행</button><button class="btn" type="button" id="bt-stop" disabled>멈추기</button>
        <button class="btn" type="button" id="bt-xlsx" ${BT.results.length ? '' : 'disabled'}>엑셀로 받기</button></div>
    </section>
    <div id="bt-out" class="rs-view">${BT.results.length ? '' : '<div class="rs-empty">아직 실행하지 않았어요.</div>'}</div>`;
  if (BT.results.length) btDraw();
  $('#bt-go').onclick = btRun;
  $('#bt-stop').onclick = () => { BT.stop = true; };
  $('#bt-xlsx').onclick = btXlsx;
}
async function btResolve(text) {
  const u = await ensureUniverse();
  const out = []; const miss = [];
  text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean).forEach((s) => {
    const hit = u.companies.find((c) => c.ticker === s.padStart(6, '0')) || u.companies.find((c) => c.name === s) || u.companies.filter((c) => c.name.includes(s))[0];
    if (hit && !out.find((x) => x.ticker === hit.ticker)) out.push({ ticker: hit.ticker, name: hit.name }); else if (!hit) miss.push(s);
  });
  return { list: out.slice(0, 30), miss };
}
async function btRunOne(card, co) {
  let r = null;
  for (let i = 0; i < 40 && !r; i += 1) {   // 엔진이 다른 일을 하는 중(409)이면 3초씩 기다렸다 다시
    try { r = await api('/api/easy/run', { method: 'POST', body: { card, company: co.ticker, cutoff: cutoff() } }); }
    catch (e) { if (e.status !== 409) throw e; await btSleep(3000); }
  }
  if (!r) throw new Error('엔진이 계속 바빠서 실행하지 못했어요');
  let a = null;
  for (let i = 0; i < 90; i += 1) {
    await btSleep(1000);
    a = await api(`/api/easy/answer/${r.id}`);
    if (!['queued', 'running'].includes(a.status)) break;
  }
  return { ...co, run_id: r.id, answer: a };
}
async function btRun() {
  if (BT.running) return;
  const card = $('#bt-card').value;
  const { list, miss } = await btResolve($('#bt-cos').value);
  if (!list.length) { toast('회사를 찾지 못했어요. 종목코드나 이름을 확인해 주세요.'); return; }
  BT.running = true; BT.stop = false; BT.card = card; BT.cutoff = cutoff(); BT.results = [];
  $('#bt-go').disabled = true; $('#bt-stop').disabled = false; $('#bt-xlsx').disabled = true;
  $('#bt-out').innerHTML = `${miss.length ? `<div class="rs-box unk"><p>찾지 못한 이름: ${miss.map(esc).join(', ')}</p></div>` : ''}<div class="rs-empty" id="bt-prog">0 / ${list.length}곳</div><div id="bt-table"></div>`;
  for (let i = 0; i < list.length && !BT.stop; i += 1) {
    $('#bt-prog').textContent = `${i + 1} / ${list.length}곳 — ${list[i].name} 실행 중…`;
    try { BT.results.push(await btRunOne(card, list[i])); } catch (e) { BT.results.push({ ...list[i], error: e.message }); }
    btDraw();
  }
  $('#bt-prog').textContent = BT.stop ? `멈춤 — ${BT.results.length} / ${list.length}곳까지` : `끝 — ${list.length}곳`;
  BT.running = false; $('#bt-go').disabled = false; $('#bt-stop').disabled = true; $('#bt-xlsx').disabled = !BT.results.length;
}
function btCols() {
  const cols = [];
  BT.results.forEach((r) => (r.answer?.key || []).forEach((it) => { const l = btLabel(it, r.name); if (!cols.includes(l)) cols.push(l); }));
  return cols;
}
function btDraw() {
  const cols = btCols();
  const cell = (r, l) => { const it = (r.answer?.key || []).find((x) => btLabel(x, r.name) === l); return it ? `${esc(it.text)}<div class="muted" style="font-size:11px">${esc(it.tier_label || '')}</div>` : '<span class="muted">—</span>'; };
  const box = $('#bt-table') || $('#bt-out');
  box.innerHTML = `<div class="rs-tbl"><table><thead><tr><th>회사</th><th>상태</th>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}<th></th></tr></thead><tbody>
    ${BT.results.map((r) => `<tr><td><b>${esc(r.name)}</b><div class="muted rs-date" style="font-size:12px">${esc(r.ticker)}</div></td>
      <td>${r.error ? `<span class="muted">${esc(r.error)}</span>` : esc(r.answer.status === 'succeeded' ? '완료' : r.answer.status === 'partial' ? '일부 보류' : r.answer.status)}</td>
      ${cols.map((c) => `<td>${r.error ? '—' : cell(r, c)}</td>`).join('')}
      <td>${r.run_id ? `<a class="btn" href="#/answer/${esc(r.run_id)}">답 카드</a>` : ''}</td></tr>`).join('')}</tbody></table></div>
    <p class="muted" style="font-size:13px">질문: ${esc(CARD[BT.card] || BT.card)} · 기준 ${esc(fmtCut(BT.cutoff))} · 칸은 각 회사 답 카드의 「핵심 숫자」 · 엔진이 준 글자 그대로 · AI 모델 호출 0회</p>`;
}
async function btXlsx() {
  const cols = btCols();
  const num = (it) => { const v = Number(it.value); return it.value != null && it.value !== '' && isFinite(v) ? v : it.text; };
  const head = ['회사', '종목코드', '상태', ...cols.flatMap((c) => [c, `${c} 단위`]), '실행 번호'];
  const rows1 = [head, ...BT.results.map((r) => {
    const its = r.answer?.key || [];
    return [r.name, r.ticker, r.error ? `실패: ${r.error}` : r.answer.status, ...cols.flatMap((c) => { const it = its.find((x) => btLabel(x, r.name) === c); return it ? [num(it), it.unit || ''] : ['', '']; }), r.run_id || ''];
  })];
  const rows2 = [['회사', '종목코드', '항목', '값', '단위', '보이는 글자', '값 종류', '계산 단계', '계산 방법', '원문 제목', '원문 주소', '실행 번호']];
  BT.results.forEach((r) => (r.answer?.items || []).forEach((it) => rows2.push([r.name, r.ticker, btLabel(it, r.name), num(it), it.unit || '', it.text, it.kind_label, it.node_name, it.formula || '', it.source?.title || '', it.source?.url || '', r.run_id])));
  const rows3 = [['안내'], [`질문 카드: ${CARD[BT.card] || BT.card}`], [`기준 날짜: ${fmtCut(BT.cutoff)}`], [`만든 때: ${new Date().toLocaleString('ko-KR')}`],
    ['모든 값은 모두의리서치 엔진 답 카드의 값을 그대로 옮긴 것입니다(새 계산 없음).'], ['「실행 번호」로 근거 리서치에서 답 카드·근거 확인서를 다시 열 수 있습니다.'],
    ['사거나 팔라는 판단이 아닙니다. 「값 종류」에서 사실·계산·추정을 구분해 보세요.']];
  try {
    const r = await fetch('/export/xlsx/', { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'same-origin',
      body: JSON.stringify({ filename: `모두의리서치_${CARD[BT.card] || BT.card}_${BT.results.length}곳`, sheets: [{ name: '비교표', rows: rows1 }, { name: '모든 숫자와 출처', rows: rows2 }, { name: '안내', rows: rows3 }] }) });
    if (!r.ok) throw new Error(`엑셀 만들기 실패 (${r.status})`);
    const url = URL.createObjectURL(await r.blob());
    const a = Object.assign(document.createElement('a'), { href: url, download: `모두의리서치_${CARD[BT.card] || BT.card}_${BT.results.length}곳.xlsx` });
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (e) { toast(e.message); }
}

