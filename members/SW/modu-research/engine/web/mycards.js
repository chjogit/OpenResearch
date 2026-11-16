/* v0.36 전문가 모드 — 늘어나는 것은 두 가지뿐:
   ① 머리줄 「기업」 칸: 이 흐름의 모든 자료 노드의 회사를 한 번에 바꾸고, 섞여 있으면 알려 줌 (T1)
   ② 「내 질문 카드」 단추: 지금 흐름을 쉬운 화면 카드로 저장 · 내 카드 목록 · 묶음 파일 내보내기/가져오기 (T2·T3)
   app.js는 고치지 않고 renderHeader만 감싼다. */
(function(){
  if (document.getElementById('mc36css')) return;
  const st = document.createElement('style'); st.id = 'mc36css';
  st.textContent = `
  #coAllWrap input{width:170px}
  .comix[hidden]{display:none}
  .comix{display:inline-block;margin-left:6px;padding:2px 9px;border-radius:999px;background:#fff4e0;border:1px solid #f0c36d;color:#8a5a00;font-size:12px;cursor:help;white-space:nowrap}
  .mc h2{margin:0 0 4px}.mc .lead{color:var(--mute);margin:0 0 12px}
  .mc section{border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin:0 0 12px;background:#fff}
  .mc section h3{margin:0 0 8px;font-size:15px}
  .mc .row{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:6px 0}
  .mc .row label{display:flex;gap:6px;align-items:center}
  .mc input[type=text]{min-width:300px}
  .mc .ok{color:#2b8a3e}.mc .no{color:#c2410c}
  .mc table{width:100%;border-collapse:collapse;font-size:13px}.mc td,.mc th{padding:7px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:middle}
  .mc th{background:#f6f5f2;font-weight:600}.mc .sub{color:var(--mute);font-size:12px}
  .mc .chipk{display:inline-block;font-size:11px;padding:1px 7px;border-radius:999px;background:#eef2f7;margin-right:4px}
  .mc .note{font-size:12.5px;color:var(--mute);line-height:1.6}`;
  document.head.appendChild(st);
})();

/* ---------------- T1 기업 한꺼번에 바꾸기 ---------------- */
function mcFields(t){
  const sc = (spec(t) || {}).config_schema || {};
  return Object.entries(sc).filter(([k, f]) => (k === 'company' && ['company', 'enum'].includes(f.type)) || (k === 'companies' && f.type === 'multi'))
    .map(([k, f]) => ({k, many: k === 'companies', opts: f.type === 'company' ? null : (f.options || [])}));
}
function mcCompanies(){
  const used = new Map();     // ticker → [노드 이름]
  (S.doc ? S.doc.nodes : []).forEach(n => mcFields(n.type).forEach(f => {
    const v = n.config[f.k]; (f.many ? (Array.isArray(v) ? v : []) : (v ? [v] : [])).forEach(t => { if (!used.has(t)) used.set(t, []); used.get(t).push(`${n.type} ${(spec(n.type) || {}).display_name || ''}`); });
  }));
  return used;
}
function mcHasSlots(){ return (S.doc ? S.doc.nodes : []).some(n => mcFields(n.type).length); }
function mcRefresh(){
  const wrap = $('#coAllWrap'); if (!wrap) return;
  const has = mcHasSlots(); wrap.hidden = !has; const mix = $('#coMix');
  if (!has){ mix.hidden = true; return; }
  const used = mcCompanies(), inp = $('#coAll');
  if (document.activeElement !== inp) inp.value = used.size === 1 ? coLabel([...used.keys()][0]) : '';
  inp.placeholder = used.size > 1 ? '하나로 맞추기' : '회사 이름이나 종목코드';
  if (used.size > 1){
    mix.hidden = false; mix.textContent = `⚠ 회사 ${used.size}곳이 섞여 있어요`;
    mix.title = [...used.entries()].map(([t, ns]) => `${coLabel(t)}: ${ns.join(', ')}`).join('\n') + '\n\n일부러 두 회사를 비교하는 게 아니라면 왼쪽 「기업」 칸에서 하나로 맞추세요.';
  } else mix.hidden = true;
}
function mcApply(t){
  const changed = [], skipped = [], recheck = [];
  S.doc.nodes.forEach(n => {
    mcFields(n.type).forEach(f => {
      const nm = `${n.type} ${(spec(n.type) || {}).display_name || ''}`;
      if (f.many){ const cur = n.config[f.k]; if (!Array.isArray(cur) || !cur.length) return;
        if (f.opts.length && !f.opts.includes(t)){ skipped.push(nm); return; }
        n.config[f.k] = [t]; changed.push(nm); return; }
      if (f.opts && f.opts.length && !f.opts.includes(t)){ skipped.push(nm); return; }
      if (n.config[f.k] !== t){ n.config[f.k] = t; changed.push(nm); }
    });
    if (['T03', 'T04'].includes(n.type)) recheck.push(`${n.type} ${(spec(n.type) || {}).display_name || ''}`);
  });
  const nm = (S.doc.name || '').replace(/(—\s*)(\d{6}|[0-9A-Z]{6})\s*$/, `$1${t}`);
  if (nm !== S.doc.name){ S.doc.name = nm; $('#wfName').value = nm; }
  touch(); renderAll();
  let msg = changed.length ? `${coLabel(t)}(으)로 ${changed.length}개 단계를 바꿨어요.` : `이미 ${coLabel(t)}예요.`;
  if (skipped.length) msg += ` 원문 두 회사(삼성전자·SK하이닉스)만 되는 단계는 그대로 뒀어요: ${skipped.join(', ')}.`;
  if (recheck.length) msg += ` 회사마다 값이 다른 단계는 직접 확인해 주세요: ${recheck.join(', ')}.`;
  toast(msg);
}
function mcSetupBar(){
  if ($('#coAllWrap')) return;
  const cut = $('#cutoff') && $('#cutoff').closest('label'); if (!cut) return;
  cut.insertAdjacentHTML('afterend', `<label class="cut" id="coAllWrap" title="이 흐름의 가격·수급·공시 같은 자료 노드 회사를 한 번에 바꿔요">기업 <input id="coAll" list="coAllList" autocomplete="off" aria-label="이 흐름의 기업"><datalist id="coAllList"></datalist></label><span id="coMix" class="comix" hidden></span>`);
  const inp = $('#coAll');
  inp.onfocus = async () => { const u = await loadUniverse(); if (u && !$('#coAllList').children.length)
    $('#coAllList').innerHTML = u.companies.filter(c => c.market === 'KR').map(c => `<option value="${esc(c.ticker + ' ' + c.name)}"></option>`).join(''); };
  const go = async () => { await loadUniverse(); const t = resolveCo(inp.value);
    if (!t){ const cs = coCands(inp.value); if (inp.value.trim()) toast(cs.length > 1 ? `${cs.length}곳이 맞아요: ${cs.slice(0, 5).join(', ')} — 하나를 골라 주세요.` : '사본에 없는 회사예요.'); return; }
    inp.blur(); mcApply(t); };
  inp.onchange = go; inp.onkeydown = e => { if (e.key === 'Enter'){ e.preventDefault(); go(); } };
  mcRefresh();
}
const _mcRenderHeader = renderHeader;
renderHeader = function(){ _mcRenderHeader(); try { mcRefresh(); } catch(e){} };

/* ---------------- T2·T3 내 질문 카드 ---------------- */
function mcGuessKind(){
  const ts = new Set(S.doc.nodes.map(n => n.type));
  if (['N02', 'N06', 'N14', 'N16', 'N17', 'N18'].some(t => ts.has(t))) return '가정';
  if (ts.has('N15')) return '관계';
  return '사실';
}
function mcDefaultTitle(){ return (S.doc.name || '').replace(/\s*—\s*\S+\s*$/, '').trim().slice(0, 60); }
function mcDownload(obj, name){
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 1)], {type: 'application/json'}));
  a.download = name; document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
async function openMyCards(){
  syncHeader();
  const blocked = S.doc.nodes.filter(n => ['T03', 'T04'].includes(n.type));
  const slots = mcHasSlots(), used = mcCompanies();
  const canSave = S.doc.nodes.length && slots && !blocked.length;
  const fresh = S.runId && S.run && !S.editedSinceRun && !['waiting', 'queued', 'running'].includes(S.run.status);
  let list = []; try { list = (await api('/api/mycards')).cards; } catch(e){}
  $('#dlgBody').innerHTML = `<div class="mc"><h2>내 질문 카드</h2>
    <p class="lead">지금 흐름을 쉬운 화면의 질문 카드로 저장해요. 회사는 비워 두고, 쉬운 화면에서 고른 회사로 바꿔 계산해요.</p>
    <section><h3>지금 흐름을 카드로 저장</h3>
      ${canSave ? '' : `<p class="no">${!S.doc.nodes.length ? '캔버스가 비어 있어요.' : !slots ? '회사를 고르는 자료 노드(가격·수급·공시 등)가 하나는 있어야 종목을 바꿔 끼울 수 있어요.' :
        `회사마다 값이 다른 단계가 있어 카드로 저장할 수 없어요: ${blocked.map(n => esc(n.type + ' ' + spec(n.type).display_name)).join(', ')}. 이 단계를 빼고 저장해 주세요.`}</p>`}
      <div class="row"><label>제목 <input type="text" id="mcTitle" maxlength="60" value="${esc(mcDefaultTitle())}" placeholder="예: 환율과 함께 움직였나?"></label></div>
      <div class="row"><label>한 줄 설명 <input type="text" id="mcSub" maxlength="120" placeholder="(선택) 무엇을 보는 카드인지"></label>
        <label>종류 <select id="mcKind">${['사실', '관계', '가정'].map(k => `<option ${k === mcGuessKind() ? 'selected' : ''}>${k}</option>`).join('')}</select></label></div>
      <p class="note">단계 ${S.doc.nodes.length}개 · 회사 칸 ${[...used.keys()].length ? '지금 ' + [...used.keys()].map(t => esc(coLabel(t))).join(', ') + ' → 저장 땐 비움' : '없음'}
        ${fresh ? ' · <span class="ok">방금 실행한 결과의 근거 확인서도 함께 묶어 둬요(내보낼 때 같이 들어감)</span>' : ' · 실행한 뒤 바꾸지 않고 저장하면 근거 확인서도 함께 묶어 둬요'}</p>
      <button class="primary" id="mcSave" ${canSave ? '' : 'disabled'}>쉬운 화면에 카드로 저장</button></section>
    <section><h3>내가 만든 카드 ${list.length}개</h3>
      ${list.length ? `<table><tr><th>카드</th><th>종류</th><th>단계</th><th>근거 확인서</th><th></th></tr>${list.map(c => `<tr>
        <td><b>${esc(c.title)}</b>${c.sub ? `<div class="sub">${esc(c.sub)}</div>` : ''}<div class="sub">${c.origin === 'imported' ? '받은 묶음에서 가져옴' : '내가 만듦'} · ${esc((c.created_at || '').slice(0, 10))}</div></td>
        <td><span class="chipk">${esc(c.kind)}</span></td><td class="sub">${esc(c.node_types.join(' · '))}</td>
        <td class="sub">${c.has_receipt || c.source_run ? '있음' : '—'}</td>
        <td style="white-space:nowrap"><button data-mcx="${esc(c.id)}">묶음 파일로 내보내기</button> <button data-mch="${esc(c.id)}">숨기기</button></td></tr>`).join('')}</table>`
        : '<p class="sub">아직 없어요. 저장하면 쉬운 화면 「내가 만든 질문」 묶음에 나타나요.</p>'}</section>
    <section><h3>받은 묶음 가져오기</h3>
      <p class="note">다른 사람이 내보낸 <b>질문 카드 묶음 파일(.json)</b>을 넣으면 내 카드로 들어와요. 앱이 지문(해시)과 단계를 검사하고, 묶음 안 근거 확인서는 같은 사본에서 다시 계산해 볼 수 있어요. 순위·적중률·추천은 담지 않아요.</p>
      <div class="row"><input type="file" id="mcFile" accept=".json,application/json"></div><div id="mcImp"></div></section>
    <p class="note">카드는 조사 방법일 뿐 결론이 아니에요. 같은 방법으로 여러 회사를 같은 규율로 볼 수 있게 하는 게 목적이에요.</p></div>`;
  $('#dlg').classList.add('wide'); $('#dlg').addEventListener('close', () => $('#dlg').classList.remove('wide'), {once: true});
  if (!$('#dlg').open) $('#dlg').showModal();
  const sv = $('#mcSave'); if (sv) sv.onclick = async () => {
    try { const r = await api('/api/mycards', {method: 'POST', body: {doc: S.doc, title: $('#mcTitle').value, sub: $('#mcSub').value, kind: $('#mcKind').value, source_run: fresh ? S.runId : null}});
      toast(`저장했어요. 쉬운 화면 「내가 만든 질문」에서 회사를 골라 눌러 보세요.${r.with_receipt ? ' (근거 확인서 함께 묶음)' : ''}`); openMyCards(); }
    catch(e){ toast('저장 못 했어요: ' + ((e.data && e.data.message) || e.message)); } };
  $('#dlgBody').querySelectorAll('[data-mcx]').forEach(b => b.onclick = async () => {
    try { const bd = await api(`/api/mycards/${b.dataset.mcx}/export`); mcDownload(bd, `질문카드_${bd.title.replace(/[\\/:*?"<>|\s]+/g, '_').slice(0, 40)}.json`);
      toast(bd.receipt ? '내보냈어요 — 조사 방법 + 근거 확인서 묶음이에요.' : '내보냈어요 — 근거 확인서는 없어요(카드 저장 전에 실행한 결과가 없음).'); }
    catch(e){ toast('내보내기 실패: ' + e.message); } });
  $('#dlgBody').querySelectorAll('[data-mch]').forEach(b => b.onclick = async () => {
    try { await api(`/api/mycards/${b.dataset.mch}/hide`, {method: 'POST', body: {}}); toast('숨겼어요. 쉬운 화면에서도 사라져요.'); openMyCards(); }
    catch(e){ toast('숨기기 실패: ' + e.message); } });
  $('#mcFile').onchange = async ev => {
    const f = ev.target.files[0]; if (!f) return; const box = $('#mcImp');
    let bd; try { bd = JSON.parse(await f.text()); } catch(e){ box.innerHTML = '<p class="no">JSON 파일이 아니에요.</p>'; return; }
    try { const r = await api('/api/mycards/import', {method: 'POST', body: {bundle: bd}});
      box.innerHTML = `<p class="ok">「${esc(r.title)}」 카드를 가져왔어요. 쉬운 화면 「내가 만든 질문」에 생겼어요.</p>${r.with_receipt ? '<button id="mcVer">묶음 안 근거 확인서 다시 계산해 보기</button> <span id="mcVerOut" class="sub"></span>' : '<p class="sub">이 묶음에는 근거 확인서가 없어요.</p>'}`;
      const vb = $('#mcVer'); if (vb) vb.onclick = async () => { vb.disabled = true; $('#mcVerOut').textContent = '다시 계산하는 중…';
        try { const v = await api('/api/easy/verify', {method: 'POST', body: {receipt: bd.receipt}}); $('#mcVerOut').innerHTML = `<b class="${v.ok ? 'ok' : 'no'}">${esc(v.reason)}</b> (${v.matched ?? 0}/${v.total ?? 0} 단계 일치)`; }
        catch(e){ $('#mcVerOut').textContent = '다시 계산 실패: ' + e.message; } vb.disabled = false; };
      setTimeout(() => { const keep = box.innerHTML; openMyCards().then(() => { $('#mcImp').innerHTML = keep; const vb2 = $('#mcVer'); if (vb2 && vb) vb2.onclick = vb.onclick; }); }, 50);
    } catch(e){ box.innerHTML = `<p class="no">가져오지 못했어요: ${esc((e.data && e.data.message) || e.message)}</p>`; }
  };
}
function mcSetupButton(){
  if ($('#bMyCard') || !$('#bSave')) return;
  $('#bSave').insertAdjacentHTML('afterend', `<button id="bMyCard" data-tip="지금 흐름을 쉬운 화면의 질문 카드로 저장해요(회사는 고른 회사로 바뀜). 내 카드 목록·묶음 파일 내보내기/가져오기도 여기서." aria-description="지금 흐름을 쉬운 화면의 질문 카드로 저장해요.">내 질문 카드</button>`);
  $('#bMyCard').onclick = openMyCards;
}
(function mcBoot(){
  const ready = () => $('#cutoff') && $('#bSave') && S.specs && Object.keys(S.specs).length;
  let n = 0; const t = setInterval(() => { if (ready() || ++n > 100){ clearInterval(t); if (ready()){ mcSetupBar(); mcSetupButton(); mcRefresh(); } } }, 100);
})();
