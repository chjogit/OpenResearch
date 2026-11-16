'use strict';
/* 모두의리서치 쉬운 화면 1.4 — 문 → 회사 → 질문 → 답 → 근거. 외부 요청 없음. */
const UI_VERSION = '쉬운 화면 1.4';
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const E = {uni:null, co:null, cards:[], groups:[], rid:null, ans:null, poll:null, ctx:null, door:'ask'};

function csrf(){ const m = document.cookie.match(/(?:^|; )mrn_csrf=([^;]+)/); return m ? m[1] : ''; }
async function api(path, opt={}){
  const o = {method: opt.method || 'GET', headers: {'Content-Type':'application/json'}};
  if (o.method !== 'GET') o.headers['X-CSRF-Token'] = csrf();
  if (opt.body !== undefined) o.body = JSON.stringify(opt.body);
  const r = await fetch(path, o);
  let data = null; try { data = await r.json(); } catch(e) {}
  if (!r.ok){ const d = data && data.detail; const err = new Error(typeof d === 'string' ? d : (d && d.issues ? d.issues.map(i => i.message).join(' / ') : (d && d.message) ? d.message : '요청이 거절됐어요')); err.status = r.status; throw err; }   // v0.38: {code, message} 오류도 엔진 문장 그대로
  return data;
}
function toast(m){ const t = $('#toast'); t.textContent = m; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('on'), 3200); }
function show(id){ document.querySelectorAll('.view').forEach(v => v.hidden = v.id !== id); window.scrollTo(0, 0);
  const xl = document.getElementById('nExpert'); if (xl) xl.href = (id === 'answer' && E.rid) ? '/expert#run=' + E.rid : '/expert';
  setPath({home: E.co ? 'q' : (E.door === 'check' ? 'door' : 'co'), progress:'ans', answer:'ans', verify:'ev', history:'door', about:''}[id] ?? ''); }
/* 지금 어디쯤 — 회사 → 질문 → 답 → 근거 */
const PATH = ['door', 'co', 'q', 'ans', 'ev'];
function setPath(stage){
  const bar = $('#path'); if (!bar) return; bar.hidden = !stage;
  const at = PATH.indexOf(stage);
  bar.querySelectorAll('li').forEach(li => { const i = PATH.indexOf(li.dataset.p); li.className = i < at ? 'done' : i === at ? 'now' : ''; });
}
const store = {get(k, d){ try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch(e){ return d; } }, set(k, v){ try { localStorage.setItem(k, JSON.stringify(v)); } catch(e){} }};

/* ---------------- 세 개의 문 (v1.4) — 사람이 아니라 하려는 일로 나눈다 ---------------- */
const DOORS = [
  {id:'ask', icon:'?', title:'궁금한 것 묻기', sub:'회사를 고르고 질문 카드를 누르면, 근거와 함께 정리해 드려요', for:'처음 오셨다면 여기부터'},
  {id:'test', icon:'≈', title:'내 생각 시험하기', sub:'내 가정을 적고 증권사·다른 사람들·실제와 나란히 비교해요', for:'나름의 생각이 있다면'},
  {id:'check', icon:'✓', title:'근거 검증하기', sub:'받은 근거 확인서를 다시 계산하거나, 답이 나온 단계를 하나씩 따라가요', for:'숫자를 직접 확인하고 싶다면'}];
function renderDoors(){
  $('#doors').innerHTML = DOORS.map(d => `<button role="tab" aria-selected="${d.id === E.door}" class="door ${d.id === E.door ? 'on' : ''}" data-d="${d.id}">
    <span class="ic" aria-hidden="true">${d.icon}</span><span class="dt">${esc(d.title)}</span><span class="ds">${esc(d.sub)}</span><span class="df">${esc(d.for)}</span></button>`).join('');
  $('#doors').querySelectorAll('.door').forEach(b => b.onclick = () => setDoor(b.dataset.d, true));
}
function setDoor(d, user){
  E.door = d; store.set('mrn_easy_door', d); renderDoors();
  $('#doorCheck').hidden = d !== 'check';
  if (d === 'check') renderRecent();
  $('#coStepH').innerHTML = d === 'check' ? '<span class="num">1</span> 또는 회사를 골라 새로 물어보고 따라가기' : '<span class="num">1</span> 회사 고르기';
  if (E.co) drawCards();
  setPath(E.co ? 'q' : (d === 'check' ? 'door' : 'co'));
  if (user && d !== 'check' && !E.co) $('#coInput').focus();
}
function renderRecent(){
  const h = store.get('mrn_easy_hist', []).slice(0, 5);
  $('#hvRecent').innerHTML = h.map(x => `<li data-r="${esc(x.rid)}"><b>${esc(x.name || '')}</b> · ${esc(x.title)} <span class="hint">(${esc(x.date)} 기준)</span></li>`).join('') || '<li class="hint">아직 본 답이 없어요. 아래에서 회사를 골라 먼저 물어보세요.</li>';
  $('#hvRecent').querySelectorAll('[data-r]').forEach(li => li.onclick = () => openAnswer(li.dataset.r, {strip:true}).catch(() => toast('이 답을 찾지 못했어요.')));
}

/* ---------------- 회사 고르기 ---------------- */
const QUICK = ['005930', '000660', '042700'];
async function loadUniverse(){
  try { E.uni = await api('/api/universe'); }
  catch(e){ E.uni = null; $('#coHint').textContent = '회사 자료(사본)를 아직 못 불러왔어요. PC에서 자료 받기 도구를 먼저 실행해 주세요.'; return; }
  const kr = E.uni.companies.filter(c => c.market === 'KR' && c.cover.price_fsc && c.cover.price_fsc.n);
  $('#coList').innerHTML = kr.map(c => `<option value="${esc(c.name)}">${esc(c.ticker)} · ${esc(c.krx_sector || '')}</option>`).join('');
  $('#coHint').textContent = `국내 ${kr.length}개 회사 중에서 고를 수 있어요. 이름 몇 글자만 적어도 돼요.`;
  const extra = kr.filter(c => !QUICK.includes(c.ticker)).sort((a, b) => (b.cover.disclosure?.n || 0) - (a.cover.disclosure?.n || 0)).slice(0, 3).map(c => c.ticker);
  $('#quick').innerHTML = [...QUICK, ...extra].map(t => { const c = info(t); return c ? `<button data-t="${t}">${esc(c.name)}</button>` : ''; }).join('');
  $('#quick').querySelectorAll('button').forEach(b => b.onclick = () => choose(b.dataset.t));
}
function info(t){ return E.uni ? E.uni.companies.find(c => c.ticker === t) : null; }
function resolve(v){
  v = (v || '').trim(); if (!v || !E.uni) return null;
  const kr = E.uni.companies.filter(c => c.market === 'KR');
  const m = v.match(/^(\d{6})/); if (m) return kr.find(c => c.ticker === m[1]) ? m[1] : null;
  const exact = kr.find(c => c.name === v); if (exact) return exact.ticker;
  const part = kr.filter(c => c.name.includes(v)); return part.length === 1 ? part[0].ticker : null;
}
async function choose(t){
  const c = info(t); if (!c) return;
  E.co = t; $('#coInput').value = c.name;
  $('#chosen').hidden = false; $('#chosen').innerHTML = `<b>${esc(c.name)}</b> <span class="hint">${esc(t)} · ${esc(c.krx_sector || c.sector_desc || '')}</span>에 대해 무엇이 궁금하세요?`;
  const r = await api('/api/easy/cards?company=' + t); E.cards = r.cards; E.groups = r.groups || [];
  drawCards(); $('#free').hidden = false; renderFreeEx(); setPath('q');
}
const KIND_CLS = {'사실':'fact', '관계':'calc', '가정':'estimate'};
const KIND_TIP = {'사실':'주로 공시·통계에 기록된 값을 보여 줘요', '관계':'함께 움직인 기록이에요 — 원인은 아니에요', '가정':'「이 가정이라면」 계산이에요 — 사실과 나눠 보여 줘요'};
function seenMap(){ const m = {}; store.get('mrn_easy_hist', []).forEach(x => { if (x.co === E.co && x.card && !m[x.card]) m[x.card] = x; }); return m; }
function drawCards(){
  const seen = seenMap(), ok = E.cards.filter(c => c.ok), n = ok.filter(c => seen[c.id]).length;
  const focus = c => (c.doors || ['ask']).includes(E.door === 'check' ? 'check' : E.door);
  const card = cd => {
    const k = cd.kind ? `<span class="b ${KIND_CLS[cd.kind] || ''}" title="${esc(KIND_TIP[cd.kind] || '')}">${esc(cd.kind)}</span>` : '';
    const sv = seen[cd.id] ? `<span class="seen" title="이 브라우저에서 본 적 있어요">✓ ${esc(seen[cd.id].at.slice(5, 10))}에 봤어요</span>` : '';
    return cd.ok
      ? `<button class="card ${E.door === 'ask' ? '' : focus(cd) ? 'focus' : 'dim'}" data-c="${cd.id}"><div class="ct">${k}${sv}</div><div class="t">${esc(cd.title)}</div><div class="s">${esc(cd.sub)}</div><div class="go">물어보기 →</div></button>`
      : `<div class="card off"><div class="ct">${k}</div><div class="t">${esc(cd.title)}</div><div class="s">${esc(cd.sub)}</div><div class="why">${esc(cd.why)}</div></div>`;
  };
  const groups = E.groups.length ? E.groups : [{id:'', title:'', sub:''}];
  const doorNote = {ask:'', test:'「내 생각 시험하기」에 맞는 질문을 진하게 보여 드려요. 가정을 적을 수 있는 곳은 「증권사들은 실적을 어떻게 보나?」예요.', check:'답을 받은 뒤 「작동 원리」와 「근거 확인서」로 단계마다 따라갈 수 있어요.'}[E.door] || '';
  $('#meter').hidden = !ok.length;
  $('#meter').innerHTML = `<div class="mbar"><i style="width:${ok.length ? Math.round(n / ok.length * 100) : 0}%"></i></div><span>이 회사 질문 ${ok.length}개 중 <b>${n}개</b>를 살펴봤어요${n && n < ok.length ? ' — 다른 질문으로 그림을 넓혀 보세요' : n === ok.length && n ? ' — 모두 봤어요! 「그때는 어땠나?」로 날짜를 바꿔 보세요' : ''}</span>`;
  $('#cards').innerHTML = `<h2 class="step-h"><span class="num">2</span> 질문 고르기</h2>${doorNote ? `<p class="hint">${esc(doorNote)}</p>` : ''}` + groups.map(g => {
    const cs = E.cards.filter(c => !g.id || c.group === g.id).sort((a, b) => (b.ok - a.ok) || (focus(b) - focus(a)));
    return cs.length ? `<section class="grp"><div class="gh"><b>${esc(g.title)}</b> <span class="hint">${esc(g.sub)}</span></div><div class="gcards">${cs.map(card).join('')}</div></section>` : '';
  }).join('');
  $('#cards').querySelectorAll('button.card').forEach(b => b.onclick = () => ask(b.dataset.c));
}
function cutoff(){ const d = $('#cutDate').value; return d ? `${d}T16:00:00+09:00` : ''; }

/* ---------------- 질문 → 진행 ---------------- */
const STEP = {T01:'공식 원문 확인', T02:'사업보고서에서 문장 찾기', T05:'답 정리', T06:'주가 자료 불러오기', T07:'매매 주체별 자료 불러오기',
  T08:'공시·뉴스 모으기', T09:'비교 회사 자료 불러오기', T10:'환율·금리·수출 자료 불러오기', T11:'사업보고서 재무 불러오기', T12:'지분 공시 불러오기'};
const ST = {waiting:['기다림',''], running:['하는 중','run'], succeeded:['완료','ok'], partial:['일부 확인','ok'], held:['보류','bad'], failed:['실패','bad'], blocked:['건너뜀','bad'], not_connected:['준비 중','bad'], cancelled:['취소','bad']};
async function ask(card, cut, title){
  if (card === 'reaction') return openReaction();   // v0.25 공시 반응 사전 — 이 화면이 직접 답함
  if (card === 'attention') return openAttention();   // v0.27 관심 체온계 — 이 화면이 직접 답함
  const cd = E.cards.find(c => c.id === card);
  E.ctx = {card, title: cd ? cd.title : (title || ''), company: E.co, cutoff: cut ?? cutoff()};
  try {
    const r = await api('/api/easy/run', {method:'POST', body:{card, company:E.co, cutoff:E.ctx.cutoff}});
    follow(r.id);
  } catch(e){ toast(e.message); }
}
function follow(rid){
  E.rid = rid; show('progress'); $('#pTitle').textContent = `${info(E.co)?.name || ''} — ${E.ctx.title || '조사'} 자료를 모으는 중…`;
  clearInterval(E.poll);
  const tick = async () => {
    const run = await api('/api/runs/' + rid);
    const ph = t => t === 'T05' ? ['정리', 'p-check'] : t === 'T02' ? ['원문 검색', 'p-find'] : t.startsWith('T') ? ['자료 찾기', 'p-find'] : ['계산', 'p-calc'];
    const cur = run.nodes.find(n => ['running', 'waiting'].includes(n.status));
    const curPh = cur ? ph(cur.node_type)[0] : '정리';
    $('#pPhase').innerHTML = ['질문 이해', '자료 찾기', '계산', '정리'].map((x, i, arr) => { const at = arr.indexOf(curPh === '원문 검색' ? '자료 찾기' : curPh);
      return `<span class="${i < at ? 'done' : i === at ? 'now' : ''}">${x}</span>`; }).join('<i>›</i>');
    $('#pSteps').innerHTML = run.nodes.map(n => { const s = ST[n.status] || [n.status, '']; const nm = STEP[n.node_type] || ((E.names || {})[n.node_type] || '계산') ; const p = ph(n.node_type);
      return `<li><span class="st ${s[1]}">${s[0]}</span> <span class="ph ${p[1]}">${p[0]}</span> ${esc(nm)}</li>`; }).join('');
    if (!['waiting', 'queued', 'running'].includes(run.status)){ clearInterval(E.poll); await openAnswer(rid); }
  };
  E.poll = setInterval(() => tick().catch(() => {}), 500); tick().catch(() => {});
}

/* ---------------- 답 카드 ---------------- */
function badge(tier, label){ return `<span class="b ${tier}">${esc(label)}</span>`; }

/* v0.28.2: 기준 시각을 한국 시각으로 — 장중이면 「그날 장은 아직 반영 안 됨」, 가격·수급 자료의 마지막 거래일 함께 */
function asofText(a){
  const cut = String(a.cutoff || '');
  let s;
  if (cut.length <= 10) s = `${cut} 장 마감까지 공개된 자료 기준`;
  else { const c = new Date(cut); if (isNaN(c)) s = `${cut.slice(0, 10)} 기준`;
    else { const k = new Date(c.getTime() + 9 * 3600e3).toISOString(), ds = k.slice(0, 10), hm = k.slice(11, 16);
      s = hm < '15:30' ? `${ds} ${hm}(한국 시각)까지 공개된 자료 기준 — 그날 장은 아직 반영 안 됨` : `${ds} 장 마감까지 공개된 자료 기준`; } }
  const t = a.data_through || {}, v = [...new Set(Object.values(t))];
  if (v.length === 1) s += ` · ${Object.keys(t).join('·')} 자료 마지막 거래일 ${v[0]}`;
  else if (v.length > 1) s += ' · ' + Object.entries(t).map(([x, d]) => `${x} 자료 마지막 거래일 ${d}`).join(', ');
  return s;
}
async function openAnswer(rid, opt={}){
  if (String(rid).startsWith('rx:')) { E.co = String(rid).slice(3); return openReaction(); }   // v0.25 최근 본 답에서 다시 열기
  if (String(rid).startsWith('at:')) { E.co = String(rid).slice(3); return openAttention(); }   // v0.27
  const a = await api('/api/easy/answer/' + rid); E.ans = a; E.rid = rid; remember(a);
  if (a.company && a.company !== E.co && info(a.company)) { E.co = a.company; $('#coInput').value = info(a.company).name; api('/api/easy/cards?company=' + a.company).then(r => { E.cards = r.cards; E.groups = r.groups || []; drawCards(); $('#chosen').hidden = false; $('#chosen').innerHTML = `<b>${esc(info(a.company).name)}</b> <span class="hint">${esc(a.company)}</span>에 대해 무엇이 궁금하세요?`; $('#free').hidden = false; renderFreeEx(); }).catch(() => {}); }
  const date = (a.cutoff || '').slice(0, 10);
  const q = a.card_title || (E.ctx && E.ctx.question) || '직접 한 질문';
  $('#answer').innerHTML = `<div class="ans">
    <div class="q">${esc(a.name || '')} · ${esc(q)} · <b>${esc(asofText(a))}</b></div>
    <div class="head">${esc(headline(a))}</div>
    <div class="counts">${badge('fact', '자료로 확인 ' + a.count.fact)} ${badge('calc', '계산한 값 ' + a.count.calc)} ${badge('estimate', '추정·가정 ' + a.count.estimate)} ${badge('unk', '아직 모르는 것 ' + a.unknown.length)}</div>
    ${a.process ? stripHtml(a.process, opt.strip) : ''}
    ${a.relmap ? relmapHtml(a.relmap) : ''}${a.forecast ? '<section class="fc" id="fc"></section>' : ''}${a.edi ? ediHtml(a.edi) : ''}
    <ul class="key"${a.relmap || a.forecast ? ' hidden' : ''}>${a.key.map((it, i) => line(it, 'k' + i)).join('') || '<li><span></span><span class="tx">보여 드릴 숫자가 없어요. 아래 「아직 모르는 것」을 확인해 주세요.</span></li>'}</ul>
    ${visHtml(a)}
    <div class="box not"><b>이 결과가 아닌 것</b><ul><li>${esc(a.not_this)}</li>${a.notices.map(n => `<li>${esc(n)}</li>`).join('')}${a.limits.map(n => `<li>${esc(n)}</li>`).join('')}</ul></div>
    ${a.unknown.length ? `<div class="box unk"><b>아직 모르는 것</b><ul>${a.unknown.map(u => `<li>${esc(u.text)}</li>`).join('')}</ul></div>` : ''}
    <div id="fix"></div>
    ${a.repairs.length ? `<div class="box fixed"><b>이 답은 막힌 곳을 고쳐서 다시 조사한 결과예요</b><ul>${a.repairs.map(r => `<li>${esc(r.problem)} → ${esc(r.fix)}${r.downgrade ? ` <span class="b estimate">근거 수준 낮아짐: ${esc(r.downgrade)}</span>` : ''}</li>`).join('')}</ul>
      ${a.repaired_from ? `<button class="ghost" id="aOrig">고치기 전 답 보기</button>` : ''}</div>` : ''}
    <details class="all"><summary>숫자 ${a.items.length}개 모두 보기</summary><ul class="key">${a.items.map((it, i) => line(it, 'a' + i)).join('')}</ul></details>
    ${a.tables.length ? `<details class="all"><summary>자세한 표 ${a.tables.length}개</summary>${a.tables.map(tableHtml).join('')}</details>` : ''}
    ${nextHtml(a)}
    ${expertHtml(a, rid)}
    <div class="acts">
      <button id="aReceipt" title="이 답을 만든 단계·기준 날짜·결과 지문을 담은 파일. 누구나 같은 결과가 나오는지 다시 계산해 볼 수 있어요">근거 확인서 내려받기</button>
      <button id="aPrint" class="ghost">인쇄·PDF로 저장</button>
      ${a.card === 'filing' ? '' : '<button id="aThen" class="ghost">그때는 어땠나? (날짜 바꿔 비교)</button>'}
      <button id="aHome" class="ghost">다른 질문</button>
    </div>
    <p class="hint" id="aRid">답 번호 ${esc(rid.slice(0, 8))} · ${esc(UI_VERSION)}</p>
  </div><div id="tm"></div>`;
  const all = {}; a.key.forEach((it, i) => all['k' + i] = it); a.items.forEach((it, i) => all['a' + i] = it);
  $('#answer').querySelectorAll('[data-i]').forEach(li => li.onclick = () => drawer(all[li.dataset.i]));
  $('#answer').querySelectorAll('a[data-u]').forEach(x => x.onclick = ev => ev.stopPropagation());
  if ($('#aOrig')) $('#aOrig').onclick = () => openAnswer(a.repaired_from);
  loadFixes(rid);
  if (a.forecast) renderForecast(a, Object.keys(a.forecast.trends)[0]);
  bindVis();
  if (a.edi) bindEdi(a);
  $('#aReceipt').onclick = downloadReceipt; $('#aPrint').onclick = () => window.print(); if ($('#aThen')) $('#aThen').onclick = timeMachine; $('#aHome').onclick = () => show('home');
  bindStrip(); bindNext(a);
  show('answer');
}
/* ---------------- 작동 원리 띠 (v1.4) — 기술 이름은 배지가 아니라 「일한 장면」으로 ---------------- */
function stripHtml(P, open){
  const st = P.steps;
  return `<section class="strip" aria-label="이 답의 작동 원리">
    <div class="sh"><b>작동 원리</b> <span class="hint">이 답이 만들어진 다섯 단계 — 눌러서 무엇을 했는지 보세요</span></div>
    <ol class="sflow">${st.map((x, i) => `<li><button class="sstep ${x.state}" data-s="${i}" aria-expanded="false"><span class="sn">${i + 1}</span><span class="stt">${esc(x.title)}</span><span class="stech">${esc(x.tech_name)}</span></button></li>`).join('')}</ol>
    <div class="sdetail" id="sDetail" hidden></div>
    <p class="ainote"><span class="b unk">AI 모델 ${P.model_calls}회</span> ${esc(P.ai_note.replace(/^AI 모델 호출 \d+회 — /, ''))}</p>
  </section>`;
}
function bindStrip(){
  const P = E.ans && E.ans.process; if (!P) return;
  const btns = [...document.querySelectorAll('.sstep')];
  const open = i => {
    btns.forEach((b, j) => { b.classList.toggle('open', j === i); b.setAttribute('aria-expanded', j === i); });
    const x = P.steps[i];
    $('#sDetail').hidden = false;
    $('#sDetail').innerHTML = `<p><b>${i + 1}. ${esc(x.title)}</b> — ${esc(x.text)}</p>
      <p class="hint"><b>쓴 기술:</b> ${esc(x.tech)}</p>
      <p class="hint"><b>이 단계에서 볼 수 있는 특징:</b> ${x.attrs.map(t => `<span class="attr">${esc(AB_KEY[t] || t)}</span>`).join(' ')} <a href="#" class="toAbout">10가지 특징 모두 보기</a></p>`;
    $('#sDetail').querySelector('.toAbout').onclick = ev => { ev.preventDefault(); openAbout(); };
  };
  btns.forEach((b, i) => b.onclick = () => b.classList.contains('open') ? (b.classList.remove('open'), $('#sDetail').hidden = true) : open(i));
}
/* ---------------- 전문가 모드 귀띔 (v1.4.1) — 넘어가기 전에 무엇을 더 알 수 있는지 ---------------- */
function expertHtml(a, rid){
  const X = a.expert; if (!X) return '';
  const stuck = X.stuck ? `<li class="xs">막힌 단계 ${X.stuck}개를 직접 열어 이유를 보고, 설정을 바꿔 다시 실행</li>` : '';
  return `<section class="xhint"><div class="xh"><span class="xd">◆</span><b>전문가 모드에서 더 알 수 있는 것</b> <span class="hint">— 이 답을 그대로 열어요. 읽기만 할 거라면 여기서 충분해요</span></div>
    <ul>${stuck}${X.hints.map(h => `<li>${esc(h)}</li>`).join('')}</ul>
    <a class="xgo" href="/expert#run=${esc(rid)}">이 답을 전문가 모드로 열기 →</a></section>`;
}
/* ---------------- 다음 걸음 (v1.4) — 답에서 끝나지 않고 이어지게 ---------------- */
const NEXT_WHY = {earnings:'공시된 실적 숫자부터 확인', forecasts:'증권사·모두·실제의 전망 비교', edi:'주가가 실적보다 얼마나 앞서 있는지', macro:'환율·금리 「이 가정이라면」', relations:'함께 움직인 기록', price:'주가 흐름과 매매 주체', events:'최근 공시·뉴스', holders:'대주주와 지분 변화', nowcast:'이번 분기 매출 조기 가늠'};
function nextHtml(a){
  const nx = (a.next || []).filter(x => { const c = E.cards.find(y => y.id === x.id); return !c || c.ok; });
  const seen = seenMap();
  const doIt = [];
  if (a.forecast) doIt.push(`<button class="nx mine" data-act="crowd"><b>내 가정 적어 보기</b><span>위 그림에 내 생각을 올려 증권사·모두·실제와 비교</span></button>`);
  doIt.push(`<button class="nx" data-act="verify"><b>이 답 검증하기</b><span>근거 확인서를 받아 누구나 다시 계산</span></button>`);
  return `<section class="next"><div class="nh"><b>다음 걸음</b> <span class="hint">이 답과 이어서 보면 좋은 것</span></div>
    <div class="nxs">${nx.map(x => `<button class="nx" data-card="${esc(x.id)}" data-title="${esc(x.title)}"><b>${esc(x.title)}</b><span>${esc(NEXT_WHY[x.id] || '')}${seen[x.id] ? ' · 본 적 있음' : ''}</span></button>`).join('')}${doIt.join('')}</div></section>`;
}
function bindNext(a){
  document.querySelectorAll('.next [data-card]').forEach(b => b.onclick = () => { E.co = a.company || E.co; ask(b.dataset.card, cutoff(), b.dataset.title); });
  document.querySelectorAll('.next [data-act]').forEach(b => b.onclick = () => {
    const k = b.dataset.act;
    if (k === 'crowd'){ const el = $('#cVal') || $('.crowdbox'); if (el){ el.scrollIntoView({behavior:'smooth', block:'center'}); if (el.focus) el.focus(); } }
    else if (k === 'verify'){ downloadReceipt().then(() => { show('verify'); }); }
    else if (k === 'then'){ timeMachine(); $('#tm').scrollIntoView({behavior:'smooth'}); }
  });
}
const GRADE_CLS = {lead:'g-lead', same_month:'g-same', lead_weak:'g-weak', unstable:'g-weak', indistinct:'g-none', too_few:'g-none'};
function relmapHtml(m){
  // 관계 지도 — 「함께 움직인 기록」만. 숫자가 커도 원인·앞으로의 방향을 뜻하지 않는다.
  const f = v => v == null ? '-' : (v > 0 ? '+' : '') + v.toFixed(2);
  const pos = v => ((Math.max(-1, Math.min(1, v)) + 1) * 50).toFixed(1);
  const rows = m.rows.map(r => {
    if (r.grade === 'too_few') return `<li class="rel g-none"><div class="rn">${esc(r.name)}</div><div class="rg">${esc(r.grade_label)}</div></li>`;
    const ci = r.ci || [r.r, r.r];
    const lag = r.lag === 0 ? '같은 달' : `${r.lag}개월 앞선 변화`;
    const oos = r.oos ? `과거 맞히기 ${Math.round(r.oos.hit * 100)}% (늘 많던 방향 ${Math.round(r.oos.baseline * 100)}%)` : (r.known_before ? '과거 맞히기: 시험할 달이 부족해요' : '같은 달 기록이라 맞히기 시험 대상이 아니에요');
    return `<li class="rel ${GRADE_CLS[r.grade] || ''}">
      <div class="rn">${esc(r.name)} <span class="mute">(${esc(lag)})</span></div>
      <div class="bar" title="왼쪽 끝 −1(반대로 움직임) · 가운데 0(관계 없음) · 오른쪽 끝 +1(같이 움직임)"><i class="mid"></i><i class="band" style="left:${pos(ci[0])}%;width:${(pos(ci[1]) - pos(ci[0])).toFixed(1)}%"></i><i class="dot" style="left:${pos(r.r)}%"></i></div>
      <div class="rg"><b>${esc(r.grade_label)}</b> · 상관 ${f(r.r)} (범위 ${f(ci[0])}~${f(ci[1])}, ${r.n}개월)</div>
      <div class="rs mute">앞 절반 ${f(r.halves && r.halves.first)} · 뒤 절반 ${f(r.halves && r.halves.second)} · ${esc(oos)}</div></li>`;
  }).join('');
  return `<section class="relmap"><div class="relhead"><b>관계 지도</b> — 함께 움직인 기록 ${m.months ? `(${esc(m.months.from)}~${esc(m.months.to)}, ${m.months.n}개월)` : ''}</div>
    <p class="relwarn">${esc(m.notice || '')}</p>
    <ul class="rels">${rows}</ul>
    <details class="relhow"><summary>이 화면을 읽는 법</summary><ul>
      <li>막대 가운데가 0(관계 없음), 오른쪽 끝은 「같이 움직임」, 왼쪽 끝은 「반대로 움직임」이에요. 진한 점이 잰 값, 옅은 띠가 그럴 법한 범위예요.</li>
      <li>띠가 가운데 선을 걸치면 「관계 없음과 구분되지 않음」이에요. 시차를 여러 개 시험한 만큼 띠를 넓게 잡았어요.</li>
      <li>앞 절반과 뒤 절반 기간에서 방향이 다르면 「기간마다 달라짐」이에요.</li>
      <li>「앞서 움직인 기록」은 그때 미리 알 수 있었던 값만 써서, 앞 기간으로 정한 방향이 뒤 기간을 늘 많던 방향보다 10%p 이상 더 맞혔을 때만 붙여요.</li>
      <li>최소 24개월이 안 되면 재지 않아요. 수정주가가 아닌 월말 종가를 썼어요.</li></ul></details></section>`;
}
/* ---------------- 증권사 전망 추이 · 모두의 가정 · 실제 (v0.18) ---------------- */
const joS = v => v == null ? '-' : Math.abs(Number(v)) < 1e6 ? (Number(v) / 100).toLocaleString('ko-KR', {maximumFractionDigits: 0}) + '억' : (Number(v) / 1e6).toLocaleString('ko-KR', {maximumFractionDigits: 1}) + '조';   // v0.24: 1조 미만은 억
async function renderForecast(a, key){
  const F = a.forecast, tr = F.trends[key], [fy, metric] = key.split(':');
  let crowd = null; try { crowd = await api(`/api/crowd/${a.company}/${fy}/${metric}`); } catch(e){}
  const act = (F.versus_actual || []).find(v => v.key === key);
  const S = tr.series, W = 660, H = 230, L = 58, R = 140, T = 14, B = 30;
  const vals = S.flatMap(p => [+p.min, +p.max]).concat(Object.values(tr.per_broker).flat().map(p => +p.value));
  if (crowd && crowd.stats && crowd.stats.shown) vals.push(+crowd.stats.q1, +crowd.stats.q3);
  if (act) vals.push(+act.actual);
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo) * 0.12 || hi * 0.05; lo -= pad; hi += pad;
  const t0 = +new Date(S[0].date), t1 = Math.max(+new Date(S[S.length - 1].date), t0 + 864e5 * 7);
  const x = d => L + (W - L - R) * ((+new Date(d)) - t0) / (t1 - t0), y = v => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
  const band = S.map(p => `${x(p.date)},${y(+p.max)}`).join(' ') + ' ' + S.slice().reverse().map(p => `${x(p.date)},${y(+p.min)}`).join(' ');
  const line = S.map(p => `${x(p.date)},${y(+p.median)}`).join(' ');
  const dots = Object.entries(tr.per_broker).flatMap(([b, ps]) => ps.map(p => `<circle cx="${x(p.date)}" cy="${y(+p.value)}" r="3" class="bdot"><title>${esc(b)} ${esc(p.date)} ${joS(p.value)}</title></circle>`)).join('');
  const ticks = [lo + (hi - lo) * 0.1, (lo + hi) / 2, hi - (hi - lo) * 0.1].map(v => `<text x="${L - 6}" y="${y(v) + 4}" text-anchor="end" class="ax">${joS(v)}</text><line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" class="grid"/>`).join('');
  const xr = W - R + 44;
  const cs = crowd && crowd.stats && crowd.stats.shown ? `<rect x="${xr - 12}" width="24" y="${y(+crowd.stats.q3)}" height="${Math.max(2, y(+crowd.stats.q1) - y(+crowd.stats.q3))}" class="crowd"/><line x1="${xr - 14}" x2="${xr + 14}" y1="${y(+crowd.stats.median)}" y2="${y(+crowd.stats.median)}" class="crowdm"/><text x="${xr}" y="${H - 8}" text-anchor="middle" class="ax">모두(${crowd.stats.n}명)</text>` : '';
  const mine = crowd && crowd.mine ? `<circle cx="${xr}" cy="${y(+crowd.mine.value_mn)}" r="5" class="mine"><title>내 가정 ${joS(crowd.mine.value_mn)}</title></circle>` : '';
  const ac = act ? `<path d="M${W - R + 98} ${y(+act.actual)} l7 -7 l7 7 l-7 7z" class="actual"/><text x="${W - R + 105}" y="${H - 8}" text-anchor="middle" class="ax">실제</text>` : `<text x="${W - R + 105}" y="${y((lo + hi) / 2)}" text-anchor="middle" class="ax">실제</text><text x="${W - R + 105}" y="${y((lo + hi) / 2) + 14}" text-anchor="middle" class="ax">공시 전</text>`;
  const last = tr.latest, rv = tr.revisions;
  const lockForm = crowd && !crowd.unlocked ? `<div class="crowdbox"><b>모두의 가정 — 먼저 내 생각을 적어 주세요</b>
      <p class="hint">${esc(crowd.rule)} 지금까지 ${crowd.n}명이 적었어요.</p>
      <div class="row">${esc(fy)}년 ${esc(tr.metric_label)}을(를) 나는 <input id="cVal" type="number" step="0.1" inputmode="decimal" placeholder="예: 380"> 조 원으로 가정해요 <button id="cSave">저장하고 다른 사람들 보기</button></div>
      <p class="hint">매수·매도나 목표주가는 받지 않아요. 실적 가정만 모아요. 같은 달 안에 다시 적으면 바뀌어요.</p></div>`
    : crowd ? `<div class="crowdbox"><b>모두의 가정</b> — 내 가정 <b>${joS(crowd.mine.value_mn)}</b> (${esc(crowd.mine.period)}) <button class="ghost" id="cEdit">다시 적기</button>
      <p>${crowd.stats.shown ? `${crowd.stats.n}명의 가정: 중앙값 <b>${joS(crowd.stats.median)}</b>, 가운데 절반 ${joS(crowd.stats.q1)}~${joS(crowd.stats.q3)}` : `지금 ${crowd.stats.n}명 — ${crowd.stats.min_n}명 이상 모이면 분포를 보여 드려요.`}</p>
      <p class="hint">다른 사람들의 가정은 거울이지 정답이 아니에요. 판단은 스스로 하세요.</p></div>` : '';
  $('#fc').innerHTML = `<div class="relhead"><b>증권사 · 모두 · 실제</b> — 실적 전망을 세 갈래로 나란히</div>
    <p class="relwarn">${esc(F.notice)}</p>
    <div class="tabs fct">${Object.keys(F.trends).map(k => { const [y2, m2] = k.split(':'); return `<button data-fk="${esc(k)}" class="${k === key ? 'on' : ''}">${esc(y2)}년 ${esc(F.trends[k].metric_label)}</button>`; }).join('')}</div>
    <svg viewBox="0 0 ${W} ${H}" class="fchart" role="img" aria-label="증권사 전망 집계 추이">
      ${ticks}<polygon points="${band}" class="band"/><polyline points="${line}" class="med"/>${dots}
      <line x1="${W - R + 8}" x2="${W - R + 8}" y1="${T}" y2="${H - B}" class="sep"/>${cs}${mine}${ac}
      <text x="${L}" y="${H - 8}" class="ax">${esc(S[0].date)}</text><text x="${W - R - 4}" y="${H - 8}" text-anchor="end" class="ax">${esc(S[S.length - 1].date)}</text></svg>
    <p class="legend"><span class="lg med"></span> 증권사 집계 중앙값 <span class="lg band"></span> 최저~최고 <span class="lg bdot"></span> 보고서 하나 <span class="lg crowd"></span> 모두의 가정(가운데 절반) <span class="lg mine"></span> 내 가정 <span class="lg actual"></span> 실제</p>
    <p><b>${esc(fy)}년 ${esc(tr.metric_label)}</b>: 증권사 ${last.n}곳 최신 집계 중앙값 <b>${joS(last.median)}</b> (범위 ${joS(last.min)}~${joS(last.max)}, ${esc(last.date)}). ${esc(tr.first.date)} 이후 같은 증권사가 고친 횟수: 상향 ${rv.up.length} · 하향 ${rv.down.length} · 유지 ${rv.flat.length}.
      ${last.thin ? `<span class="b estimate">보고서 ${tr.min_reports}건 미만 — 추이로 보지 마세요</span>` : ''}</p>
    ${act ? `<p><b>실제</b> ${joS(act.actual)} (공시 ${esc(act.disclosed)}) — 공시 전날까지 집계 중앙값과 ${esc(act.gap_pct)}% 차이${act.inside_range ? ', 집계 범위 안' : ', 집계 범위 밖'}.</p>` : `<p class="hint">실제 실적은 사업보고서가 공시되면 자동으로 이 그림에 들어와요.</p>`}
    ${quarterHtml(F.quarters)}
    ${lockForm}`;
  $('#fc').querySelectorAll('[data-fk]').forEach(b => b.onclick = () => renderForecast(a, b.dataset.fk));
  if ($('#cSave')) $('#cSave').onclick = async () => {
    const v = parseFloat($('#cVal').value); if (!isFinite(v)){ toast('조 원 단위 숫자를 적어 주세요.'); return; }
    try { await api('/api/crowd/submit', {method:'POST', body:{ticker:a.company, fiscal_year:+fy, metric, value_jo:v}}); toast('저장했어요. 이제 다른 사람들의 가정을 볼 수 있어요.'); renderForecast(a, key); }
    catch(e){ toast(e.message); } };
  if ($('#cEdit')) $('#cEdit').onclick = () => { const v = prompt('새 가정 (조 원)', (crowd.mine.value_mn / 1e6).toFixed(1)); if (v == null) return;
    api('/api/crowd/submit', {method:'POST', body:{ticker:a.company, fiscal_year:+fy, metric, value_jo:parseFloat(v)}}).then(() => renderForecast(a, key)).catch(e => toast(e.message)); };
}
/* v0.24 분기 전망 성적표 — 실적이 알려지기 전 마지막 전망 vs 실제 (지난 기록) */
function quarterHtml(Q){
  if (!Q || !Q.periods || !Q.periods.length) return '';
  const lab = {revenue:'매출액', operatingProfit:'영업이익'};
  const ps = Q.periods.filter(p => p.status === 'scored').concat(Q.periods.filter(p => p.status !== 'scored').slice(0, 4));
  return `<details class="qsc" open><summary><b>분기 전망 성적표</b> <span class="hint">— 증권사마다 실적이 알려지기 전에 낸 마지막 분기 전망 vs 실제</span></summary>
    <div class="tw"><table><tr><th>분기</th><th>항목</th><th>증권사</th><th>마지막 전망 중앙값</th><th>실제</th><th>오차(절댓값 중앙값)</th></tr>
    ${ps.map(p => `<tr><td>${esc(p.period.replace('Q', '년 ') + '분기')}</td><td>${esc(lab[p.metric] || p.metric)}</td><td>${p.n}곳</td><td>${joS(p.median_forecast_mn)}</td>
      <td>${p.status === 'scored' ? joS(p.actual_mn) : '<span class="b unk">공시 전</span>'}</td><td>${p.status === 'scored' ? `${p.median_abs_error_pct}% <span class="hint">(5% 안 ${p.within5}곳)</span>` : '실제가 공시되면 자동 채점'}</td></tr>`).join('')}</table></div>
    <p class="hint">${esc(Q.notice)} 실적이 처음 알려진 날(잠정실적 공시·정기보고서 중 이른 날) 이후의 보고서는 채점에서 뺐어요.</p></details>`;
}
function headline(a){
  // 첫 문장은 결론이 아니라 정리 — 무엇을 확인했고 무엇을 모르는지
  const n = a.count.fact + a.count.calc + a.count.estimate;
  if (!n) return '이 질문에 답할 자료를 찾지 못했어요.';
  const parts = [];
  if (a.count.fact) parts.push(`자료로 확인한 사실 ${a.count.fact}건`);
  if (a.count.calc) parts.push(`그 자료로 계산한 값 ${a.count.calc}건`);
  if (a.count.estimate) parts.push(`추정 ${a.count.estimate}건`);
  return parts.join(', ') + '을 찾았어요.' + (a.unknown.length ? ` 아직 모르는 것도 ${a.unknown.length}건 있어요.` : '');
}
function line(it, key){
  return `<li data-i="${key}"><span>${badge(it.tier, it.tier_label)}</span><div><div class="lb">${esc(it.label)}</div>${pretty(it.text)}<span class="more">근거 ›</span></div></li>`;
}
function tableHtml(t){
  const cell = v => v && typeof v === 'object' && v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener" data-u="1">${esc(v.text || '링크')}</a>` : esc(v ?? '');
  return `<h3>${esc(t.title)}</h3><div class="tw"><table><tr>${t.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${t.rows.map(r => `<tr>${r.map(v => `<td class="${numCell(v)}">${cell(v)}</td>`).join('')}</tr>`).join('')}</table></div>${t.hint ? `<p class="hint">${esc(t.hint)}</p>` : ''}`;
}
const KIND_HELP = {fact:'공시·통계·시세처럼 기록된 자료에서 그대로 가져온 값이에요.', calc:'확인된 자료로 정해진 식이나 규칙에 따라 계산한 값이에요. 식은 아래에 있어요.', estimate:'과거 관계가 유지된다는 가정 등으로 계산한 추정이에요. 실제 공시가 나오면 그 값이 우선이에요.'};
function drawer(it){
  if (!it) return;
  const a = E.ans;
  const src = it.source ? `<dt>원문</dt><dd>${it.source.url ? `<a href="${esc(it.source.url)}" target="_blank" rel="noopener">${esc(it.source.title || '원문 열기')}</a>` : esc(it.source.title || '')}${it.source.status === 'api_reported' ? ' <span class="hint">(공시 API 값, 원문 표와 직접 대조 전)</span>' : ''}</dd>` : '';
  $('#dBody').innerHTML = `<h3>${esc(it.label)}</h3>${pretty(it.text)}
    <p>${badge(it.tier, it.tier_label)} <span class="hint">${esc(KIND_HELP[it.tier])}</span></p>
    <dl><dt>값의 종류</dt><dd>${esc(it.kind_label)}</dd>
      ${it.formula ? `<dt>계산 방법</dt><dd>${esc(it.formula)}</dd>` : ''}
      <dt>계산한 단계</dt><dd>${esc(it.node_name)}</dd>${src}
      <dt>기준 날짜</dt><dd>${esc((a.cutoff || '').slice(0, 10))} 장 마감까지 공개된 자료만</dd></dl>
    ${a.sources.length ? `<h3>출처근거</h3><p class="hint">이 답에 쓴 자료가 언제·어디서·어떻게 왔는지와 그 자료의 지문(해시)이에요.</p><dl>${a.sources.map(s => `<dt>${esc(grade(s.grade))}</dt><dd>${esc(s.what || '')}${(s.detail || []).map(x => `<br><span class="hint">${esc(x)}</span>`).join('')}${s.url ? `<br><a href="${esc(s.url)}" target="_blank" rel="noopener">DART 원문 열기</a>` : ''}${s.use ? `<br><span class="hint">이용 범위: ${esc(s.use)}</span>` : ''}<br><span class="mono">${s.snapshot ? esc(s.snapshot) + ' · ' : ''}${esc((s.sha256 || '').slice(0, 16))}…</span></dd>`).join('')}</dl>
      <p class="hint">지문(해시)은 자료 파일이 한 글자라도 바뀌면 달라져요. 같은 지문이면 같은 자료예요.</p>${(a.source_notes || []).map(x => `<p class="hint">${esc(x)}</p>`).join('')}` : ''}
    <p><a class="ghost" href="/expert#run=${esc(E.rid)}">이 계산 단계를 그림으로 보기</a></p>`;
  $('#drawer').hidden = false;
}

/* ---------------- 스스로 고치는 근거 사슬 ---------------- */
async function loadFixes(rid){
  let r; try { r = await api('/api/easy/repairs/' + rid); } catch(e){ return; }
  if (!r.proposals.length || E.rid !== rid) return;
  $('#fix').innerHTML = `<div class="box fix"><b>이렇게 하면 알 수 있어요</b>
    <p class="hint">막힌 곳마다 다른 방법을 찾았어요. 고른 것만 바꿔서 다시 조사하고, 지금 답은 그대로 남아요.</p>
    <ul class="fixes">${r.proposals.map(p => `<li><label><input type="checkbox" data-p="${esc(p.id)}" checked>
      <span><b>${esc(p.problem)}</b><br>${esc(p.fix)}${p.downgrade ? `<br><span class="b estimate">근거 수준 낮아짐</span> <span class="hint">${esc(p.downgrade)}</span>` : ''}</span></label></li>`).join('')}</ul>
    <button id="fixGo">고른 방법으로 다시 조사</button></div>`;
  $('#fixGo').onclick = async () => {
    const ids = [...document.querySelectorAll('#fix input[data-p]:checked')].map(x => x.dataset.p);
    if (!ids.length){ toast('하나 이상 골라 주세요.'); return; }
    try { const x = await api('/api/easy/repair', {method:'POST', body:{run_id: rid, ids}}); E.ctx = E.ctx || {}; follow(x.id); }
    catch(e){ toast(e.message); }
  };
}

/* ---------------- C2 근거 확인서 ---------------- */
function grade(g){
  g = String(g || ''); const k = g.split(':')[0];
  return ({official:'공식 자료', public:'공공 자료', portal:'포털 수집', rule_derived:'규칙으로 계산', unofficial:'비공식(참고)', derived:'계산', registered:'등록 정보'})[k] || '자료';
}
async function downloadReceipt(){
  try {
    const rc = await api('/api/easy/receipt/' + E.rid);
    const blob = new Blob([JSON.stringify(rc, null, 1)], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = `근거확인서_${(E.ans.name || '').replace(/\s/g, '')}_${rc.receipt_id.slice(0, 8)}.json`; a.click(); URL.revokeObjectURL(a.href);
    $('#aRid').textContent = `답 번호 ${E.rid.slice(0, 8)} · 확인 번호 ${rc.receipt_id.slice(0, 16)} · ${UI_VERSION}`;
    toast('근거 확인서를 내려받았어요. 누구나 「근거검증」으로 같은 결과가 나오는지 확인할 수 있어요.');
  } catch(e){ toast(e.message); }
}
async function verifyFile(f){
  $('#vOut').innerHTML = '<p>같은 근거로 다시 계산하는 중…</p>';
  try {
    const rc = JSON.parse(await f.text());
    const r = await api('/api/easy/verify', {method:'POST', body:{receipt: rc}});
    $('#vOut').innerHTML = `<h3 class="${r.ok ? 'ok' : 'ng'}">${esc(r.reason)}</h3>
      ${r.rows.length ? `<p>${r.matched} / ${r.total} 단계 일치 · 기준 날짜 ${esc((rc.cutoff || '').slice(0, 10))}</p><table><tr><th>단계</th><th>그때 지문</th><th>지금 지문</th><th></th></tr>${r.rows.map(x => `<tr><td>${esc(x.name)}</td><td class="mono">${esc((x.then || '-').slice(0, 12))}</td><td class="mono">${esc((x.now || '-').slice(0, 12))}</td><td class="${x.match ? 'ok' : 'ng'}">${x.match ? '같음' : '다름'}</td></tr>`).join('')}</table>` : ''}`;
  } catch(e){ $('#vOut').innerHTML = `<p class="ng">${esc(e.message)}</p>`; }
}

/* ---------------- C1 그때 vs 지금 ---------------- */
function timeMachine(){
  const a = E.ans, now = (a.cutoff || '').slice(0, 10);
  $('#tm').innerHTML = `<div class="tm"><h3>그때는 어땠나?</h3><p>같은 질문을 예전 날짜 기준으로 다시 물어, 그날 알 수 있었던 것과 지금(${esc(now)}) 아는 것을 나란히 보여 드려요.</p>
    <div class="row"><input id="tmDate" type="date" max="${esc(now)}"><button id="tmGo">이 날짜로 비교</button></div><div id="tmOut"></div></div>`;
  $('#tmGo').onclick = async () => {
    const d = $('#tmDate').value; if (!d){ toast('날짜를 골라 주세요.'); return; }
    if (!a.card){ toast('질문 카드로 얻은 답만 비교할 수 있어요.'); return; }
    $('#tmOut').innerHTML = '<p>그날 기준으로 다시 계산하는 중…</p>';
    try {
      const r = await api('/api/easy/run', {method:'POST', body:{card:a.card, company:a.company, cutoff:`${d}T16:00:00+09:00`}});
      let run; for (let i = 0; i < 120; i++){ run = await api('/api/runs/' + r.id); if (!['waiting', 'queued', 'running'].includes(run.status)) break; await new Promise(z => setTimeout(z, 400)); }
      const b = await api('/api/easy/answer/' + r.id);
      const lab = new Map(); a.items.forEach(it => lab.set(it.label, [null, it])); b.items.forEach(it => lab.set(it.label, [it, (lab.get(it.label) || [null, null])[1]]));
      const rows = [...lab.entries()].filter(([, [x, y]]) => x && y).slice(0, 14);
      const onlyNow = [...lab.values()].filter(([x, y]) => y && !x).length;
      $('#tmOut').innerHTML = `<table><tr><th>항목</th><th>그때 (${esc(d)})</th><th>지금 (${esc(now)})</th></tr>
        ${rows.map(([l, [x, y]]) => `<tr><td>${esc(l)}</td><td>${esc(x.text)}</td><td class="${x.text !== y.text ? 'diff' : ''}">${esc(y.text)}</td></tr>`).join('')}</table>
        <p class="hint">그때 답: 확인 ${b.count.fact} · 계산 ${b.count.calc} · 추정 ${b.count.estimate} · 모르는 것 ${b.unknown.length}. 지금만 있는 항목 ${onlyNow}개(그날엔 아직 공개되지 않았던 자료).
        그날 기준 답은 그날 장 마감까지 공개된 자료만 썼어요 — 나중에 나온 자료가 섞이지 않아요.</p>
        <p><button class="ghost" id="tmOpen">그때 답 전체 보기</button></p>`;
      $('#tmOpen').onclick = () => openAnswer(r.id);
    } catch(e){ $('#tmOut').innerHTML = `<p class="ng">${esc(e.message)}</p>`; }
  };
}

/* ---------------- 직접 물어보기 ---------------- */
/* v0.26 AI 길잡이 — 질문 통역·사용 안내만. 숫자·판단을 만들지 않고, 실행은 언제나 사용자가 누른다 */
function aiOn(){ return !!(E.guideStatus && E.guideStatus.available && store.get('mrn_ai_guide', false)); }
function guideToggleHtml(){
  const s = E.guideStatus || {};
  if (!s.available) return `<details class="aig off"><summary>AI 길잡이 <span class="hint">— 지금 꺼져 있어요(이 PC에 AI 모델이 연결돼 있지 않음)</span></summary>
    <p class="hint">켜면 알아듣지 못한 질문을 앱이 알아듣는 말로 바꿔 드려요. 숫자나 투자 판단은 만들지 않아요. 켜는 방법(관리자): ${esc(s.how || '')}</p></details>`;
  return `<label class="aig"><input type="checkbox" id="aiOn" ${aiOn() ? 'checked' : ''}> <b>AI 길잡이 쓰기</b>
    <span class="hint">— 알아듣지 못한 질문을 앱의 말로 바꿔 드려요 · 숫자·판단은 만들지 않아요 · 모델 ${esc(s.model || '')}${s.local ? ' (이 PC 안에서만 동작)' : ' (외부 서버 — 질문이 밖으로 나가요)'}</span></label>`;
}
function guideOffer(q, understood){
  const box = $('#guideBox'); if (!box) return;
  const label = aiOn() ? 'AI 길잡이에게 바꿔 달라고 하기' : '가까운 질문 찾아보기';
  box.innerHTML = understood
    ? `<p class="hint">원하던 내용이 아니면 <a href="#" id="gGo">${esc(label)}</a></p>`
    : `<div class="gofr"><b>질문을 다 알아듣지 못했어요.</b> <button id="gGo">${esc(label)}</button></div>`;
  $('#gGo').onclick = ev => { ev.preventDefault(); guide(q).catch(e => toast(e.message)); };
}
async function guide(q){
  const box = $('#guideBox'); box.innerHTML = `<p class="hint">${aiOn() ? 'AI 길잡이가 질문을 살펴보는 중…' : '가까운 질문을 찾는 중…'}</p>`;
  const r = await api('/api/guide/translate', {method:'POST', body:{question: q, company: E.co || '', use_model: aiOn()}});
  const ai = r.mode === 'model' && r.ai_written;
  const sug = r.suggestions.map(s => `<button class="ghost" data-card="${esc(s.id)}">${esc(s.title)}</button>`).join(' ');
  box.innerHTML = `<div class="gbox ${ai ? 'ai' : 'rule'}">
    <div class="gh">${ai ? `<span class="b ai">AI 작성</span> AI 길잡이 제안 <span class="hint">· 모델 ${esc(r.model || '')} ${r.model_calls}회 · 숫자·판단 없음 · 실행은 직접 눌러요</span>`
      : r.refused ? '<b>판단은 드리지 않아요</b>' : `<b>가까운 질문</b> <span class="hint">· 규칙으로 찾았어요 (AI 아님)</span>`}</div>
    ${r.why ? `<p>${esc(r.why)}</p>` : ''}
    ${r.rewrite ? `<p class="grw">이렇게 물어볼까요? <b>「${esc(r.rewrite)}」</b> <button id="gUse">이 질문으로 물어보기</button></p>` : ''}
    ${r.card ? `<p>가장 가까운 질문 카드: <button class="ghost" data-card="${esc(r.card.id)}">${esc(r.card.title)}</button></p>` : ''}
    ${sug ? `<p class="gs">${r.refused ? '판단 재료를 볼 수 있는 질문' : r.card || r.rewrite ? '규칙으로 찾은 다른 후보' : '이 질문들이 가까워요'}: ${sug}</p>` : ''}
    ${r.checks && r.checks.length ? `<p class="hint">안전 검사로 뺀 것: ${r.checks.map(esc).join(' / ')}</p>` : ''}</div>`;
  box.querySelectorAll('[data-card]').forEach(b => b.onclick = () => { if (!E.co){ toast('먼저 회사를 골라 주세요.'); return; } ask(b.dataset.card); });
  if ($('#gUse')) $('#gUse').onclick = () => { E.pendingGuide = r; $('#freeQ').value = r.rewrite; freeAsk().catch(e => toast(e.message)); };
}

/* v0.24.3 직접 물어보기 예시 — 앱이 알아듣는 낱말로 만든 질문. 누르면 칸만 채우고(바로 조사하지 않음) 「물어보기」로 확인 */
const FREE_EX = [
  ['실적·현금흐름', '{co} 2025년 영업이익과 현금흐름은?'],
  ['수급 엇갈림', '{co} 외국인 순매수와 주가가 엇갈린 날은?'],
  ['환율 영향', '{co} 환율 영향 크기는 얼마야?'],
  ['변동성·국면', '{co} 변동성과 하락장 국면은?'],
  ['공시 뒤 반응', '{co} 공시 후 주가 반응은?']];
const FREE_WORDS = '매출·영업이익·현금흐름·부채 / 기업가치·DCF / 금리·환율·환율 영향·민감도 / 주가 흐름·이동평균·거래량 / 변동성·낙폭·국면 / 외국인·기관·순매수·공매도 / 엇갈·불일치 / 경쟁사·비교기업 / 점유율·경쟁력 / 뉴스·최근 공시 / 공시 후 반응 / 대주주·지분 / 수출·실적 발표 전 / 상관관계·함께 움직 / 컨센서스·전망치';
function renderFreeEx(){
  const box = $('#freeEx'); if (!box) return;
  const nm = info(E.co)?.name || '이 회사';
  box.innerHTML = `<div class="fx-h">이렇게 물어보면 잘 알아들어요 <span class="hint">— 누르면 칸에 들어가요. 고친 뒤 「물어보기」</span></div>
    <div class="fx">${FREE_EX.map(([t, q]) => `<button class="ghost" data-q="${esc(q.replace('{co}', nm))}" title="${esc(q.replace('{co}', nm))}">${esc(t)}</button>`).join('')}</div>
    <details class="fx-w"><summary>앱이 알아듣는 낱말 보기</summary><p>${esc(FREE_WORDS)}</p>
      <p class="hint">무엇을 보고 싶은지 위 낱말로, 한두 가지만 물으면 가장 정확해요. 질문 카드에 있는 질문은 카드가 더 정확해요. 사거나 팔지, 목표주가는 답하지 않아요.</p></details>
    ${guideToggleHtml()}`;
  const t = $('#aiOn'); if (t) t.onchange = () => { store.set('mrn_ai_guide', t.checked); toast(t.checked ? 'AI 길잡이를 켰어요. 알아듣지 못한 질문을 앱의 말로 바꿔 드려요.' : 'AI 길잡이를 껐어요. 규칙으로만 찾아요.'); };
  box.querySelectorAll('[data-q]').forEach(b => b.onclick = () => { $('#freeQ').value = b.dataset.q; $('#freeQ').focus(); $('#freeOut').innerHTML = ''; });
}
async function freeAsk(){
  const q = $('#freeQ').value.trim(); if (!q){ toast('질문을 적어 주세요.'); return; }
  const gmeta = E.pendingGuide && E.pendingGuide.rewrite === q ? E.pendingGuide : null;   // AI 길잡이가 바꿔 준 질문 그대로일 때만
  const name = info(E.co)?.name || '';
  const question = name && !q.includes(name) ? `${name} ${q}` : q;
  const r = await api('/api/agent/assemble', {method:'POST', body:{question, cutoff: cutoff()}});
  const ok = r.doc && !(r.issues || []).length;
  $('#freeOut').innerHTML = `<div class="box unk"><b>이렇게 이해했어요</b><ul>${r.targets.map(t => `<li>${esc(t.label)}</li>`).join('') || '<li>알아볼 수 있는 항목을 찾지 못했어요</li>'}</ul>
    ${r.gaps.length ? `<p>아직 답할 수 없는 것: ${r.gaps.map(g => esc(g.label)).join(', ')}</p>` : ''}${r.notes.map(n => `<p class="hint">${esc(n)}</p>`).join('')}</div>
    ${ok ? '<button id="freeRun">이대로 조사하기</button>' : ''}
    ${gmeta ? `<p class="hint">이 질문은 AI 길잡이(${esc(gmeta.model || '')})가 바꿔 준 거예요. 실행해도 숫자·계산은 모두 앱이 규칙으로 만들어요.</p>` : ''}
    <div id="guideBox"></div>`;
  guideOffer(q, ok && r.targets.length && !r.gaps.length);
  if (ok) $('#freeRun').onclick = async () => {
    const doc = {...r.doc, cutoff: cutoff(), meta: {ui: 'easy', company: E.co, card: '', question: q, planned_by: r.method || 'rule',
      ...(gmeta ? {guide: {model: gmeta.model, calls: gmeta.model_calls, prompt_sha: gmeta.prompt_sha, prompt_version: gmeta.prompt_version}} : {})}};
    E.ctx = {card:'', title:q, company:E.co, question:q};
    try { const x = await api('/api/runs', {method:'POST', body:{doc}}); follow(x.id); } catch(e){ toast(e.message); }
  };
}

/* ---------------- 최근 본 답 ---------------- */
function remember(a){
  const h = store.get('mrn_easy_hist', []).filter(x => x.rid !== a.run_id);
  h.unshift({rid: a.run_id, name: a.name, co: a.company, card: a.card || '', title: a.card_title || (E.ctx && E.ctx.question) || '직접 한 질문', date: (a.cutoff || '').slice(0, 10), at: new Date().toISOString().slice(0, 16).replace('T', ' ')});
  store.set('mrn_easy_hist', h.slice(0, 30));
}
function openHistory(){
  const h = store.get('mrn_easy_hist', []);
  $('#hList').innerHTML = h.map(x => `<li data-r="${esc(x.rid)}"><b>${esc(x.name || '')}</b> · ${esc(x.title)} <span class="hint">(${esc(x.date)} 기준 · ${esc(x.at)} 확인)</span></li>`).join('') || '<li class="hint">아직 없어요.</li>';
  $('#hList').querySelectorAll('[data-r]').forEach(li => li.onclick = () => openAnswer(li.dataset.r).catch(() => toast('이 답을 찾지 못했어요(다른 브라우저에서 만든 답일 수 있어요).')));
  show('history');
}

/* ---------------- 처음 안내 ---------------- */
const INTRO = [
  ['하려는 일부터 고르세요', '<b>궁금한 것 묻기</b> · <b>내 생각 시험하기</b> · <b>근거 검증하기</b> — 세 개의 문 중 하나를 고르면, 회사 → 질문 → 답 → 근거 순서로 안내해 드려요. 사거나 팔라는 말은 하지 않아요.'],
  ['숫자를 누르면 근거가 열려요', '초록은 <b>자료로 확인</b>, 파랑은 <b>계산한 값</b>, 주황은 <b>추정·가정</b>이에요. 숫자를 누르면 원문·계산 방법·자료 지문(해시)이 보여요.'],
  ['답이 어떻게 만들어졌는지 보여 드려요', '답 아래 <b>작동 원리</b> 띠: 질문 이해 → 자료 찾기 → 계산 → 검사 → 확인서. 눌러 보면 이번 답에서 실제로 한 일과 쓴 기술(에이전트·원문 검색 등), AI 모델을 몇 번 불렀는지까지 나와요.']];
function intro(force){
  if (!force && store.get('mrn_easy_intro', false)) return;
  let i = 0; const draw = () => { $('#iBody').innerHTML = `<h2>${INTRO[i][0]}</h2><p>${INTRO[i][1]}</p><p class="hint">${i + 1} / ${INTRO.length}</p>`; $('#iNext').textContent = i === INTRO.length - 1 ? '시작하기' : '다음'; };
  const done = () => { $('#intro').hidden = true; store.set('mrn_easy_intro', true); $('#coInput').focus(); };
  $('#iNext').onclick = () => { if (i < INTRO.length - 1){ i++; draw(); } else done(); };
  $('#iSkip').onclick = done; draw(); $('#intro').hidden = false;
}

/* ---------------- 어떻게 일하나요? (v1.4) ---------------- */
const AB_STEPS = [
  ['질문 이해', '질문 카드는 미리 정해 둔 순서(근거 사슬)로, 직접 한 질문은 조립 에이전트가 낱말을 규칙으로 읽어 필요한 단계를 골라 이어요.', '에이전트'],
  ['자료 찾기', '공시·통계·시세 사본에서 그대로 불러오고, 사업보고서 문장이 필요하면 원문에서 관련 문단을 찾아와요(RAG의 「찾아오기」). 찾은 문단마다 원문 지문을 붙여요.', 'RAG · 도구'],
  ['계산', '정해진 식과 규칙으로만 계산해요. 같은 자료면 언제나 같은 값이 나와요.', '계산 규칙'],
  ['검사', '값을 「자료로 확인 · 계산 · 추정」으로 나누고, 매매·추천 표현이 있는지 규칙으로 검사하고, 기준 날짜 뒤에 나온 자료는 빼요.', '근거 관문'],
  ['확인서', '쓴 자료의 지문(해시)과 단계를 담은 근거 확인서를 만들어요. 누구나 같은 근거로 다시 계산해 똑같이 나오는지 대조할 수 있어요. 막힌 곳은 수리 에이전트가 대체 방법을 제안하고, 사람이 고른 것만 다시 조사해요.', '확인서 · 수리 에이전트']];
// v0.37.1: 화면에는 한 단어 대신 짧은 문장으로 보인다(엔진이 넘기는 이름은 그대로)
const AB_LABEL = {'실시간': '가장 최근 자료로 답해요 (최신성)', '에이전트': '필요한 단계를 알아서 이어요 (에이전트)', '전문': '숫자마다 근거를 열어 볼 수 있어요 (전문성)', '교육': '읽는 법을 함께 알려 줘요 (교육형)', '맞춤': '내 조건·내 가정으로 볼 수 있어요 (맞춤형)', '반응': '막히면 다른 길을 알려 줘요 (반응형)', '개방': '누구나 다시 계산해 볼 수 있어요 (개방성)', '재귀발전': '지난 답을 돌아보며 고쳐 가요 (재귀성)', '예측': '「이 가정이라면」으로 앞을 가늠해요 (예측력)', '감성분석': '뉴스 분위기를 점수로 보여 줘요 (감성분석)'};
const AB_KEY = {'실시간': '최신성', '에이전트': '에이전트', '전문': '전문성', '교육': '교육형', '맞춤': '맞춤형', '반응': '반응형', '개방': '개방성', '재귀발전': '재귀성', '예측': '예측력', '감성분석': '감성분석'};
const AB_ATTRS = [
  ['실시간', '답 맨 위 「○○ 장 마감까지 공개된 자료 기준」, 기준 날짜 바꾸기', 'home'],
  ['에이전트', '작동 원리 「질문 이해」, 직접 물어보기, 막힌 곳 고치기', 'home'],
  ['전문', '숫자를 눌러 여는 근거 서랍 — 원문 링크·계산 방법·자료 지문', 'home'],
  ['교육', '배지 설명, 「이 화면을 읽는 법」, 이 페이지의 쉬운 말 풀이', 'about'],
  ['맞춤', '회사·질문·기준 날짜를 골라 나만의 근거 사슬, 내 가정 넣기', 'test'],
  ['반응', '자료가 모자라 보류되면 「이렇게 하면 알 수 있어요」 대체 방법 제안', 'home'],
  ['개방', '모두의 가정(5명 이상일 때 분포만), 누구나 다시 계산하는 근거 확인서', 'test'],
  ['재귀발전', '전망 vs 실제 사후 기록, 고쳐서 다시 조사한 답, 그때 vs 지금', 'check'],
  ['예측', '증권사 · 모두 · 실제 그림, 이번 분기 매출 조기 가늠 — 모두 「이 가정이라면」', 'test'],
  ['감성분석', '「요즘 무슨 일이 있었나?」의 뉴스 제목 감성 점수(사전 기반 규칙)와 공시 뒤 주가 반응 — 기대·우려를 판단하지 않아요', 'ask']];
const AB_WORDS = [
  ['에이전트', '질문을 보고 필요한 단계를 골라 잇고, 실행하고, 막히면 고칠 방법을 찾는 프로그램. 이 앱의 에이전트는 지금 규칙으로 움직여요(AI 모델을 부르지 않음).'],
  ['RAG', '답하기 전에 원문에서 관련 문단을 먼저 찾아와(Retrieval) 그 문단에 근거해 답하는 방식. 이 앱은 「찾아오기」까지만 하고, 찾은 문단을 그대로 보여 줘요.'],
  ['근거 관문', '답으로 나가기 전에 값의 종류·금지 표현·기준 날짜를 검사하는 단계.'],
  ['지문(해시)', '자료 파일이 한 글자라도 바뀌면 달라지는 고유 번호. 같은 지문이면 같은 자료예요.'],
  ['근거 확인서', '「이 근거로 계산하면 이 결과가 나온다」를 담은 파일. 결과가 옳다거나 투자해도 된다는 보증은 아니에요.']];
async function openAbout(){
  $('#abSteps').innerHTML = AB_STEPS.map((x, i) => `<li><span class="sn">${i + 1}</span><div><b>${esc(x[0])}</b> <span class="b unk">${esc(x[2])}</span><br>${esc(x[1])}</div></li>`).join('');
  const P = E.ans && E.ans.process;
  $('#abAi').innerHTML = `<b>AI 모델은 언제 쓰나요?</b><p>질문 카드·직접 물어보기·계산은 <b>AI 모델을 부르지 않아요</b>(규칙과 계산만). 그래서 같은 질문·같은 기준 날짜면 언제나 같은 답이 나오고, 근거 확인서로 다시 계산할 수 있어요. <b>AI 길잡이</b>를 켠 경우에만, 알아듣지 못한 질문을 앱의 말로 바꾸는 데 AI를 써요 — 숫자·판단은 만들지 않고, 바꾼 질문은 규칙 엔진이 다시 확인하며, 실행은 사용자가 직접 눌러요. 그때는 답의 「작동 원리」에 AI 모델 횟수가 표시돼요.
    AI 모델을 붙이게 되면, 모델이 쓴 부분과 호출 횟수를 답마다 따로 표시할게요.</p>${P ? `<p class="hint">마지막으로 본 답: AI 모델 호출 ${P.model_calls}회</p>` : ''}`;
  $('#abAttrs').innerHTML = AB_ATTRS.map(x => `<button class="attrc" data-go="${x[2]}"><b>${esc(AB_LABEL[x[0]] || x[0])}</b><span>${esc(x[1])}</span></button>`).join('');
  $('#abAttrs').querySelectorAll('[data-go]').forEach(b => b.onclick = () => { const g = b.dataset.go; if (g === 'about') return; show('home'); if (['ask', 'test', 'check'].includes(g)) setDoor(g, true); });
  $('#abWords').innerHTML = AB_WORDS.map(x => `<dt>${esc(x[0])}</dt><dd>${esc(x[1])}</dd>`).join('');
  show('about');
}

function modeTip(){
  const b = document.getElementById('mbWhy'), t = document.getElementById('mbTip'); if (!b || !t) return;
  const set = on => { t.classList.toggle('open', on); b.setAttribute('aria-expanded', on); };
  b.onclick = e => { e.stopPropagation(); set(!t.classList.contains('open')); };
  document.addEventListener('click', e => { if (!t.contains(e.target) && e.target !== b) set(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
}

/* ---------------- 시작 ---------------- */
async function boot(){
  await api('/api/health');
  try { const reg = await api('/api/registry'); E.names = Object.fromEntries(reg.nodes.map(n => [n.id, n.display_name])); } catch(e){}
  try { E.guideStatus = await api('/api/guide/status'); } catch(e){ E.guideStatus = {available: false}; }
  await loadUniverse();
  $('#coInput').addEventListener('input', () => { const t = resolve($('#coInput').value); if (t && t !== E.co) choose(t); });
  $('#coInput').addEventListener('keydown', e => { if (e.key === 'Enter'){ const t = resolve($('#coInput').value); if (t) choose(t); else toast('목록에 있는 회사를 골라 주세요.'); } });
  $('#freeGo').onclick = () => freeAsk().catch(e => toast(e.message));
  $('#freeQ').addEventListener('keydown', e => { if (e.key === 'Enter') freeAsk().catch(x => toast(x.message)); });
  $('#cutClear').onclick = () => { $('#cutDate').value = ''; };
  $('#dClose').onclick = () => $('#drawer').hidden = true;
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#drawer').hidden = true; });
  $('#pBack').onclick = $('#vBack').onclick = $('#hBack').onclick = $('#abBack').onclick = () => show('home');
  $('#nAbout').onclick = openAbout;
  modeTip();
  $('#hvFile').onchange = e => { if (e.target.files[0]){ show('verify'); verifyFile(e.target.files[0]); } };
  $('#path').querySelectorAll('li').forEach(li => li.onclick = () => { const p = li.dataset.p;
    if (p === 'door' || p === 'co' || p === 'q'){ show('home'); if (p === 'co') $('#coInput').focus(); }
    else if (p === 'ans' && E.ans) show('answer'); else if (p === 'ev' && E.ans) show('verify'); });
  setDoor(store.get('mrn_easy_door', 'ask'), false);
  $('#nVerify').onclick = () => show('verify'); $('#vFile').onchange = e => e.target.files[0] && verifyFile(e.target.files[0]);
  $('#nHistory').onclick = openHistory;
  $('.brand').onclick = e => { e.preventDefault(); show('home'); };
  setPath('door');
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get('answer')) openAnswer(h.get('answer')).catch(() => show('home'));
  else if (h.get('co') && info(h.get('co'))) choose(h.get('co'));
  intro(false);
}
boot().catch(e => { document.body.innerHTML = `<p style="padding:20px">시작하지 못했어요: ${esc(e.message)}</p>`; });

/* ---------------- v0.25 공시 반응 사전: 「이런 공시가 나오면 예전엔 어땠나?」 (AI 모델 0회 · 판단 아님) ---------------- */
const RX_CLS = {up:'up', down:'down', lean_up:'lean', lean_down:'lean', flat:'flat', held:'held'};
function rxStyle(){
  if (document.getElementById('rxStyle')) return;
  const st = document.createElement('style'); st.id = 'rxStyle';
  st.textContent = `.rx .chip{display:inline-block;border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600;white-space:nowrap}
.rx .chip.up{background:#e5f4e4;color:#1d6b2a}.rx .chip.down{background:#fbebeb;color:#a12a2a}.rx .chip.lean{background:#f9eeda;color:#8a5a00}
.rx .chip.flat{background:#f0efec;color:#555}.rx .chip.held{background:#f0efec;color:#888}
.rx table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0}.rx th,.rx td{border-bottom:1px solid var(--line);padding:6px 6px;text-align:left;vertical-align:top}
.rx th{color:var(--mute);font-weight:600}.rx td.n{text-align:right;font-variant-numeric:tabular-nums}
.rx .try{display:flex;gap:8px;margin:8px 0}.rx .try input{flex:1;padding:10px 12px;border:1px solid var(--line);border-radius:10px;font-size:15px}
.rx .res{border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:10px 0;background:#fcfcfb}.rx .big{font-size:17px;font-weight:700;margin:6px 0}
.rx .bar{position:relative;height:10px;background:#f0efec;border-radius:5px;margin:6px 0 2px}.rx .bar i{position:absolute;top:0;bottom:0;background:#9db7d9;border-radius:5px}
.rx .bar b{position:absolute;top:-3px;width:2px;height:16px;background:#333}.rx .bar u{position:absolute;top:-3px;width:1px;height:16px;background:#bbb}
.rx .ex{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0}.rx .ex button{font-size:13px;padding:4px 10px}`;
  document.head.appendChild(st);
}
const pct = (v, d=2) => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(d) + '%';
function rxChip(v, plain){ return `<span class="chip ${RX_CLS[v] || 'held'}" title="과거 기록을 정해진 규칙으로 나눈 것이에요. 이번 공시의 결과가 아니에요">${esc(plain)}</span>`; }
function rxRange(s){
  if (!s || s.p25 == null) return '';
  const lo = Math.min(-6, s.p25), hi = Math.max(6, s.p75), X = v => ((v - lo) / (hi - lo) * 100).toFixed(1) + '%';
  return `<div class="bar" title="가운데 절반의 범위(25~75%)와 평균"><u style="left:${X(0)}"></u><i style="left:${X(s.p25)};width:calc(${X(s.p75)} - ${X(s.p25)})"></i><b style="left:${X(s.mean)}"></b></div>
    <div class="hint">가운데 절반: ${pct(s.p25, 1)} ~ ${pct(s.p75, 1)} · 회색 선 = 0%</div>`;
}
async function openReaction(){
  rxStyle(); setPath('ans');
  const co = E.co, nm = info(co)?.name || co, cut = cutoff();
  show('answer');
  $('#answer').innerHTML = `<div class="ans rx"><div class="q">${esc(nm)} · 이런 공시가 나오면 예전엔 어땠나?</div><div class="head">과거 기록을 모으는 중…</div></div>`;
  let rec, dict;
  try { [rec, dict] = await Promise.all([api(`/api/reaction/recent?company=${co}&days=60&cutoff=${encodeURIComponent(cut)}`), api(`/api/reaction/dictionary?cutoff=${encodeURIComponent(cut)}`)]); }
  catch(e){ $('#answer').innerHTML = `<div class="ans rx"><div class="head">공시 반응 사전을 만들지 못했어요</div><p>${esc(e.message)}</p><div class="acts"><button class="ghost" id="aHome">다른 질문</button></div></div>`; $('#aHome').onclick = () => show('home'); return; }
  E.rxDict = dict;
  const ctl = dict.control, rows = rec.rows;
  const strong = dict.table.filter(r => !r.routine && ['up', 'down'].includes(r.verdict));
  const head = rows.length
    ? `최근 60일 ${esc(nm)} 공시 ${rows.length}건을, 같은 종류 공시가 과거에 나온 뒤의 주가 반응 기록과 나란히 정리했어요.`
    : `최근 60일 ${esc(nm)}의 주요 공시는 없어요. 아래에 공시 제목을 넣어 과거 기록을 볼 수 있어요.`;
  const ex = ['주요사항보고서(자기주식취득결정)', '단일판매ㆍ공급계약체결', '풍문또는보도에대한해명', '유상증자결정', '타인에대한채무보증결정'];
  $('#answer').innerHTML = `<div class="ans rx">
    <div class="q">${esc(nm)} · 이런 공시가 나오면 예전엔 어땠나? · <b>${esc(dict.last_usable_date)}</b> 장 마감까지 공개된 자료 기준</div>
    <div class="head">${head}</div>
    <div class="strip" title="이 답이 만들어진 순서">질문 이해 › 자료 찾기 (공시 ${dict.n_disclosures.toLocaleString()}건 · ${dict.n_companies}개 회사) › 계산 (시장 대비 반응) › 검사 (표본 ${dict.rules.min_events}건 · |t| ≥ ${dict.rules.t_strong}) · <b>AI 모델 0회</b></div>
    <h3>${esc(nm)} 최근 공시</h3>
    ${rows.length ? `<table><tr><th>날짜</th><th>공시</th><th>과거 기록</th><th class="n">보통 (이틀)</th><th class="n">이번 (이틀)</th></tr>
      ${rows.map(r => `<tr><td>${esc(r.date.slice(5))}</td><td><a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.title)}</a>${r.mixed ? ' <span class="hint" title="같은 날 다른 주요 공시가 함께 있어 이 공시만의 반응으로 보기 어려워요">· 다른 공시와 섞임</span>' : ''}</td>
        <td>${rxChip(r.verdict, r.plain)}</td><td class="n">${pct(r.typical_first)}</td><td class="n">${pct(r.actual_first)}</td></tr>`).join('')}</table>
      <p class="hint">「보통」은 같은 종류 공시 뒤 이틀 동안 시장보다 움직인 평균, 「이번」은 이 공시 뒤 실제로 움직인 값이에요(아직 이틀이 안 지났으면 —).</p>` : '<p class="hint">기간 안에 정기·반복 공시 말고는 없어요.</p>'}
    <h3>새 공시 제목 넣어 보기</h3>
    <div class="try"><input id="rxIn" placeholder="예: 주요사항보고서(자기주식취득결정)" maxlength="300"><button id="rxGo">과거 기록 보기</button></div>
    <div class="ex">${ex.map(t => `<button class="ghost" data-t="${esc(t)}">${esc(t.replace('주요사항보고서', '').replace(/[()]/g, ''))}</button>`).join('')}</div>
    <div id="rxOut"></div>
    <details class="all"><summary>공시 종류별 기록 전체 (${dict.table.length}종)</summary>
      <table><tr><th>공시 종류</th><th class="n">건수</th><th class="n">이틀 평균</th><th class="n">시장보다 오른 비율</th><th>과거 기록</th><th class="n">20일 평균</th></tr>
      ${dict.table.map(r => { const s = r.stats.first, d = r.stats.drift20; return `<tr><td>${esc(r.label)}${r.routine ? ' <span class="hint">(대조군)</span>' : ''}</td><td class="n">${s.n || 0}</td><td class="n">${pct(s.mean)}</td><td class="n">${s.n ? Math.round(s.up_share * 100) + '%' : '—'}</td><td>${rxChip(r.verdict, r.plain)}</td><td class="n">${pct(d.mean)}</td></tr>`; }).join('')}</table>
      <p class="hint">대조군(정기보고서·임원 보고 등)의 이틀 평균이 ${pct(ctl && ctl.mean)}로 0에 가까우면 비교 기준이 한쪽으로 치우치지 않았다는 뜻이에요.</p></details>
    <div class="box not"><b>이 결과가 아닌 것</b><ul><li>${esc(dict.notice)}</li>${dict.notes.map(n => `<li>${esc(n)}</li>`).join('')}
      <li>지금 기록상 첫 반응이 뚜렷한 종류는 ${strong.length ? strong.map(r => esc(r.label)).join(', ') : '없어요'}. 대부분의 공시는 「종류」만으로는 방향이 뚜렷하지 않았어요 — 금액·내용이 더 중요해요.</li></ul></div>
    <div class="acts"><button id="aHome" class="ghost">다른 질문</button></div>
    <p class="hint">사본 ${esc(dict.snapshot)} · 목록 지문 ${esc(dict.manifest_sha256.slice(0, 12))} · ${esc(UI_VERSION)}</p>
  </div>`;
  const go = async t => {
    t = (t || $('#rxIn').value).trim(); if (!t) return; $('#rxIn').value = t;
    try { const j = await api('/api/reaction/judge', {method:'POST', body:{title:t, company:co, cutoff:cut}}); rxDraw(j, nm); } catch(e){ toast(e.message); }
  };
  $('#rxGo').onclick = () => go(); $('#rxIn').onkeydown = ev => { if (ev.key === 'Enter') go(); };
  $('#answer').querySelectorAll('.ex button').forEach(b => b.onclick = () => go(b.dataset.t));
  $('#aHome').onclick = () => show('home');
  const h = store.get('mrn_easy_hist', []).filter(x => x.rid !== 'rx:' + co);
  h.unshift({rid: 'rx:' + co, name: nm, co, card: 'reaction', title: '이런 공시가 나오면 예전엔 어땠나?', date: dict.last_usable_date, at: new Date().toISOString().slice(0, 16).replace('T', ' ')});
  store.set('mrn_easy_hist', h.slice(0, 30));
}
function rxDraw(j, nm){
  const s = j.stats && j.stats.first, d = j.stats && j.stats.drift20;
  $('#rxOut').innerHTML = `<div class="res">
    <div class="hint">「${esc(j.title)}」 → ${esc(j.group_label)}</div>
    <div class="big">${rxChip(j.verdict, j.plain)} ${esc(j.verdict_label)}</div>
    ${pretty(j.line)}
    ${s && s.n ? `${rxRange(s)}<p class="hint">이틀 반응 · 건수 ${s.n} (서로 다른 날 ${s.n_dates}) · 중앙값 ${pct(s.median)} · t ${s.t == null ? '—' : s.t.toFixed(2)} · 앞 절반 ${pct(s.first_half)} / 뒤 절반 ${pct(s.second_half)}</p>` : ''}
    ${d && d.n ? `<p class="hint">20거래일까지 이어진 반응: 평균 ${pct(d.mean)} (${d.n}건) — ${esc({up:'과거엔 대체로 더 올랐어요', down:'과거엔 대체로 더 내렸어요', lean_up:'오른 쪽으로 약한 경향', lean_down:'내린 쪽으로 약한 경향', flat:'방향이 뚜렷하지 않았어요', held:'기록 부족'}[j.verdict_drift20] || '')}</p>` : ''}
    ${(j.cautions || []).length ? `<ul>${j.cautions.map(c => `<li>${esc(c)}</li>`).join('')}</ul>` : ''}
    ${(j.company_history || []).length ? `<details><summary>${esc(nm)}의 같은 종류 공시 ${j.company_history.length}건</summary><table><tr><th>날짜</th><th>공시</th><th class="n">이틀</th><th class="n">20일</th></tr>${j.company_history.map(h => `<tr><td>${esc(h.date)}</td><td>${esc(h.title)}</td><td class="n">${pct(h.first)}</td><td class="n">${pct(h.drift20)}</td></tr>`).join('')}</table></details>` : ''}
    <p class="hint">${esc(j.notice)} AI 모델 ${j.model_calls}회.</p></div>`;
}



/* ---------------- v0.27 관심 체온계: 「사람들이 얼마나 몰렸나?」 (2차 가공 · AI 모델 0회 · 인과 아님) ---------------- */
function atStyle(){
  if (document.getElementById('atStyle')) return;
  const st = document.createElement('style'); st.id = 'atStyle';
  st.textContent = `.at table{width:100%;border-collapse:collapse;font-size:14px;margin:8px 0}.at th,.at td{border-bottom:1px solid var(--line);padding:6px;text-align:left;vertical-align:middle}
.at th{color:var(--mute);font-weight:600}.at td.n{text-align:right;font-variant-numeric:tabular-nums}
.at .bars{display:flex;align-items:flex-end;gap:6px;height:120px;margin:12px 0 4px;padding:0 4px;border-bottom:1px solid var(--line)}
.at .bars div{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;font-size:11px;color:var(--mute)}
.at .bars i{display:block;width:100%;max-width:38px;background:#9db7d9;border-radius:4px 4px 0 0}.at .bars i.hi{background:#e0894a}.at .bars i.lo{background:#cfd6df}
.at .lab{display:flex;gap:6px;padding:0 4px;font-size:11px;color:var(--mute)}.at .lab span{flex:1;text-align:center}
.at .chip{display:inline-block;border-radius:999px;padding:2px 10px;font-size:13px;font-weight:600}.at .chip.hi{background:#f9ece7;color:#a4471a}.at .chip.lo{background:#f0efec;color:#666}.at .chip.mid{background:#e7f1fb;color:#2b5d8f}
.at .flag{font-size:12px;color:#a4471a}.at svg.sp{width:100%;height:110px;display:block;margin:6px 0}`;
  document.head.appendChild(st);
}
function atLevel(m){ return m == null ? ['—', ''] : m >= 2 ? ['훨씬 많음', 'hi'] : m >= 1.3 ? ['많음', 'hi'] : m <= 0.7 ? ['적음', 'lo'] : ['평소', 'mid']; }
const xf = (v, d=1) => v == null ? '—' : v.toFixed(d) + '배';
const FLAG = {gap:'수집 간격 큼', negative_delta:'줄어든 값 뺌(색인 변동)', jump:'튄 값 뺌(수집 효과)', market_odd:'시장 전체 값 비정상 — 시장 감안 보류'};
async function openAttention(){
  atStyle(); setPath('ans');
  const co = E.co, nm = info(co)?.name || co, cut = cutoff();
  show('answer');
  $('#answer').innerHTML = `<div class="ans at"><div class="q">${esc(nm)} · 사람들이 얼마나 몰렸나?</div><div class="head">글 수를 하루 단위로 바꾸는 중…</div></div>`;
  let a;
  try { a = await api(`/api/attention/thermo?company=${co}&cutoff=${encodeURIComponent(cut)}`); }
  catch(e){ $('#answer').innerHTML = `<div class="ans at"><div class="head">관심 체온계를 만들지 못했어요</div><p>${esc(e.message)}</p><div class="acts"><button class="ghost" id="aHome">다른 질문</button></div></div>`; $('#aHome').onclick = () => show('home'); return; }
  const S = a.series.filter(r => r.posts != null), mx = Math.max(1, ...S.map(r => r.posts));
  const rel = a.relation || {}, yt = a.youtube_recent, se = a.sentiment;
  const r2 = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2);
  $('#answer').innerHTML = `<div class="ans at">
    <div class="q">${esc(nm)} · 사람들이 얼마나 몰렸나? · <b>${esc(a.last_usable_date)}</b> 장 마감까지 수집된 자료 기준</div>
    <div class="head">${esc(a.head)}</div>
    <div class="strip" title="이 답이 만들어진 순서">질문 이해 › 글 수 모으기 (포털 검색 결과 수 · ${a.relation.n_companies || ''}개 회사) › 하루 새 글로 바꾸기 (장 마감 시각 보간) › 시장 전체 빼기 › 거래량과 나란히 · <b>AI 모델 0회</b></div>
    ${S.length ? `<h3>하루 새 블로그·카페 글 (장 마감~장 마감, 24시간 기준)</h3>
    <div class="bars">${S.map(r => { const l = atLevel(r.adj_multiple)[1]; return `<div title="${esc(r.date)} 약 ${Math.round(r.posts).toLocaleString()}건"><span>${Math.round(r.posts).toLocaleString()}</span><i class="${l}" style="height:${Math.max(3, r.posts / mx * 100)}%"></i></div>`; }).join('')}</div>
    <div class="lab">${S.map(r => `<span>${esc(r.date.slice(5))}</span>`).join('')}</div>
    <p class="hint">주황 = 시장을 감안해도 평소보다 많은 날 · 회색 = 적은 날</p>
    <table><tr><th>날짜</th><th class="n">새 글</th><th class="n">이 회사 평소 대비</th><th class="n">시장 전체</th><th>시장 감안</th><th class="n">그날 거래량<br>(평소 대비)</th><th class="n">영상 댓글</th></tr>
      ${a.series.slice().reverse().map(r => { const l = atLevel(r.adj_multiple); return `<tr><td>${esc(r.date)}${r.flags.length ? `<div class="flag">${r.flags.map(f => esc(FLAG[f] || f)).join(' · ')}</div>` : ''}</td>
        <td class="n">${r.posts == null ? '—' : Math.round(r.posts).toLocaleString()}</td><td class="n">${xf(r.own_multiple)}</td><td class="n">${xf(r.market_multiple)}</td>
        <td>${r.adj_multiple == null ? '—' : `<span class="chip ${l[1]}">${xf(r.adj_multiple)} ${esc(l[0])}</span>`}</td><td class="n">${xf(r.volume_multiple)}</td><td class="n">${r.youtube ? r.youtube.comments.toLocaleString() : '—'}</td></tr>`; }).join('')}</table>` : '<p class="hint">하루 새 글을 만들 만큼 수집 기록이 쌓이지 않았어요.</p>'}
    <div class="box"><b>관심과 거래량 — 모든 회사 묶음 기록 (인과 아님)</b>
      <p>${esc(rel.line || '')}</p>
      <p class="hint">회사 ${rel.n_companies || 0}곳 · 거래일 ${rel.n_dates || 0}일 · 관측 ${rel.n || 0}건 · 회사·날짜 효과를 뺀 뒤 — 같은 날 거래량 ${r2(rel.same_day_volume)}${rel.same_day_volume_t != null ? ` (t ${rel.same_day_volume_t.toFixed(1)})` : ''} · 다음 날 거래량 ${r2(rel.next_day_volume)} · 다음 날 변동 ${r2(rel.next_day_absret)} (당일 거래량·변동을 뺀 편상관)</p></div>
    ${atSearch(a.search)}
    <div class="box"><b>다른 신호</b><ul>
      <li>영상 댓글(최근 5거래일): ${yt ? `${yt.comments.toLocaleString()}건 · 가장 많이 몰린 영상 비중 ${Math.round((yt.top_share || 0) * 100)}%${yt.top_share >= 0.6 ? ' — 한 영상에 몰렸어요(퍼진 관심이라기보다 한 곳의 반응)' : ''}` : '기록 없음'}</li>
      <li>감성 점수(단어 사전 규칙): ${se ? `점수가 붙은 글 ${se.n_scored.toLocaleString()} / ${se.n_docs.toLocaleString()}건 (${Math.round(se.cover * 100)}%)${se.usable ? (se.avg != null ? ` · 평균 ${r2(se.avg)}` : '') : ' — 4분의 1도 안 돼서 참고하기 어려워요'}` : '이 기간 기록 없음'}</li></ul></div>
    <div class="box not"><b>이 결과가 아닌 것</b><ul><li>${esc(a.notice)}</li>${a.notes.map(n => `<li>${esc(n)}</li>`).join('')}<li>순위를 매기지 않아요 — 회사를 고른 경우에만 보여 드려요.</li></ul></div>
    <div class="acts"><button id="aHome" class="ghost">다른 질문</button></div>
    <p class="hint">사본 ${esc(a.snapshot)} · 목록 지문 ${esc(a.manifest_sha256.slice(0, 12))} · ${esc(UI_VERSION)}</p>
  </div>`;
  $('#aHome').onclick = () => show('home');
  const h = store.get('mrn_easy_hist', []).filter(x => x.rid !== 'at:' + co);
  h.unshift({rid: 'at:' + co, name: nm, co, card: 'attention', title: '사람들이 얼마나 몰렸나?', date: a.last_usable_date, at: new Date().toISOString().slice(0, 16).replace('T', ' ')});
  store.set('mrn_easy_hist', h.slice(0, 30));
}

/* v0.29 과거 검색량(네이버 데이터랩) — 급증 뒤 기록 · 다다음 거래일 기준 관계 */
function atSearch(sb){
  if (!sb) return '';
  if (!sb.available) return `<div class="box"><b>과거 검색량 (네이버 데이터랩)</b><p class="hint">${esc(sb.line)}</p></div>`;
  const S = sb.series.filter(r => r.adj_multiple != null || r.multiple != null);
  const val = r => r.adj_multiple ?? r.multiple, W = 600, H = 100;
  const ys = S.map(r => Math.log(Math.max(0.2, Math.min(8, val(r))))), lo = Math.log(0.25), hi = Math.log(8);
  const Y = v => (H - (v - lo) / (hi - lo) * H).toFixed(1), X = i => (S.length > 1 ? i / (S.length - 1) * W : 0).toFixed(1);
  const path = ys.map((v, i) => `${i ? 'L' : 'M'}${X(i)},${Y(v)}`).join(' ');
  const pc = v => v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(2) + '%';
  const VL = {up:'과거엔 대체로 올랐어요', down:'과거엔 대체로 내렸어요', lean_up:'오른 쪽 약한 경향', lean_down:'내린 쪽 약한 경향', flat:'방향이 뚜렷하지 않았어요', held:'기록 부족'};
  const grp = (k, nm) => { const g = sb.spikes[k]; if (!g) return ''; const s = g.stats;
    return `<tr><td>${nm}</td><td class="n">${s.first.n || 0}</td><td class="n">${pc(s.first.mean)}</td><td class="n">${pc(s.drift5.mean)}</td><td class="n">${pc(s.drift20.mean)}</td><td>${esc(VL[g.verdict_drift20] || '')}</td></tr>`; };
  const R = sb.relation || {}, st = R.strict || {}, nx = R.same_and_next || {};
  return `<div class="box"><b>과거 검색량 (네이버 데이터랩 「주가」 검색 · ${esc(sb.range[0])}~${esc(sb.known_until)})</b>
    ${pretty(sb.line)}
    <svg class="sp" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="0" x2="${W}" y1="${Y(0)}" y2="${Y(0)}" stroke="#bbb" stroke-dasharray="4 4"/><line x1="0" x2="${W}" y1="${Y(Math.log(2))}" y2="${Y(Math.log(2))}" stroke="#e0894a" stroke-dasharray="2 4"/><path d="${path}" fill="none" stroke="#2b5d8f" stroke-width="2"/></svg>
    <p class="hint">최근 ${S.length}거래일 · 시장 감안 검색량 배수(로그 눈금) · 회색 점선 = 평소(1배), 주황 점선 = 2배 · ${esc(S[0]?.date || '')} ~ ${esc(S[S.length - 1]?.date || '')}</p>
    <p><b>검색이 몰린 날(시장 감안 2배 이상) 뒤 주가 — 모든 회사 ${sb.n_companies}곳, 급증 ${sb.n_spikes}번</b></p>
    <table><tr><th></th><th class="n">건수</th><th class="n">그날~다음 날</th><th class="n">2~5일</th><th class="n">2~20일</th><th>20일 기록</th></tr>${grp('no_disclosure', '공시 없이 몰린 날')}${grp('with_disclosure', '주요 공시와 함께 몰린 날')}${grp('unknown_disclosure', '공시 기록 이전(공시 여부 모름)')}${grp('all', '전체')}</table>
    <p class="hint">시장보다 움직인 정도(보통 종목 평균 대비)입니다. 공시 없이 몰린 날이 네티즌 관심만의 기록에 가까워요. 공시 목록은 ${esc(sb.disclosure_from || '—')}부터 있어서, 그보다 앞선 급증은 공시 여부를 몰라 따로 셌어요.</p>
    ${(sb.company_spikes || []).length ? `<details><summary>이 회사의 검색 급증 ${sb.company_spikes.length}번</summary><table><tr><th>날짜</th><th>공시</th><th class="n">그날~다음 날</th><th class="n">2~20일</th></tr>${sb.company_spikes.slice().reverse().map(e => `<tr><td>${esc(e.date)}</td><td>${e.with_disclosure == null ? '모름' : e.with_disclosure ? '있음' : '없음'}</td><td class="n">${pc(e.first)}</td><td class="n">${pc(e.drift20)}</td></tr>`).join('')}</table></details>` : ''}
    <p><b>검색량과 거래량 (회사·날짜 효과를 뺀 뒤, 인과 아님)</b></p>
    <ul><li>엄격 기준 — 다다음 거래일: ${esc(st.line || '—')}</li>
      <li>참고 — 다음 거래일 (데이터랩 공개 시각이 확인되지 않아 참고로만): 편상관 ${nx.next_day_volume == null ? '—' : nx.next_day_volume.toFixed(2)} · 거래일 ${nx.n_dates || 0}일</li></ul>
    <p class="hint">데이터랩 값은 요청마다 최댓값을 100으로 맞춘 상대값이라 회사끼리 크기를 비교하지 않고, 이 회사의 평소(이전 40거래일) 대비 배수만 써요. 기준일 당일 검색량은 아직 공개 전이라 쓰지 않아요. 사본 ${esc(sb.snapshot)}</p></div>`;
}
/* ---- v0.27 관심 체온계 끝 ---- */

/* ---------------- v0.32 공유용 페이지 · 가설 일지 · 배우는 길 (AI 모델 0회) ---------------- */
const JL = {learn: null, marked: new Set()};
function learnBadge(){ const b = $('#nLearn'); if (b && JL.learn) b.innerHTML = `따라하는 사용법 <span class="lcount">${JL.learn.done}/${JL.learn.total}</span>`; }
async function learnRefresh(){ try { JL.learn = await api('/api/learn'); learnBadge(); } catch(e){} }
function learnMark(task){
  if (JL.marked.has(task)) return; JL.marked.add(task);
  api('/api/learn/mark', {method:'POST', body:{task}}).then(p => { JL.learn = p; learnBadge(); }).catch(() => JL.marked.delete(task));
}

/* T1 공유용 페이지 — 설치 없이 열리는 한 장짜리 파일, 근거 확인서가 들어 있어 앱에 넣으면 다시 계산 */
async function downloadShare(){
  if (!E.rid) return;
  const q = (E.ans && E.ans.card_title) || (E.ctx && E.ctx.question) || '';
  try {
    const r = await fetch(`/api/share/${encodeURIComponent(E.rid)}?q=${encodeURIComponent(q)}`);
    if (!r.ok){ let m = '공유용 페이지를 만들지 못했어요.'; try { const d = await r.json(); if (typeof d.detail === 'string') m = d.detail; } catch(e){} throw new Error(m); }
    const blob = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = `공유_${(E.ans.name || '').replace(/\s/g, '')}_${E.rid.slice(0, 8)}.html`; a.click(); URL.revokeObjectURL(a.href);
    toast('공유용 페이지를 내려받았어요. 받는 사람은 설치 없이 열어 볼 수 있고, 앱에 넣으면 같은 근거로 다시 계산해 확인할 수 있어요.');
    learnRefresh();
  } catch(e){ toast(e.message); }
}
const _v32_openAnswer = openAnswer;
openAnswer = async function(rid, opt){
  const r = await _v32_openAnswer(rid, opt);
  const acts = document.querySelector('#answer .acts');
  if (acts && !$('#aShare') && !/^(rx|at):/.test(String(rid))){
    const b = document.createElement('button'); b.id = 'aShare'; b.className = 'share';
    b.title = '답·숫자·출처·작동 원리를 한 장짜리 파일로. 받는 사람은 설치 없이 읽고, 앱에 넣으면 다시 계산해 확인할 수 있어요';
    b.textContent = '공유용 페이지 내려받기'; b.onclick = downloadShare;
    acts.insertBefore(b, acts.children[1] || null);
  }
  return r;
};
const _v32_verifyFile = verifyFile;
verifyFile = async function(f){
  try {
    const t = await f.text();
    if (/^\s*</.test(t)){
      const m = t.match(/<script type="application\/json" id="modu-receipt">([\s\S]*?)<\/script>/);
      if (!m){ $('#vOut').innerHTML = '<p class="ng">이 파일에서 근거 확인서를 찾지 못했어요. 모두의리서치 공유용 페이지(.html)나 근거 확인서(.json)를 넣어 주세요.</p>'; return; }
      f = new File([m[1].replace(/<\\\//g, '</')], 'receipt.json', {type: 'application/json'});
    }
  } catch(e){}
  const r = await _v32_verifyFile(f); learnRefresh(); return r;
};

/* v0.38 확인서 사용법(vGuide): 연습 버튼 · 끌어다 놓기 · 결과를 쉬운 말로. 계산·API는 그대로. */
function vTryDraw(){
  const box = $('#vTry'); if (!box) return;
  box.innerHTML = E.rid
    ? `<button id="vTryBtn" class="ghost">방금 본 답으로 바로 해 보기</button> <span class="hint">파일 없이 지금 열려 있던 답(${esc(E.ans && E.ans.name || '')})의 확인서로 연습해요.</span>`
    : '<span class="hint">처음이라면: 질문 하나를 해서 답을 본 뒤 여기로 오면, 파일 없이 「방금 본 답으로 바로 해 보기」로 연습할 수 있어요.</span>';
  const b = $('#vTryBtn');
  if (b) b.onclick = async () => {
    b.disabled = true;
    try { const rc = await api('/api/easy/receipt/' + E.rid);
      await verifyFile(new File([JSON.stringify(rc)], 'receipt.json', {type: 'application/json'})); }
    catch(e){ toast(e.message); }
    b.disabled = false;
  };
}
(function(){
  const d = $('#vDrop'); if (!d) return;
  ['dragenter', 'dragover'].forEach(k => d.addEventListener(k, e => { e.preventDefault(); d.classList.add('on'); }));
  ['dragleave', 'drop'].forEach(k => d.addEventListener(k, e => { e.preventDefault(); d.classList.remove('on'); }));
  d.addEventListener('drop', e => { const f = e.dataTransfer && e.dataTransfer.files[0]; if (f) verifyFile(f); });
})();
const _v38_show = show;
show = function(id){ const r = _v38_show(id); if (id === 'verify') vTryDraw(); return r; };
const _v38_verifyFile = verifyFile;
verifyFile = async function(f){
  const r = await _v38_verifyFile(f);
  const h = $('#vOut h3');
  if (h){
    const ok = h.classList.contains('ok');
    h.insertAdjacentHTML('afterend', ok
      ? '<p class="vsay ok">쉽게 말하면: 이 답은 적힌 근거 그대로 다시 계산해도 <b>똑같이</b> 나와요. 결과가 옳다거나 투자해도 된다는 뜻은 아니에요.</p>'
      : $('#vOut table') ? '<p class="vsay ng">쉽게 말하면: 아래 「다름」 단계가 있어요. 그 뒤 자료가 고쳐졌거나(정정 공시 등) 근거 자료가 바뀌었을 수 있어요. 다른 단계의 이름을 보고 원문을 확인해 보세요.</p>'
      : '<p class="vsay ng">쉽게 말하면: 확인서 파일 자체가 처음 만들어진 것과 달라요(누군가 고쳤거나 일부가 잘린 파일). 보낸 사람에게 원본 파일을 다시 받아 넣어 보세요.</p>');
    const th = $('#vOut table th:nth-child(2)'); if (th) th.title = '지문: 그 단계의 자료와 계산을 짧은 문자열로 요약한 것. 한 글자만 달라도 바뀌어요.';
    const th3 = $('#vOut table th:nth-child(3)'); if (th3) th3.title = th.title;
  }
  return r;
};
const _v32_openAbout = openAbout;
openAbout = async function(){ learnMark('strip'); return _v32_openAbout(); };
document.addEventListener('click', e => {
  const t = e.target; if (!t.closest) return;
  if (t.closest('#answer .strip')) learnMark('strip');
  else if (t.closest('#answer [data-i]')) learnMark('evidence');
  else if (t.closest('#aThen')) learnMark('then');
}, true);

/* T2 가설 일지 — 내 가정 · 그때 증권사 · 그때 모두 · 실제(공시 뒤 채점) */
const _v32_renderForecast = renderForecast;
renderForecast = async function(a, key){
  const r = await _v32_renderForecast(a, key);
  const box = document.querySelector('#fc .crowdbox');
  if (box && $('#cEdit') && !box.querySelector('.jlink')){
    const l = document.createElement('a'); l.href = '#'; l.className = 'jlink'; l.textContent = '내 예상 채점표에서 왜 이렇게 봤는지 적기 →';
    l.onclick = ev => { ev.preventDefault(); openJournal(); }; box.appendChild(l);
  }
  learnRefresh(); return r;
};
const sgn = v => v == null ? '-' : (Number(v) > 0 ? '+' : Number(v) < 0 ? '−' : '') + Math.abs(Number(v)).toFixed(1) + '%';
const CLOSER = {me: ['내 가정이 더 가까웠어요', 'me'], broker: ['그때 증권사 집계가 더 가까웠어요', 'br'], tie: ['비슷했어요', 'tie']};
function jResult(e){
  if (e.status === 'scored') return `<b>오차 ${esc(sgn(e.mine_err_pct))}</b>${e.broker_err_pct != null ? `<br><span class="hint">증권사 ${esc(sgn(e.broker_err_pct))}</span>` : ''}${e.closer ? `<br><span class="jchip ${CLOSER[e.closer][1]}">${CLOSER[e.closer][0]}</span>` : ''}`;
  if (e.status === 'after') return '<span class="hint">공시 뒤에 적어 채점하지 않아요</span>';
  return '<span class="hint">실적 공시 전 — 공시되면 저절로 채점</span>';
}
async function openJournal(){
  show('journal'); $('#jBody').innerHTML = '<p class="hint">불러오는 중…</p>';
  let J; try { J = await api('/api/journal'); } catch(e){ $('#jBody').innerHTML = `<p class="ng">${esc(e.message)}</p>`; return; }
  const S = J.summary;
  if (!S.entries){
    $('#jBody').innerHTML = `<div class="box"><b>아직 적은 가정이 없어요</b><p>회사를 고르고 「증권사들은 실적을 어떻게 보나?」에서 올해 매출액·영업이익에 대한 내 가정을 적으면 여기에 쌓여요. 실적이 공시되면 저절로 채점돼요.</p><button id="jStart">가정 적으러 가기</button></div>`;
    $('#jStart').onclick = () => { show('home'); setDoor('test', true); toast('회사를 고른 뒤 「증권사들은 실적을 어떻게 보나?」를 눌러 보세요.'); };
    return;
  }
  const sum = `<div class="jsum"><div><b>${S.entries}</b><span>적은 가정</span></div><div><b>${S.scored}</b><span>채점됨</span></div><div><b>${S.pending}</b><span>발표 기다림</span></div><div><b>${S.notes}</b><span>이유 메모</span></div>
    ${S.scored ? (S.broker_abs_err != null
      ? `<div class="wide"><b>${esc(S.mine_abs_err)}% <small>vs</small> ${esc(S.broker_abs_err)}%</b><span>평균 오차(크기) — 나 vs 그때 증권사 · 내가 더 가까움 ${S.closer_me} · 증권사가 더 가까움 ${S.closer_broker}</span></div>`
      : `<div class="wide"><b>${esc(S.mine_abs_err)}%</b><span>내 평균 오차(크기) — 적은 날 승인된 증권사 전망이 없어 증권사와는 견주지 못했어요</span></div>`) : ''}</div>`;
  const groups = J.groups.map((g, gi) => `<section class="jg"><h3>${esc(g.name)} · ${g.fiscal_year}년 ${esc(g.metric_label)}</h3>
    <p class="hint">${g.actual ? `실제 <b>${esc(joS(g.actual.value_mn))}</b> (공시 ${esc(g.actual.disclosed)})` : '아직 실적이 공시되지 않았어요.'}</p>
    <div class="tw"><table class="jt"><tr><th>적은 날</th><th>내 가정</th><th>그때 증권사</th><th>그때 모두</th><th>결과</th><th>왜 이렇게 봤나</th></tr>
    ${g.entries.map((e, ei) => `<tr><td>${esc(String(e.submitted_at).slice(0, 10))}</td><td><b>${esc(joS(e.value_mn))}</b></td>
      <td>${e.broker_then ? `${esc(joS(e.broker_then.median))}<br><span class="hint">${e.broker_then.n}곳 · ${esc(e.broker_then.date)}${e.broker_then.thin ? ' · 적음' : ''}</span>` : '<span class="hint">없음</span>'}</td>
      <td>${e.crowd_then && e.crowd_then.shown ? `${esc(joS(e.crowd_then.median))}<br><span class="hint">${e.crowd_then.n}명</span>` : `<span class="hint">${e.crowd_then ? e.crowd_then.n : 0}명 — 5명부터</span>`}</td>
      <td>${jResult(e)}</td>
      <td class="jn">${e.note ? `<span>${esc(e.note)}</span><br>` : ''}<button class="ghost sm" data-j="${gi}:${ei}">${e.note ? '고치기' : '적기'}</button></td></tr>`).join('')}</table></div></section>`).join('');
  $('#jBody').innerHTML = sum + groups + `<p class="hint">${esc(J.rule)} 메모는 나만 봐요.</p>`;
  $('#jBody').querySelectorAll('[data-j]').forEach(b => b.onclick = async () => {
    const [gi, ei] = b.dataset.j.split(':').map(Number); const g = J.groups[gi], e = g.entries[ei];
    const v = prompt(`${g.name} ${g.fiscal_year}년 ${g.metric_label} — 왜 ${joS(e.value_mn)}로 봤나요? (300자까지, 비우면 지워요)`, e.note || '');
    if (v == null) return;
    try { await api('/api/journal/note', {method:'POST', body:{ticker: g.ticker, fiscal_year: g.fiscal_year, metric: g.metric, period: e.period, note: v}}); toast('적어 뒀어요. 실적이 나오면 이 이유와 결과를 나란히 볼 수 있어요.'); learnRefresh(); openJournal(); }
    catch(x){ toast(x.message); }
  });
}

/* T3 배우는 길 */
function needAns(){ show('home'); toast('먼저 회사를 고르고 질문 카드 하나를 눌러 답을 열어 주세요.'); }
const scrollTo_ = sel => { const el = document.querySelector(sel); if (el) el.scrollIntoView({behavior:'smooth', block:'center'}); };
const LEARN_GO = {
  ask: () => { show('home'); setDoor('ask', true); $('#coInput').focus(); },
  evidence: () => { if (!E.ans) return needAns(); show('answer'); scrollTo_('#answer .key'); toast('숫자 줄 하나를 눌러 보세요.'); },
  strip: () => { if (!E.ans) return openAbout(); show('answer'); scrollTo_('#answer .strip'); },
  then: () => { if (!E.ans) return needAns(); show('answer'); scrollTo_('#aThen'); },
  crowd: () => { show('home'); setDoor('test', true); toast('회사를 고른 뒤 「증권사들은 실적을 어떻게 보나?」를 눌러 보세요.'); },
  note: () => openJournal(),
  verify: () => show('verify'),
  share: () => { if (!E.ans) return needAns(); show('answer'); scrollTo_('#aShare'); },
  expert: () => { location.href = '/expert'; }};
async function openLearn(){
  show('learn'); await learnRefresh(); const L = JL.learn;
  if (!L){ $('#lBody').innerHTML = '<p class="ng">진도를 불러오지 못했어요.</p>'; return; }
  $('#lBody').innerHTML = `<div class="lbar"><div style="width:${Math.round(L.done / L.total * 100)}%"></div></div><p class="hint">${L.done} / ${L.total} 완료</p>
    ${L.stages.map(s => `<section class="lst"><h3>${esc(s.title)} <span class="hint">${s.done}/${s.tasks.length} · ${esc(s.sub)}</span></h3><ol class="ltasks">
      ${s.tasks.map(t => `<li class="${t.done ? 'done' : ''}${L.next === t.id ? ' lnext' : ''}"><span class="lc">${t.done ? '✓' : ''}</span><div><b>${esc(t.title)}</b>${L.next === t.id ? ' <span class="jchip me">다음 과제</span>' : ''}<br>${esc(t.how)}<br><span class="hint">왜? ${esc(t.why)}</span></div>
        <button class="${t.done ? 'ghost' : ''} sm" data-l="${esc(t.id)}">${t.done ? '다시 해 보기' : '해 보기'}</button></li>`).join('')}</ol></section>`).join('')}
    <p class="hint">진도는 이 브라우저 기준이에요. 실행·가정·확인서·공유 기록에서 저절로 알아내고, 화면 안에서만 하는 일(근거 열기·작동 원리 보기·날짜 바꾸기)은 눌렀을 때 체크돼요.</p>`;
  $('#lBody').querySelectorAll('[data-l]').forEach(b => b.onclick = () => (LEARN_GO[b.dataset.l] || (() => {}))());
}
$('#nJournal').onclick = openJournal; $('#nLearn').onclick = openLearn;
$('#jBack').onclick = $('#lBack').onclick = () => show('home');
learnRefresh();

/* ===== v0.34 readable-answers: 답 문장을 눈에 들어오게 나눠 보여 주기 =====
   글자는 하나도 바꾸지 않고 「배치」만 바꾼다(요점 / 항목 / 묶음 칩 / 주의 문장).
   숫자는 굵게(좋다·나쁘다 색은 쓰지 않음), 날짜는 고정폭, 괄호 안은 옅게. */
const PX_NOTE = /인과 아님|컨센서스 아님|보지 마세요|구분되지 않음|견주어 보세요|섞여 있어요|쓰지 않음|함께 움직인 기록|아니에요|아닙니다|주의/;
const PX_HEAD = /^(전체 )?\d[\d,]*\s?(건|곳|회|개|일|명|주|거래일째|일째)$/;
function pxSplit(s, seps){                     // 괄호·「」 밖에서만 나눈다
  const out = []; let depth = 0, cur = '';
  for (let i = 0; i < s.length; i++){
    const ch = s[i];
    if (ch === '(' || ch === '「' || ch === '[') depth++;
    else if ((ch === ')' || ch === '」' || ch === ']') && depth) depth--;
    if (!depth){
      const sep = seps.find(p => s.startsWith(p, i));
      if (sep){ out.push(cur); cur = ''; i += sep.length - 1; continue; }
    }
    cur += ch;
  }
  out.push(cur);
  return out.map(x => x.trim()).filter(Boolean);
}
function pxInline(t){
  let h = esc(t);
  h = h.replace(/\d{4}-\d{2}-\d{2}(?:~\d{4}-\d{2}-\d{2})?/g, m => `<span class="px-dt">${m}</span>`);
  h = h.replace(/(^|[\s(:→~])([+\-−]?\d[\d,]*(?:\.\d+)?\s?(?:%p|%|조\s?\d[\d,]*억\s?원|조\s?원|조원|조|억\s?원|억원|억 달러|원|주|배))(?![\d가-힣])/g,
    (m, a, n) => `${a}<b class="px-n">${n}</b>`);
  h = h.replace(/(상관 |^)([+\-−]\d+\.\d+)(?![\d%])/g, (m, a, n) => `${a}<b class="px-n">${n}</b>`);
  h = h.replace(/\(([^()]*)\)/g, '<span class="px-pa">($1)</span>');
  return h;
}
function pxChipLike(t){ return t.length <= 30 && /\d/.test(t) && !/:/.test(t); }
function pxBody(s){                              // 문장 하나 → HTML(줄 / 목록 / 칩)
  const own = pxSplit(s, [' / ']);
  if (own.length >= 2 && own.filter(x => /^[^:()「]{1,14}:\s/.test(x)).length >= 2)
    return `<ul class="px-ls">${own.map(x => { const m = x.match(/^([^:()「]{1,14}):\s+(.+)$/);
      return `<li>${m ? `<span class="px-lab">${esc(m[1])}</span>${pxInline(m[2])}` : pxInline(x)}</li>`; }).join('')}</ul>`;
  let label = '', rest = s;
  const m = s.match(/^([^:()「]{1,14}):\s+(.+)$/);
  if (m && !/\d{2}:\d{2}/.test(s)){ label = m[1]; rest = m[2]; }
  const lab = label ? `<span class="px-lab">${esc(label)}</span>` : '';
  const bySlash = rest.length > 30 ? pxSplit(rest, [' / ']) : [rest];
  if (bySlash.length >= 2)
    return `${lab}<ul class="px-ls">${bySlash.map(x => `<li>${pxInline(x)}</li>`).join('')}</ul>`;
  const tk = pxSplit(rest, [', ', ' · ', '; ']);
  if (tk.length >= 3 && tk.every(pxChipLike))
    return `<div class="px-row">${lab}<span class="px-chips">${tk.map(x => `<span class="px-chip">${pxInline(x)}</span>`).join('')}</span></div>`;
  if (tk.length >= 3 || (tk.length === 2 && rest.length > 44))
    return `${lab}<ul class="px-ls">${tk.map(x => `<li>${pxInline(x)}</li>`).join('')}</ul>`;
  return `<div class="px-line">${lab}${pxInline(rest)}</div>`;
}
function pretty(text){
  const t = String(text ?? '').trim();
  if (!t) return '';
  if (t.length <= 28 && !/ — |\. /.test(t)) return `<div class="px"><div class="px-lead">${pxInline(t)}</div></div>`;
  const sents = [];
  pxSplit(t, [' — ']).forEach((seg, si) => pxSplit(seg, ['. ']).forEach((x, i) => sents.push({x: x.replace(/\.$/, ''), seg: si, first: i === 0})));
  let html = '', lead = '', notes = [];
  sents.forEach((o, i) => {
    if (i > 0 && PX_NOTE.test(o.x) && o.x.length < 60){ notes.push(o.x); return; }
    if (i === 0){
      let s = o.x;
      const parts = pxSplit(s, [', ']);
      if (parts.length >= 2 && PX_HEAD.test(parts[0])){ lead = parts[0]; s = parts.slice(1).join(', '); }
      else if (sents.length > 1 && s.length <= 40 && pxSplit(s, [', ', ' · ', ' / ']).length === 1){ lead = s; return; }
      if (lead){ html += pxBody(s); return; }
    }
    html += pxBody(o.x);
  });
  return `<div class="px">${lead ? `<div class="px-lead">${pxInline(lead)}</div>` : ''}${html ? `<div class="px-body${lead ? ' ind' : ''}">${html}</div>` : ''}`
    + `${notes.length ? `<div class="px-note"><span aria-hidden="true">ⓘ</span> ${notes.map(pxInline).join(' · ')}</div>` : ''}</div>`;
}

/* ---------------- 주가와 「실적이 받치는 가치(V)」 그림 (v0.37.2) — 계산값을 그대로 그릴 뿐, 높고 낮음을 판단하지 않는다 ---------------- */
const ediWon = v => Math.round(v).toLocaleString('ko-KR') + '원';
const ediYr = e => e == null ? '-' : (e > 0 ? '+' : '') + e.toFixed(1) + '년';
function ediHtml(v){
  const S = (v && v.series) || []; if (!S.length) return '';
  const now = S[S.length - 1], M = v.methods || [];
  const max = Math.max(now.P, ...M.map(m => now['V_' + m.key] || 0)) * 1.06;
  const pct = x => Math.max(0, Math.min(100, x / max * 100)).toFixed(1);
  const rows = M.map(m => { const V = now['V_' + m.key], e = now['EDI_' + m.key];
    if (V == null || !(V > 0)) return `<li class="ev"><div class="en">${esc(m.label)}</div><div class="eg mute">이 방법으로는 계산을 보류했어요</div></li>`;
    return `<li class="ev"><div class="en">${esc(m.label)}</div>
      <div class="etrack" title="주황 막대 = 실적이 받치는 가치 V ${ediWon(V)} · 파란 세로선 = 주가 ${ediWon(now.P)}"><i class="ebar" style="width:${pct(V)}%"></i><i class="epx" style="left:${pct(now.P)}%"></i></div>
      <div class="eg">V <b>${ediWon(V)}</b> · 주가 ÷ V <b>${(now.P / V).toFixed(2)}배</b> · 앞선 햇수 <b>${ediYr(e)}</b></div></li>`; }).join('');
  return `<section class="edi" id="edi"><div class="relhead"><b>한눈에 보기</b> — 주가와 실적이 받치는 가치(V) <span class="mute">(${esc(now.date)} 기준)</span></div>
    <div class="eleg"><span><i class="sw px"></i>주가 ${ediWon(now.P)}</span><span><i class="sw v"></i>실적이 받치는 가치 V (가정 아래 계산값)</span></div>
    <ul class="evs">${rows}</ul>
    ${S.length >= 3 ? `<div class="relhead" style="margin-top:14px"><b>지나온 흐름</b> — 월말 주가와 V <span class="mute">(${esc(M[0] ? M[0].label : '')} · 단위 원)</span></div>
    <div class="ewrap"><svg class="echart" id="ediSvg" viewBox="0 0 680 270" role="img" aria-label="월말 주가와 실적이 받치는 가치 V의 흐름"></svg><div class="etip" id="ediTip" hidden></div></div>` : ''}
    <details class="relhow"><summary>이 그림을 읽는 법</summary><ul>
      <li>파란 선(주가)이 주황 선(V)보다 <b>위</b>에 있으면 주가가 실적보다 앞서 있고(앞선 햇수 +), <b>아래</b>에 있으면 실적이 주가보다 앞서 있어요(앞선 햇수 −).</li>
      <li>두 선의 간격이 벌어질수록 앞선 햇수의 크기가 커져요. 햇수는 「실적이 해마다 ${v.assumptions && v.assumptions.edi_growth != null ? esc(String(+(v.assumptions.edi_growth * 100).toFixed(1))) : '8'}%씩 자란다」는 가정으로 바꾼 값이에요.</li>
      <li>V는 자기자본비용·장기성장률 가정에 따라 크게 달라지는 계산값이에요. 주가가 얼마여야 한다는 뜻이 아니고, 사라·팔라는 뜻도 아니에요.</li>
      <li>정확한 숫자는 아래 「표로 보기」의 월말 표에 그대로 있어요.</li></ul></details></section>`;
}
function bindEdi(a){
  const svg = document.getElementById('ediSvg'); if (!svg || !a.edi) return;
  const S = a.edi.series, k = 'V_' + ((a.edi.methods[0] || {}).key || 'norm'), ek = k.replace('V_', 'EDI_');
  const W = 680, H = 270, L = 62, R = 96, T = 14, B = 30, n = S.length;
  const vals = S.flatMap(d => [d.P, d[k]]).filter(x => x != null && isFinite(x));
  let lo = Math.min(...vals), hi = Math.max(...vals); const pad = (hi - lo || hi || 1) * 0.08; lo = Math.max(0, lo - pad); hi += pad;
  const x = i => L + (n === 1 ? 0 : i / (n - 1) * (W - L - R)), y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const path = key => { let d = '', pen = false; S.forEach((p, i) => { const v = p[key]; if (v == null || !isFinite(v)) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); pen = true; }); return d; };
  const man = v => v >= 10000 ? (v / 10000).toLocaleString('ko-KR', {maximumFractionDigits: v >= 1e6 ? 0 : 1}) + '만' : Math.round(v).toLocaleString('ko-KR');
  let g = '';
  const raw = (hi - lo) / 4, mag = Math.pow(10, Math.floor(Math.log10(raw))), st = [1, 2, 2.5, 5, 10].map(m => m * mag).find(m => m >= raw);
  for (let v = Math.ceil(lo / st) * st; v <= hi + 1e-9; v += st){ g += `<line class="eg1" x1="${L}" x2="${W - R}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/><text class="et" x="${L - 8}" y="${(y(v) + 4).toFixed(1)}" text-anchor="end">${man(v)}</text>`; }
  const step = Math.max(1, Math.ceil(n / 6));
  S.forEach((p, i) => { if (i % step === 0 && i <= n - 1 - step * 0.8 || i === n - 1) g += `<text class="et" x="${x(i).toFixed(1)}" y="${H - 9}" text-anchor="${i === n - 1 ? 'end' : 'middle'}">${esc(p.date.slice(0, 7))}</text>`; });
  const last = S[n - 1], lv = [...S].reverse().find(p => p[k] != null);
  let yp = y(last.P), yv = lv ? y(lv[k]) : null;
  if (yv != null && Math.abs(yp - yv) < 15){ const mid = (yp + yv) / 2, up = yp <= yv; yp = mid + (up ? -8 : 8); yv = mid + (up ? 8 : -8); }
  g += `<path class="lv" d="${path(k)}"/><path class="lp" d="${path('P')}"/>`;
  g += `<circle class="dp" cx="${x(n - 1).toFixed(1)}" cy="${y(last.P).toFixed(1)}" r="4"/><text class="el" x="${(W - R + 9)}" y="${(yp + 4).toFixed(1)}">주가</text>`;
  if (lv) g += `<circle class="dv" cx="${x(S.indexOf(lv)).toFixed(1)}" cy="${y(lv[k]).toFixed(1)}" r="4"/><text class="el" x="${(W - R + 9)}" y="${(yv + 4).toFixed(1)}">V (계산값)</text>`;
  g += `<line id="ediX" class="ex" y1="${T}" y2="${H - B}" x1="0" x2="0" hidden/><circle id="ediDp" class="dp" r="4" hidden/><circle id="ediDv" class="dv" r="4" hidden/>
    <rect id="ediHit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>`;
  svg.innerHTML = g;
  const tip = document.getElementById('ediTip'), X = svg.querySelector('#ediX'), dp = svg.querySelector('#ediDp'), dv = svg.querySelector('#ediDv'), hit = svg.querySelector('#ediHit');
  const move = ev => { const r = svg.getBoundingClientRect(), sx = (ev.clientX - r.left) / r.width * W;
    const i = Math.max(0, Math.min(n - 1, Math.round((sx - L) / (W - L - R) * (n - 1)))), p = S[i];
    X.setAttribute('x1', x(i)); X.setAttribute('x2', x(i)); X.removeAttribute('hidden');
    dp.setAttribute('cx', x(i)); dp.setAttribute('cy', y(p.P)); dp.removeAttribute('hidden');
    if (p[k] != null) { dv.setAttribute('cx', x(i)); dv.setAttribute('cy', y(p[k])); dv.removeAttribute('hidden'); } else dv.setAttribute('hidden', '');
    tip.innerHTML = `<b>${esc(p.date)}</b><span><i class="sw px"></i>주가 ${ediWon(p.P)}</span><span><i class="sw v"></i>V ${p[k] == null ? '계산 보류' : ediWon(p[k])}</span><span>앞선 햇수 ${ediYr(p[ek])}</span>`;
    tip.hidden = false; const px = x(i) / W * r.width; tip.style.left = Math.max(0, px > r.width / 2 ? px - 196 : px + 12) + 'px'; tip.style.top = '8px'; };
  const out = () => { tip.hidden = true; [X, dp, dv].forEach(e => e.setAttribute('hidden', '')); };
  hit.addEventListener('mousemove', move); hit.addEventListener('mouseleave', out); hit.addEventListener('touchstart', e => move(e.touches[0]), {passive: true});
}

/* ---------------- 표를 그림으로 (v0.37.4) — 답에 든 표 값을 그대로 그릴 뿐, 좋고 나쁨을 판단하지 않는다 ---------------- */
const visNum = s => { const m = String(s == null ? '' : s).replace(/,/g, '').match(/-?\d+(\.\d+)?/); return m ? parseFloat(m[0]) : null; };
const visEok = v => v >= 10000 ? (v / 10000).toLocaleString('ko-KR', {maximumFractionDigits: 1}) + '조원' : Math.round(v).toLocaleString('ko-KR') + '억원';
function segCell(s){
  const t = String(s || ''); if (!t.trim()) return null;
  const y = t.match(/\(([+-]?\d+(\.\d+)?)%\)/);
  return {v: visNum(t.split('(')[0]), yoy: y ? parseFloat(y[1]) : null, calc: t.includes('※')};
}
function segSpark(cells, cols, name){
  const W = 168, H = 40, P = 5, vs = cells.map(c => c && c.v), ok = vs.filter(v => v != null);
  if (ok.length < 2) return '<span class="mute">분기 값이 2개 미만</span>';
  const lo = Math.min(...ok), hi = Math.max(...ok), x = i => P + i / (cells.length - 1) * (W - 2 * P), y = v => H - P - (hi === lo ? 0.5 : (v - lo) / (hi - lo)) * (H - 2 * P);
  let d = '', pen = false, dots = '';
  vs.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(v).toFixed(1); pen = true;
    dots += `<circle class="${i === vs.length - 1 ? 'sd on' : 'sd'}" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="${i === vs.length - 1 ? 3.5 : 2.2}"><title>${esc(name)} ${esc(cols[i])}: ${visEok(v)}${cells[i].yoy != null ? ` (전년 동기 대비 ${cells[i].yoy > 0 ? '+' : ''}${cells[i].yoy}%)` : ''}${cells[i].calc ? ' ※누적끼리 뺀 값' : ''}</title></circle>`; });
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)} 최근 ${cells.length}개 분기 흐름"><path d="${d}"/>${dots}</svg>`;
}
function segPane(t){
  const cols = t.cols.slice(1), rows = t.rows.map(r => ({name: r[0], cells: r.slice(1).map(segCell)})).filter(r => r.cells[r.cells.length - 1] && r.cells[r.cells.length - 1].v != null);
  if (!rows.length) return '<p class="mute">가장 최근 분기 값이 없어요.</p>';
  const max = Math.max(...rows.map(r => r.cells[r.cells.length - 1].v));
  return `<div class="segh"><span>구분</span><span>${esc(cols[0])} → ${esc(cols[cols.length - 1])} 흐름</span><span>${esc(cols[cols.length - 1])} 매출 (막대는 같은 눈금)</span></div>
    <ul class="segs">${rows.map(r => { const c = r.cells[r.cells.length - 1];
      return `<li class="seg"><div class="sn">${esc(r.name)}</div><div>${segSpark(r.cells, cols, r.name)}</div>
        <div><div class="strack"><i style="width:${(c.v / max * 100).toFixed(1)}%"></i></div><div class="sv"><b>${visEok(c.v)}</b>${c.yoy != null ? ` · 전년 동기 대비 <b>${c.yoy > 0 ? '+' : ''}${c.yoy}%</b>` : ''}${c.calc ? ' ※' : ''}</div></div></li>`; }).join('')}</ul>`;
}
function segHtml(a){
  const T = (a.tables || []).filter(t => /별 분기 매출 \(억원/.test(t.title)); if (!T.length) return '';
  const lab = t => t.title.split('별 분기 매출')[0];
  return `<section class="vis" id="segVis"><div class="relhead"><b>한눈에 보기</b> — 사업부별 분기 매출 <span class="mute">(정기보고서 주석 값)</span></div>
    ${T.length > 1 ? `<div class="fct">${T.map((t, i) => `<button data-seg="${i}"${i ? '' : ' class="on"'}>${esc(lab(t))}</button>`).join('')}</div>` : ''}
    ${T.map((t, i) => `<div class="segp" data-segp="${i}"${i ? ' hidden' : ''}>${segPane(t)}</div>`).join('')}
    <details class="relhow"><summary>이 그림을 읽는 법</summary><ul>
      <li>가운데 작은 선은 그 줄의 <b>흐름 모양</b>만 보여 줘요. 줄마다 눈금이 달라서, 선의 높이로 다른 줄과 크기를 비교하면 안 돼요. 점에 마우스를 올리면 분기별 값이 나와요.</li>
      <li>오른쪽 막대는 가장 최근 분기 매출이고, 모든 줄이 <b>같은 눈금</b>이라 크기를 서로 비교할 수 있어요.</li>
      <li>전년 동기 대비는 같은 보고서의 당기·전기 칸끼리 계산한 값이에요. ※는 누적 값끼리 뺀 값이에요(연간 − 9개월, 반기 − 1분기 등).</li>
      <li>늘고 줄어든 것이 좋은지 나쁜지는 판단하지 않아요. 정확한 숫자는 아래 「자세한 표」에 그대로 있어요.</li></ul></details></section>`;
}
function promHtml(a){
  const t = (a.tables || []).find(t => t.title.startsWith('자기주식 취득 결정과 결과')); if (!t || !t.rows.length) return '';
  const th = ((t.hint || '').match(/(\d+(\.\d+)?)%/g) || []).map(parseFloat).filter(v => v > 0 && v < 100).slice(0, 2);
  const rows = t.rows.slice(0, 8).map(r => { const rate = r[3] === '' ? null : parseFloat(r[3]), u = r[7] && r[7].url;
    return `<li class="pr"><div class="pd">${esc(r[0])}<span class="mute">${esc(r[5] || '')}</span></div>
      <div><div class="ptrack" title="막대 전체 = 예정 금액 ${esc(r[1])} · 채운 부분 = 실제 취득 ${esc(r[2])}">${rate == null ? '' : `<i class="pf" style="width:${Math.min(100, rate).toFixed(1)}%"></i>`}${th.map(v => `<i class="pt" style="left:${v}%"></i>`).join('')}</div>
      <div class="sv">${rate == null ? `예정 <b>${esc(r[1])}</b> · <b>${esc(r[4])}</b>` : `예정 <b>${esc(r[1])}</b> → 실제 <b>${esc(r[2])}</b> · 이행률 <b>${rate.toFixed(1)}%</b> · 규칙 분류 「${esc(r[4])}」`}${r[6] ? ` · 뒤이은 소각 결정 ${esc(r[6])}` : ''}${u ? ` · <a href="${esc(u)}" target="_blank" rel="noopener" data-u="1">원문</a>` : ''}</div></div></li>`; }).join('');
  return `<section class="vis" id="promVis"><div class="relhead"><b>한눈에 보기</b> — 자기주식 취득: 예정한 금액과 실제 취득 <span class="mute">(최근 ${Math.min(8, t.rows.length)}건${t.rows.length > 8 ? ` / 전체 ${t.rows.length}건은 아래 표` : ''})</span></div>
    <div class="eleg"><span><i class="sw pfc"></i>실제 취득 (막대 전체 = 예정 금액)</span>${th.length ? `<span><i class="sw ptc"></i>규칙 기준선 ${th.map(v => v + '%').join(' · ')}</span>` : ''}</div>
    <ul class="prs">${rows}</ul>
    <details class="relhow"><summary>이 그림을 읽는 법</summary><ul>
      <li>회색 칸 전체가 회사가 공시한 <b>예정 금액</b>이고, 채워진 부분이 결과보고서에 적힌 <b>실제 취득 금액</b>이에요.</li>
      <li>세로 기준선은 「이행 · 부분 이행 · 미달」을 나누는 규칙의 기준값이에요. 이름은 규칙에 따른 분류일 뿐, 회사에 대한 평가가 아니에요.</li>
      <li>막대가 비어 있으면 아직 진행 중이거나 결과보고서를 찾지 못한 결정이에요.</li></ul></details></section>`;
}
function visHtml(a){ return segHtml(a) + promHtml(a); }
function bindVis(){
  const s = document.getElementById('segVis'); if (!s) return;
  s.querySelectorAll('[data-seg]').forEach(b => b.onclick = () => { s.querySelectorAll('[data-seg]').forEach(x => x.classList.toggle('on', x === b)); s.querySelectorAll('[data-segp]').forEach(p => p.hidden = p.dataset.segp !== b.dataset.seg); });
}

function numCell(v){ const s = String(v ?? ''); return s.length <= 16 && /\d/.test(s) ? 'n' : ''; }   // v0.38 T2-3: 숫자 칸 표시
