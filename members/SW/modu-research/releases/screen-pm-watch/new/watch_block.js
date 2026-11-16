/* ---------- 관심회사 공시함 (엔진 v0.38~v0.39 쉬운 화면 watch.js 를 옮김 · PM 2026-11-15) ----------
   관심 회사 담기 → 주요 공시를 숫자로(1·2등급) · 새로 나온 공시 자동 확인(등급별) · 주가가 크게 움직인 날 같은 날 공시(KIS 감지).
   엔진 API(/api/watch*, /api/easy/run card=filing)를 그대로 부르고 엔진이 준 글자는 바꾸지 않는다. 좋다·나쁘다 판단 없음. */
const W = { pick: null, list: [], limit: 0, open: null, ac: null, opt: { sort: 'name', group: 'all', sector: '', q: '' } };
const wWon = (v) => (v == null ? '—' : v >= 1e12 ? `${(v / 1e12).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}조` : `${Math.round(v / 1e8).toLocaleString('ko-KR')}억`);
const wKst = (iso) => { if (!iso) return '—'; const d = new Date(iso); if (isNaN(d)) return String(iso); const k = new Date(d.getTime() + 9 * 3600 * 1000).toISOString(); return `${+k.slice(5, 7)}/${+k.slice(8, 10)} ${k.slice(11, 16)}`; };   // 한국 시각 「11/15 21:25」
const wHint = (s) => `<p class="muted" style="font-size:13px">${s}</p>`;
const wTag = (t) => `<span class="chip">${esc(t)}</span>`;

async function viewWatch() {
  crumbs(-1); tab('#/watch');
  view().innerHTML = `<section class="rs-head"><h2>관심회사 공시함</h2><p>관심 회사의 주요 공시를 숫자로 · 새 공시 자동 확인 · 주가가 크게 움직인 날의 같은 날 공시</p></section>
    <div class="rs-box not"><p>공시 종류·등급은 제목으로 나눈 것이고 좋다·나쁘다를 뜻하지 않아요. 사거나 팔라는 판단은 하지 않아요.</p></div>
    <section class="card" style="display:flex;flex-direction:column;gap:10px"><div class="card-h"><h2>새로 나온 공시</h2></div><div id="wNew"><div class="rs-empty">불러오는 중…</div></div></section>
    <section class="card" style="display:flex;flex-direction:column;gap:10px"><div class="card-h"><h2>내 관심회사</h2></div><div id="wList"><div class="rs-empty">불러오는 중…</div></div></section>
    <section class="card" style="display:flex;flex-direction:column;gap:10px"><div class="card-h"><h2>회사 담기</h2></div><div id="wPick"><div class="rs-empty">불러오는 중…</div></div></section>`;
  const r = await Promise.allSettled([wLoadList(), wLoadPick(), wLoadNew()]);
  r.forEach((x, i) => { if (x.status === 'rejected') { const box = ['#wList', '#wPick', '#wNew'][i]; if ($(box)) $(box).innerHTML = errBox(x.reason); } });
}
async function wLoadList() { const r = await api('/api/watch'); W.list = r.rows; W.limit = r.limit; wDrawList(); }
async function wLoadPick() {
  W.pick = await api(`/api/watch/pick?${qs({ sort: W.opt.sort, group: W.opt.group, sector: W.opt.sector, q: W.opt.q, cutoff: cutoff() })}`);
  wDrawPick();
}
function wDrawPick() {
  const p = W.pick; const have = new Set(W.list.map((x) => x.ticker));
  const sel = (id, opts, cur, label) => `<select class="rs-input" style="width:auto" id="${id}" aria-label="${label}">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  $('#wPick').innerHTML = `<div class="rs-actions">
      ${sel('wSort', [['name', '가나다순'], ['code', '종목코드순'], ['cap', '시가총액순']], W.opt.sort, '정렬')}
      ${sel('wGroup', p.groups.map((g) => [g.key, g.label]), W.opt.group, '묶음')}
      ${sel('wSector', [['', '모든 업종']].concat(p.sectors.map((s) => [s, s])), W.opt.sector, '업종')}
      <input class="rs-input" style="flex:1;min-width:160px" id="wQ" placeholder="이름·종목코드 찾기" value="${esc(W.opt.q)}" aria-label="회사 찾기"></div>
    ${wHint(`${esc(p.universe_note)} ${esc(p.cap_note)}${W.opt.group === 'smallmid' ? ` ${esc(p.smallmid_note)}` : ''}`)}
    <div class="rs-tbl" style="max-height:360px;overflow:auto"><table><thead><tr><th>회사</th><th>종목코드</th><th>업종</th><th>시가총액</th><th>순위</th><th></th></tr></thead><tbody>
    ${p.rows.map((r) => `<tr><td>${esc(r.name)}${r.kospi200 ? ` ${wTag('코스피200')}` : ''}</td><td class="rs-date">${esc(r.ticker)}</td><td>${esc(r.krx_sector || (r.market === 'US' ? '해외' : ''))}</td>
      <td class="n">${r.cap ? esc(wWon(r.cap)) : '—'}</td><td class="n">${r.cap_rank || '—'}</td>
      <td>${have.has(r.ticker) ? '<span class="muted">담음</span>' : `<button class="btn" type="button" data-add="${esc(r.ticker)}">담기</button>`}</td></tr>`).join('')}</tbody></table></div>
    ${wHint(`${esc(p.count)}곳`)}`;
  const re = () => wLoadPick().catch((e) => toast(e.message));
  $('#wSort').onchange = (e) => { W.opt.sort = e.target.value; re(); };
  $('#wGroup').onchange = (e) => { W.opt.group = e.target.value; re(); };
  $('#wSector').onchange = (e) => { W.opt.sector = e.target.value; re(); };
  let tq; $('#wQ').oninput = (e) => { clearTimeout(tq); tq = setTimeout(() => { W.opt.q = e.target.value; re().then(() => { const i = $('#wQ'); if (i) { i.focus(); i.setSelectionRange(i.value.length, i.value.length); } }); }, 300); };
  $('#wPick').querySelectorAll('[data-add]').forEach((b) => { b.onclick = async () => {
    try { const r = await api('/api/watch', { method: 'POST', body: { ticker: b.dataset.add } }); W.list = r.rows; wDrawList(); wDrawPick(); } catch (e) { toast(e.message); }
  }; });
}
function wDrawList() {
  $('#wList').innerHTML = W.list.length
    ? `${wHint(`${W.list.length} / ${esc(W.limit)}곳`)}<ul style="list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px">${W.list.map((r) => `<li style="border:1px solid var(--line);border-radius:10px;padding:10px 12px">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><b>${esc(r.name)}</b> <span class="muted rs-date">${esc(r.ticker)}</span>
        <span style="margin-left:auto;display:flex;gap:6px;flex-wrap:wrap"><button class="btn" type="button" data-f="${esc(r.ticker)}" aria-expanded="${W.open === r.ticker}">공시 보기</button>
        <button class="btn" type="button" data-q="${esc(r.ticker)}" data-n="${esc(r.name)}">질문 카드</button>
        <button class="btn" type="button" data-x="${esc(r.ticker)}" title="관심회사에서 빼기">빼기</button></span></div>
        ${W.open === r.ticker ? '<div id="wFil" style="margin-top:10px"></div>' : ''}</li>`).join('')}</ul>`
    : wHint('아직 담은 회사가 없어요. 아래 「회사 담기」에서 「담기」를 눌러 주세요.');
  $('#wList').querySelectorAll('[data-x]').forEach((b) => { b.onclick = async () => {
    try { const r = await api('/api/watch/remove', { method: 'POST', body: { ticker: b.dataset.x } }); W.list = r.rows; if (W.open === b.dataset.x) W.open = null; wDrawList(); if (W.pick) wDrawPick(); } catch (e) { toast(e.message); }
  }; });
  $('#wList').querySelectorAll('[data-q]').forEach((b) => { b.onclick = () => { S.company = { ticker: b.dataset.q, name: b.dataset.n }; Store.set(KEY('company'), S.company); location.hash = '#/'; }; });
  $('#wList').querySelectorAll('[data-f]').forEach((b) => { b.onclick = () => { W.open = W.open === b.dataset.f ? null : b.dataset.f; wDrawList(); if (W.open) wFilings(W.open); }; });
}
async function wFilings(t) {
  const box = $('#wFil'); box.innerHTML = '<div class="rs-empty">불러오는 중…</div>';
  let r; try { r = await api(`/api/watch/filings/${encodeURIComponent(t)}`); } catch (e) { box.innerHTML = errBox(e); return; }
  box.innerHTML = `<form class="rs-actions" id="wGetF"><input class="rs-input" style="flex:1;min-width:200px" id="wNo" placeholder="DART 접수번호 14자리 (예: 20260211800925)" inputmode="numeric" maxlength="14" aria-label="DART 접수번호"><button class="btn" id="wGet">접수번호로 받기</button></form>
    ${wHint(`${esc(r.note)} 지금 숫자로 보는 공시: ${r.kinds ? r.kinds.map((k) => esc(k.label)).join(' · ') : ''}. 자회사 공시는 이 회사 숫자로 쓰지 않아요.`)}
    ${r.rows.length ? `<div class="rs-tbl" style="max-height:320px;overflow:auto"><table><thead><tr><th>접수일</th><th>종류</th><th>보고서</th><th></th></tr></thead><tbody>${r.rows.map((x) => `<tr><td class="rs-date">${esc(x.rcept_dt)}</td><td>${esc(x.kind_label)}</td>
      <td>${safeUrl(x.url) ? `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>` : esc(x.report_nm)}${x.added_by === 'manual' ? ' <span class="muted">(직접 받음)</span>' : ''}</td>
      <td><button class="btn btn-v" type="button" data-run="${esc(x.rcept_no)}">숫자로 보기</button></td></tr>`).join('')}</tbody></table></div>` : wHint('사본에 이 회사의 해당 공시가 아직 없어요.')}`;
  $('#wGetF').onsubmit = async (e) => {
    e.preventDefault();
    const no = $('#wNo').value.trim(); if (!/^\d{14}$/.test(no)) { toast('접수번호는 숫자 14자리예요.'); return; }
    $('#wGet').disabled = true;
    try { const g = await api('/api/watch/fetch', { method: 'POST', body: { ticker: t, rcept_no: no } });
      toast(g.new ? `받았어요: ${g.report_nm} (${g.rcept_dt})` : `이미 사본에 있어요: ${g.report_nm}`); await wFilings(t); }
    catch (err) { toast(err.message); $('#wGet').disabled = false; }
  };
  box.querySelectorAll('[data-run]').forEach((b) => { b.onclick = () => wRunFiling(t, b.dataset.run); });
}
async function wRunFiling(t, no) {
  try { const r = await api('/api/easy/run', { method: 'POST', body: { card: 'filing', company: t, cutoff: cutoff(), rcept_no: no } }); location.hash = `#/run/${r.id}`; }
  catch (e) { toast(e.message); }
}
async function wLoadNew() { W.ac = await api('/api/watch/autocheck'); wDrawNew(); }
function wDoc(x) {   // 원문 자동 받기·미리 계산 상태 (v0.38 T2-4e)
  if (x.doc_state === 'got') return `<br><span class="muted" style="font-size:12px" title="${esc(x.prep_note || '')}">${x.prep_state === 'ready' ? '원문 받음 · 미리 계산함' : '원문 받음'}</span>`;
  if (x.doc_state === 'failed') return `<br><span class="muted" style="font-size:12px" title="${esc(x.doc_note || '')}">원문 자동 받기 실패 — 누르면 다시 받아요</span>`;
  return '';
}
function wSeen(x) { return `앱이 처음 본 시각 ${wKst(x.first_seen_at)}${x.seen_gap_min != null ? ` · 실제 공시는 그 전 ${x.seen_gap_min}분 안` : x.first_check ? ' · 처음 등록 때 본 공시' : ''}`; }
const wLink = (x) => (safeUrl(x.url) ? `<a href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>` : esc(x.report_nm));
function wRow(x) {
  const tag = (x.first_check ? ' <span class="muted">(등록 때 본 공시)</span>' : '') + (x.is_new ? ` ${wTag('새로')}` : '');
  const fix = x.corrected ? ` ${wTag('정정')}` : '';
  let act = '';
  if (x.grade === 1 && x.can_compute) act = `<button class="btn btn-v" type="button" data-calc="${esc(x.rcept_no)}" data-t="${esc(x.ticker)}">숫자로 보기</button>${wDoc(x)}`;
  else if (x.grade === 1) act = '<span class="muted">계산 준비 중</span>';
  else if (x.grade === 2) act = '<span class="muted">가정이 필요한 공시(다음 단계)</span>';
  return `<tr><td class="rs-date" title="${esc(wSeen(x))}">${esc(x.rcept_dt)}</td><td>${esc(x.name || x.ticker)}</td><td>${esc(x.label)}${fix}</td><td>${wLink(x)}${tag}</td><td>${act}</td></tr>`;
}
function wSub(x) {
  return `<tr><td class="rs-date" title="${esc(wSeen(x))}">${esc(x.rcept_dt)}${x.is_new ? ` ${wTag('새로')}` : ''}</td><td>${esc(x.filer || '')}</td><td>${wLink(x)}${x.corrected ? ` ${wTag('정정')}` : ''}${x.first_check ? ' <span class="muted">(등록 때 본 공시)</span>' : ''}</td></tr>`;
}
function wItem(x) {
  if (!x.group) return wRow(x);
  const span = x.from.slice(0, 4) === x.to.slice(0, 4) ? `${x.from}~${x.to.slice(5)}` : `${x.from}~${x.to}`;
  return `<tr><td class="rs-date">${esc(span)}</td><td>${esc(x.name || x.ticker)}</td>
    <td colspan="3"><details><summary>${esc(x.label)} <b>${esc(x.count)}건</b></summary>
    <div class="rs-tbl"><table><thead><tr><th>접수일</th><th>보고자</th><th>보고서</th></tr></thead><tbody>${x.rows.map(wSub).join('')}</tbody></table></div></details></td></tr>`;
}
function wSurge(s) {   // 주가 큰 움직임(v0.39 T3-1) — 이유는 판단하지 않고 같은 날 공시만. 시세 숫자는 엔진이 준 등락률만
  if (!s) return '';
  const st = !s.has_key ? 'KIS 키가 없어 주가 움직임 감지는 쉬고 있어요(엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'
    : !s.enabled ? '주가 움직임 감지가 꺼져 있어요(MODU_SURGE=0).'
    : `장중 ${s.minutes}분마다 확인 · 오늘 바로 확인 ${s.checks_today}/${s.daily_cap}번 · KIS 조회 ${s.kis_calls_today}회${s.last_poll ? ` · 마지막 ${wKst(s.last_poll.at)} — ${s.last_poll.message || ''}` : ''}`;
  const pct = (v) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%`);
  const ev = s.events || [];
  const rows = ev.map((e) => `<tr><td class="rs-date">${esc(e.day)}</td><td>${esc(e.name || e.ticker)}</td><td class="n">${pct(e.pct)}</td><td class="n">${e.mkt_pct == null ? '—' : `${esc(e.mkt)} ${pct(e.mkt_pct)}`}</td>
    <td>${e.filings.length ? e.filings.map(wLink).join('<br>') : '<span class="muted">같은 날 공시 없음</span>'}</td></tr>`).join('');
  return `<details class="rs-fold" open><summary>주가가 크게 움직인 관심회사 · 최근 14일 ${ev.length}건</summary><div>
    ${wHint(esc(st))}
    ${rows ? `<div class="rs-tbl"><table><thead><tr><th>거래일</th><th>회사</th><th>전일 대비</th><th>같은 시장 지수</th><th>같은 날 공시</th></tr></thead><tbody>${rows}</tbody></table></div>` : wHint('최근 14일에 크게 움직인 관심회사가 없어요.')}
    ${wHint(esc(s.note || ''))}</div></details>`;
}
function wDrawNew() {
  const a = W.ac; const b = a.board; const lr = a.last_run; const u = a.usage;
  const head = '<thead><tr><th>접수일</th><th>회사</th><th>종류</th><th>보고서</th><th></th></tr></thead>';
  const sec = (title, note, items, open) => (items.length
    ? `<details class="rs-fold"${open ? ' open' : ''}><summary>${esc(title)} · ${esc(note)} · ${items.reduce((n, x) => n + (x.count || 1), 0)}건</summary><div>
       <div class="rs-tbl"><table>${head}<tbody>${items.map(wItem).join('')}</tbody></table></div></div></details>` : '');
  const state = !a.has_key ? 'DART 키가 없어 자동 확인을 하지 않아요(엔진 local-env.cmd 에 DART_API_KEY).'
    : !a.enabled ? '자동 확인이 꺼져 있어요(MODU_AUTOCHECK=0). 「지금 확인」은 쓸 수 있어요.'
    : a.running ? `${a.interval_min}분마다 자동 확인 · 다음 확인 ${wKst(a.next_run_at)}` : '자동 확인은 엔진(start.cmd)으로 켰을 때만 돌아요.';
  const last = lr ? `마지막 확인 ${wKst(lr.finished_at || lr.started_at)} · ${esc(lr.status_label)} — ${esc(lr.message || '')}` : '아직 확인한 적이 없어요.';
  const any = b.computable.length + b['상'].length + b['중'].length + b['하'].length;
  $('#wNew').innerHTML = `<div style="display:flex;gap:12px;align-items:flex-start;justify-content:space-between;flex-wrap:wrap"><div style="flex:1;min-width:240px">
      ${wHint(`${esc(state)}<br>${last}<br>오늘 DART 사용 ${u.calls.toLocaleString('ko-KR')} / ${u.limit.toLocaleString('ko-KR')}회${u.docs_paused ? ' · 원문 받기 멈춤' : ''}${u.lists_paused ? ' · 목록 확인 멈춤' : ''}`)}</div>
      <button class="btn" type="button" id="wCheck">지금 확인</button></div>
    ${wSurge(a.surge)}
    ${any ? sec('숫자로 볼 수 있는 공시', '1·2등급', b.computable, true) + sec(`상 · ${a.tier_note['상']}`, '3등급', b['상'], true)
      + sec(`중 · ${a.tier_note['중']}`, '3등급', b['중'], true) + sec(`하 · ${a.tier_note['하']}`, '3등급 · 접어 둠', b['하'], false)
      + (b['하_more'] ? wHint(`참고 공시 ${esc(b['하_more'])}줄은 더 있어요(오래된 것부터 생략).`) : '')
      : wHint(`관심회사의 최근 ${esc(a.window_days || 14)}일 공시가 아직 없어요.`)}
    ${wHint(`${esc(a.note)} 등급은 제목만 보고 나눈 것이고, 좋다·나쁘다를 뜻하지 않아요.`)}`;
  $('#wCheck').onclick = async () => {
    const btn = $('#wCheck'); btn.disabled = true; btn.textContent = '확인하는 중…';
    try {   // 뒤에서 돌리고 2초마다 끝났는지 되묻는다(최대 5분)
      await api('/api/watch/autocheck/run?background=1', { method: 'POST' });
      let s = null;
      for (let i = 0; i < 150; i += 1) {
        await new Promise((ok) => setTimeout(ok, 2000));
        s = await api('/api/watch/autocheck');
        if (!s.checking) break;
        if ($('#wCheck')) $('#wCheck').textContent = `확인하는 중… ${(i + 1) * 2}초`;
      }
      const l = s && s.last_run;
      toast(s && s.checking ? '아직 확인하고 있어요. 조금 뒤 이 화면을 다시 열어 주세요.' : l ? `${l.status_label}: ${l.message || ''}` : '확인을 마쳤어요.');
    } catch (e) { toast(e.message); }
    await wLoadNew().catch((e) => toast(e.message));
  };
  $('#wNew').querySelectorAll('[data-calc]').forEach((btn) => { btn.onclick = async () => {
    btn.disabled = true;
    try { await api('/api/watch/fetch', { method: 'POST', body: { ticker: btn.dataset.t, rcept_no: btn.dataset.calc } }); wRunFiling(btn.dataset.t, btn.dataset.calc); }
    catch (e) { toast(e.message); btn.disabled = false; }
  }; });
}

