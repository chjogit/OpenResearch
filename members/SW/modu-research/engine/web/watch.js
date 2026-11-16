'use strict';
/* v0.38 T1 「내 관심 종목」 — 회사 고르기·저장, 사본에 있는 1등급 공시 목록, 접수번호로 받기, 「이 공시는 숫자로 무엇인가?」.
   easy.js 의 api·$·esc·show·toast·info·follow·E 를 그대로 쓴다. 외부 요청 없음. 판단(호재·악재) 없음. */
const W = {pick: null, list: [], open: null, opt: {sort: 'name', group: 'all', sector: '', q: ''}};
const won = v => v == null ? '—' : v >= 1e12 ? (v / 1e12).toLocaleString('ko-KR', {maximumFractionDigits: 1}) + '조' : Math.round(v / 1e8).toLocaleString('ko-KR') + '억';

async function openWatch(){
  show('watch');
  await Promise.all([wLoadList(), wLoadPick(), wLoadNew()]).catch(e => toast(e.message));   // v0.38 T2-2 wLoadNew
}
async function wLoadList(){ const r = await api('/api/watch'); W.list = r.rows; W.limit = r.limit; wDrawList(); }
async function wLoadPick(){
  const q = new URLSearchParams({sort: W.opt.sort, group: W.opt.group, sector: W.opt.sector, q: W.opt.q, cutoff: cutoff()});
  W.pick = await api('/api/watch/pick?' + q.toString()); wDrawPick();
}
function wDrawPick(){
  const p = W.pick, have = new Set(W.list.map(x => x.ticker));
  const sel = (id, opts, cur) => `<select id="${id}">${opts.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;
  $('#wPick').innerHTML = `<div class="wctl">
      ${sel('wSort', [['name', '가나다순'], ['code', '종목코드순'], ['cap', '시가총액순']], W.opt.sort)}
      ${sel('wGroup', p.groups.map(g => [g.key, g.label]), W.opt.group)}
      ${sel('wSector', [['', '모든 업종']].concat(p.sectors.map(s => [s, s])), W.opt.sector)}
      <input id="wQ" placeholder="이름·종목코드 찾기" value="${esc(W.opt.q)}">
    </div>
    <p class="hint">${esc(p.universe_note)} ${esc(p.cap_note)}${W.opt.group === 'smallmid' ? ' ' + esc(p.smallmid_note) : ''}</p>
    <div class="wscroll"><table class="jt"><tr><th>회사</th><th>종목코드</th><th>업종</th><th>시가총액</th><th>순위</th><th></th></tr>
    ${p.rows.map(r => `<tr><td>${esc(r.name)}${r.kospi200 ? ' <span class="b calc">코스피200</span>' : ''}</td><td>${esc(r.ticker)}</td><td>${esc(r.krx_sector || (r.market === 'US' ? '해외' : ''))}</td>
      <td>${r.cap ? esc(won(r.cap)) : '—'}</td><td>${r.cap_rank || '—'}</td>
      <td>${have.has(r.ticker) ? '<span class="hint">담음</span>' : `<button class="ghost" data-add="${esc(r.ticker)}">담기</button>`}</td></tr>`).join('')}</table></div>
    <p class="hint">${p.count}곳</p>`;
  const re = () => wLoadPick().catch(e => toast(e.message));
  $('#wSort').onchange = e => { W.opt.sort = e.target.value; re(); };
  $('#wGroup').onchange = e => { W.opt.group = e.target.value; re(); };
  $('#wSector').onchange = e => { W.opt.sector = e.target.value; re(); };
  let tq; $('#wQ').oninput = e => { clearTimeout(tq); tq = setTimeout(() => { W.opt.q = e.target.value; re().then(() => { const i = $('#wQ'); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
  $('#wPick').querySelectorAll('[data-add]').forEach(b => b.onclick = async () => {
    try { const r = await api('/api/watch', {method: 'POST', body: {ticker: b.dataset.add}}); W.list = r.rows; wDrawList(); wDrawPick(); }
    catch(e){ toast(e.message); }
  });
}
function wDrawList(){
  $('#wList').innerHTML = W.list.length
    ? `<p class="hint">${W.list.length} / ${W.limit}곳</p><ul class="wl">${W.list.map(r => `<li class="${W.open === r.ticker ? 'on' : ''}">
        <b>${esc(r.name)}</b> <span class="hint">${esc(r.ticker)}</span>
        <span class="wbtn"><button class="ghost" data-f="${esc(r.ticker)}">공시 보기</button>
        <button class="ghost" data-q="${esc(r.ticker)}">질문 카드</button>
        <button class="ghost" data-x="${esc(r.ticker)}" title="관심회사에서 빼기">빼기</button></span>
        ${W.open === r.ticker ? '<div id="wFil" class="wfil"></div>' : ''}</li>`).join('')}</ul>`
    : '<p class="hint">아직 담은 회사가 없어요. 아래 목록에서 「담기」를 눌러 주세요.</p>';
  $('#wList').querySelectorAll('[data-x]').forEach(b => b.onclick = async () => {
    const r = await api('/api/watch/remove', {method: 'POST', body: {ticker: b.dataset.x}}); W.list = r.rows; if (W.open === b.dataset.x) W.open = null; wDrawList(); if (W.pick) wDrawPick();
  });
  $('#wList').querySelectorAll('[data-q]').forEach(b => b.onclick = () => { show('home'); choose(b.dataset.q); });
  $('#wList').querySelectorAll('[data-f]').forEach(b => b.onclick = () => { W.open = W.open === b.dataset.f ? null : b.dataset.f; wDrawList(); if (W.open) wFilings(W.open); });
}
async function wFilings(t){
  const box = $('#wFil'); box.innerHTML = '<p class="hint">불러오는 중…</p>';
  try {
    const r = await api('/api/watch/filings/' + t);
    box.innerHTML = `<div class="row"><input id="wNo" placeholder="DART 접수번호 14자리 (예: 20260211800925)" inputmode="numeric" maxlength="14"><button id="wGet">접수번호로 받기</button></div>
      <p class="hint">${esc(r.note)} 지금 숫자로 보는 공시: ${r.kinds ? r.kinds.map(k => esc(k.label)).join(' · ') : ''}. 자회사 공시는 이 회사 숫자로 쓰지 않아요.</p>
      ${r.rows.length ? `<div class="wscroll"><table class="jt"><tr><th>접수일</th><th>종류</th><th>보고서</th><th></th></tr>${r.rows.map(x => `<tr><td>${esc(x.rcept_dt)}</td><td>${esc(x.kind_label)}</td>
        <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>${x.added_by === 'manual' ? ' <span class="hint">(직접 받음)</span>' : ''}</td>
        <td><button data-run="${esc(x.rcept_no)}">숫자로 보기</button></td></tr>`).join('')}</table></div>` : '<p class="hint">사본에 이 회사의 해당 공시가 아직 없어요.</p>'}`;
    $('#wGet').onclick = async () => {
      const no = $('#wNo').value.trim(); if (!/^\d{14}$/.test(no)){ toast('접수번호는 숫자 14자리예요.'); return; }
      $('#wGet').disabled = true;
      try { const g = await api('/api/watch/fetch', {method: 'POST', body: {ticker: t, rcept_no: no}});
        toast(g.new ? `받았어요: ${g.report_nm} (${g.rcept_dt})` : `이미 사본에 있어요: ${g.report_nm}`); await wFilings(t); }
      catch(e){ toast(e.message); $('#wGet').disabled = false; }
    };
    box.querySelectorAll('[data-run]').forEach(b => b.onclick = () => runFiling(t, b.dataset.run));
  } catch(e){ box.innerHTML = `<p class="ng">${esc(e.message)}</p>`; }
}
async function runFiling(t, no){
  E.co = t;
  E.ctx = {card: 'filing', title: '이 공시는 숫자로 무엇인가?', company: t, cutoff: cutoff(), rcept_no: no};
  try { const r = await api('/api/easy/run', {method: 'POST', body: {card: 'filing', company: t, cutoff: E.ctx.cutoff, rcept_no: no}}); follow(r.id); }
  catch(e){ toast(e.message); }
}

/* v0.38 T2-2 「새로 나온 공시」: 앱이 켜져 있는 동안 관심 종목 공시 목록을 자동 확인한 결과를 등급별로 보여 준다.
   1·2등급(숫자가 나오는 공시) → 상(꼭 알아 둘) → 중(알아 둘) 은 펼쳐 두고, 하(참고)는 접어 둔다. 같은 종류가 여러 건이면 한 줄로 묶는다. 판단(호재·악재) 없음. */
const kst = iso => iso ? new Date(iso).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
async function wLoadNew(){ W.ac = await api('/api/watch/autocheck'); wDrawNew(); }
function wDoc(x){   // v0.38 T2-4e 원문 자동 받기·미리 계산 상태
  if (x.doc_state === 'got') return `<br><span class="hint" title="${esc(x.prep_note || '')}">${x.prep_state === 'ready' ? '원문 받음 · 미리 계산함' : '원문 받음'}</span>`;
  if (x.doc_state === 'failed') return `<br><span class="hint" title="${esc(x.doc_note || '')}">원문 자동 받기 실패 — 누르면 다시 받아요</span>`;
  return '';
}
function wRow(x){
  const tag = (x.first_check ? ' <span class="hint">(등록 때 본 공시)</span>' : '') + (x.is_new ? ' <span class="b calc">새로</span>' : '');   // T2-1b F4
  const fix = x.corrected ? ' <span class="b estimate">정정</span>' : '';
  let act = '';
  if (x.grade === 1 && x.can_compute) act = `<button data-calc="${esc(x.rcept_no)}" data-t="${esc(x.ticker)}">숫자로 보기</button>${wDoc(x)}`;
  else if (x.grade === 1) act = '<span class="hint">계산 준비 중</span>';
  else if (x.grade === 2) act = '<span class="hint">가정이 필요한 공시(다음 단계)</span>';
  return `<tr><td title="${esc(wSeen(x))}">${esc(x.rcept_dt)}</td><td>${esc(x.name || x.ticker)}</td><td>${esc(x.label)}${fix}</td>
    <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>${tag}</td><td>${act}</td></tr>`;
}
function wSeen(x){   // T2-1b F2: 앱이 처음 본 시각과, 실제 공시가 뜬 때의 범위
  return `앱이 처음 본 시각 ${kst(x.first_seen_at)}` + (x.seen_gap_min != null ? ` · 실제 공시는 그 전 ${x.seen_gap_min}분 안` : x.first_check ? ' · 처음 등록 때 본 공시' : '');
}
function wSub(x){   // 묶음 안쪽 줄: 회사·종류는 묶음 머리에 있으므로 되풀이하지 않음
  return `<tr><td title="${esc(wSeen(x))}">${esc(x.rcept_dt)}${x.is_new ? ' <span class="b calc">새로</span>' : ''}</td><td>${esc(x.filer || '')}</td><td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>${x.corrected ? ' <span class="b estimate">정정</span>' : ''}${x.first_check ? ' <span class="hint">(등록 때 본 공시)</span>' : ''}</td></tr>`;
}
function wSurge(s){   // v0.39 T3-1 주가 큰 움직임 — 이유는 판단하지 않고 같은 날 공시만 보임
  if (!s) return '';
  const st = !s.has_key ? 'KIS 키가 없어 주가 움직임 감지는 쉬고 있어요(local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'
    : !s.enabled ? '주가 움직임 감지가 꺼져 있어요(MODU_SURGE=0).'
    : `장중 ${s.minutes}분마다 확인 · 오늘 바로 확인 ${s.checks_today}/${s.daily_cap}번 · KIS 조회 ${s.kis_calls_today}회` + (s.last_poll ? ` · 마지막 ${kst(s.last_poll.at)} — ${s.last_poll.message || ''}` : '');
  const pct = v => v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(2)}%`;
  const ev = s.events || [];
  const rows = ev.map(e => `<tr><td>${esc(e.day)}</td><td>${esc(e.name || e.ticker)}</td><td class="n">${pct(e.pct)}</td><td class="n">${e.mkt_pct == null ? '—' : esc(e.mkt) + ' ' + pct(e.mkt_pct)}</td>
    <td>${e.filings.length ? e.filings.map(f => `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.report_nm)}</a>`).join('<br>') : '<span class="hint">같은 날 공시 없음</span>'}</td></tr>`).join('');
  return `<details class="wsec" open><summary><b>주가가 크게 움직인 관심회사</b> <span class="hint">최근 14일 · ${ev.length}건</span></summary>
    <p class="hint">${esc(st)}</p>
    ${rows ? `<div class="wscroll"><table class="jt"><tr><th>거래일</th><th>회사</th><th>전일 대비</th><th>같은 시장 지수</th><th>같은 날 공시</th></tr>${rows}</table></div>` : '<p class="hint">최근 14일에 크게 움직인 관심회사가 없어요.</p>'}
    <p class="hint">${esc(s.note || '')}</p></details>`;
}
function wItem(x){
  if (!x.group) return wRow(x);
  const span = x.from.slice(0, 4) === x.to.slice(0, 4) ? `${x.from}~${x.to.slice(5)}` : `${x.from}~${x.to}`;   // T2-2c 같은 해면 짧게
  return `<tr class="wgrp"><td>${esc(span)}</td><td>${esc(x.name || x.ticker)}</td>
    <td colspan="3"><details><summary>${esc(x.label)} <b>${x.count}건</b></summary>
    <table class="jt wsub"><tr><th>접수일</th><th>보고자</th><th>보고서</th></tr>${x.rows.map(wSub).join('')}</table></details></td></tr>`;   // T2-2b wSub
}
function wDrawNew(){
  const a = W.ac, b = a.board, lr = a.last_run, u = a.usage;
  const head = '<tr><th>접수일</th><th>회사</th><th>종류</th><th>보고서</th><th></th></tr>';
  const sec = (title, note, items, open) => items.length
    ? `<details class="wsec"${open ? ' open' : ''}><summary><b>${esc(title)}</b> <span class="hint">${esc(note)} · ${items.reduce((n, x) => n + (x.count || 1), 0)}건</span></summary>
       <div class="wscroll"><table class="jt">${head}${items.map(wItem).join('')}</table></div></details>` : '';
  const state = !a.has_key ? 'DART 키가 없어 자동 확인을 하지 않아요(local-env.cmd 에 DART_API_KEY).'
    : !a.enabled ? '자동 확인이 꺼져 있어요(MODU_AUTOCHECK=0). 「지금 확인」은 쓸 수 있어요.'
    : a.running ? `${a.interval_min}분마다 자동 확인 · 다음 확인 ${kst(a.next_run_at)}` : '자동 확인은 앱(start.cmd)으로 켰을 때만 돌아요.';
  const last = lr ? `마지막 확인 ${kst(lr.finished_at || lr.started_at)} · ${esc(lr.status_label)} — ${esc(lr.message || '')}` : '아직 확인한 적이 없어요.';
  const any = b.computable.length + b['상'].length + b['중'].length + b['하'].length;
  $('#wNew').innerHTML = `<div class="wstat"><p class="hint">${esc(state)}<br>${last}<br>오늘 DART 사용 ${u.calls.toLocaleString('ko-KR')} / ${u.limit.toLocaleString('ko-KR')}회${u.docs_paused ? ' · 원문 받기 멈춤' : ''}${u.lists_paused ? ' · 목록 확인 멈춤' : ''}</p>
      <button id="wCheck" class="ghost">지금 확인</button></div>
    ${wSurge(a.surge)}
    ${any ? sec('숫자로 볼 수 있는 공시', '1·2등급', b.computable, true) + sec(`상 · ${a.tier_note['상']}`, '3등급', b['상'], true)
      + sec(`중 · ${a.tier_note['중']}`, '3등급', b['중'], true) + sec(`하 · ${a.tier_note['하']}`, '3등급 · 접어 둠', b['하'], false)
      + (b['하_more'] ? `<p class="hint">참고 공시 ${b['하_more']}줄은 더 있어요(오래된 것부터 생략).</p>` : '')
      : `<p class="hint">관심회사의 최근 ${a.window_days || 14}일 공시가 아직 없어요.</p>`}
    <p class="hint">${esc(a.note)} 등급은 제목만 보고 나눈 것이고, 좋다·나쁘다를 뜻하지 않아요.</p>`;
  $('#wCheck').onclick = async () => {
    const btn = $('#wCheck'); btn.disabled = true; btn.textContent = '확인하는 중…';
    try {                                                            // v0.38 T2-4: 뒤에서 돌리고 2초마다 끝났는지 되묻는다(최대 5분)
      await api('/api/watch/autocheck/run?background=1', {method: 'POST'});
      let a = null;
      for (let i = 0; i < 150; i++) {
        await new Promise(r => setTimeout(r, 2000));
        a = await api('/api/watch/autocheck');
        if (!a.checking) break;
        if ($('#wCheck')) $('#wCheck').textContent = `확인하는 중… ${(i + 1) * 2}초`;
      }
      const lr = a && a.last_run;
      toast(a && a.checking ? '아직 확인하고 있어요. 조금 뒤 이 화면을 다시 열어 주세요.' : lr ? `${lr.status_label}: ${lr.message || ''}` : '확인을 마쳤어요.');
    }
    catch(e){ toast(e.message); }
    await wLoadNew().catch(e => toast(e.message));
  };
  $('#wNew').querySelectorAll('[data-calc]').forEach(btn => btn.onclick = async () => {
    btn.disabled = true;
    try { await api('/api/watch/fetch', {method: 'POST', body: {ticker: btn.dataset.t, rcept_no: btn.dataset.calc}}); runFiling(btn.dataset.t, btn.dataset.calc); }
    catch(e){ toast(e.message); btn.disabled = false; }
  });
}
$('#nWatch').onclick = () => openWatch().catch(e => toast(e.message));
$('#wBack').onclick = () => show('home');
