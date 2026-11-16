/* v0.35 증권사 전망 — 종목별로 나눠 읽기 쉽게.
   app.js의 renderTimeline·renderCompare를 덮어쓴다(app.js는 건드리지 않음).
   원칙: 한 그림에는 한 종목만. 굵은 선 = 증권사별 최신 목표주가의 중앙값(120일 안, 3곳 이상일 때만).
   좋고 나쁨 색을 쓰지 않는다(상향·하향은 기호로만). 컨센서스 아님. */
(function(){
  if (document.getElementById('tp35css')) return;
  const st = document.createElement('style'); st.id = 'tp35css';
  st.textContent = `
  .tp-pick{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 12px;padding:10px 12px;background:#f8f7f4;border:1px solid var(--line);border-radius:8px}
  .tp-pick label{font-weight:600}.tp-pick select{font-size:14px;padding:5px 8px;min-width:260px}
  .tp-pick .chip{border-radius:999px;padding:3px 11px;font-size:12.5px;background:#fff;color:#1f2328}
  .tp-pick .chip.on{background:#1f2328;color:#fff;border-color:#1f2328}
  .tp-head{display:flex;align-items:baseline;gap:10px;margin:2px 0 10px}.tp-head h3{margin:0;font-size:19px}
  .tp-kpis{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin-bottom:12px}
  .tp-kpi{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 12px}
  .tp-kpi .k{font-size:12px;color:var(--mute)}.tp-kpi .v{font-size:22px;font-weight:700;line-height:1.25;margin-top:2px}
  .tp-kpi .s{font-size:12px;color:var(--mute);margin-top:2px}
  .tp-warn{background:#fff8e6;border:1px solid #f1d38a;border-radius:8px;padding:8px 12px;margin:0 0 12px;font-size:13px}
  .tp-chart{background:#fff;border:1px solid var(--line);border-radius:8px;padding:8px 8px 4px}
  .tp-chart svg{width:100%;height:auto;display:block}
  .tp-legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12.5px;padding:6px 8px 4px;color:#333}
  .tp-legend i{display:inline-block;width:22px;height:0;border-top:3px solid #1f2328;vertical-align:middle;margin-right:5px}
  .tp-legend i.band{height:10px;border:0;background:#e9e7e1}.tp-legend i.one{border-top:2px solid #b8bec7}
  .tp-legend i.hl{border-top:3px solid #e8590c}
  .tp-table{width:100%;border-collapse:collapse;font-size:13.5px;margin-top:6px}
  .tp-table th{position:sticky;top:0;background:#f3f1ec;text-align:left;font-weight:600;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}
  .tp-table td{padding:8px 10px;border-bottom:1px solid #eeece6;vertical-align:middle;white-space:nowrap}
  .tp-table td.n{text-align:right;font-variant-numeric:tabular-nums}
  .tp-table tr{cursor:pointer}.tp-table tr:hover td{background:#faf9f6}.tp-table tr.on td{background:#fff1e6}
  .tp-up,.tp-dn,.tp-eq{font-weight:600}.tp-dn{color:#1f2328}.tp-eq{color:var(--mute);font-weight:400}
  .tp-sub{color:var(--mute);font-size:12px}
  .tp-notes{font-size:12.5px;color:var(--mute);line-height:1.6;margin-top:10px}
  #bBody h3.tp-h{font-size:15px;margin:18px 0 4px}`;
  document.head.appendChild(st);
})();

const TP_DAY = 864e5, TP_WINDOW = 120;
const tpWon = v => v == null ? '—' : (v >= 10000 ? (Math.round(v / 1000) / 10).toLocaleString('ko-KR', {maximumFractionDigits: 1}) + '만원' : Number(v).toLocaleString('ko-KR') + '원');
const tpWonFull = v => v == null ? '—' : Number(v).toLocaleString('ko-KR') + '원';
const tpT = s => +new Date(s + 'T00:00:00');
const tpYmd = t => { const d = new Date(t); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const tpMed = a => { const s = [...a].sort((x, y) => x - y), n = s.length; return n ? (n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2) : null; };
function tpStats(vals){ const v = vals.filter(x => x != null && x !== '').map(Number); if (!v.length) return null;
  return {min: Math.min(...v), median: tpMed(v), max: Math.max(...v), count: v.length}; }

function tpTickers(d){
  const cnt = {}; d.rows.forEach(r => { if (r.ticker) cnt[r.ticker] = (cnt[r.ticker] || 0) + 1; });
  const names = d.companies || {};
  return Object.entries(cnt).map(([t, n]) => ({t, n, name: names[t] || t})).sort((a, b) => b.n - a.n || a.name.localeCompare(b.name, 'ko'));
}
function tpCurrent(d){
  const list = tpTickers(d);
  if (!S.bTicker || !list.some(x => x.t === S.bTicker)) S.bTicker = (list.find(x => x.t === '005930') || list[0] || {}).t || null;
  return list;
}
function tpPickerHtml(d){
  const list = tpCurrent(d), top = list.slice(0, 6);
  return `<div class="tp-pick"><label for="tpSel">종목</label>
    <select id="tpSel">${list.map(x => `<option value="${esc(x.t)}" ${x.t === S.bTicker ? 'selected' : ''}>${esc(x.name)} (${esc(x.t)}) · 보고서 ${x.n}건</option>`).join('')}</select>
    <span class="tp-sub">보고서 많은 순:</span>${top.map(x => `<button class="chip ${x.t === S.bTicker ? 'on' : ''}" data-tpt="${esc(x.t)}">${esc(x.name)}</button>`).join('')}
    <span class="tp-sub">· 전체 ${list.length}개 종목</span></div>`;
}
function tpBindPicker(){
  const go = t => { S.bTicker = t; S.tpFocus = null; openBroker(); };
  const sel = $('#tpSel'); if (sel) sel.onchange = () => go(sel.value);
  document.querySelectorAll('[data-tpt]').forEach(b => b.onclick = () => go(b.dataset.tpt));
}
function tpFilter(d){
  const rows = d.rows.filter(r => r.ticker === S.bTicker);
  const summary = {};
  d.columns.forEach(k => {
    summary[k] = {all: tpStats(rows.map(r => r.cells[k] && ['approved', 'proposed'].includes(r.cells[k].state) ? r.cells[k].value_mn : null)),
                  approved: tpStats(rows.map(r => r.cells[k] && r.cells[k].state === 'approved' ? r.cells[k].value_mn : null))};
  });
  summary.target_price = {all: tpStats(rows.map(r => r.target_price))};
  return {...d, rows, summary};
}

/* ---- 비교표: 종목 하나만 ---- */
const _tpOrigCompare = renderCompare;
renderCompare = function(d){
  const head = tpPickerHtml(d);
  const dd = tpFilter(d);
  _tpOrigCompare(dd);
  $('#bBody').insertAdjacentHTML('afterbegin', head);
  tpBindPicker();
};

/* ---- 목표주가 변화 ---- */
function tpNice(lo, hi, n){
  const raw = (hi - lo) / n, p = Math.pow(10, Math.floor(Math.log10(raw))), f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * p;
}
function tpSeries(rows){
  const by = {};
  rows.forEach(r => { (by[r.broker] = by[r.broker] || {reports: [], missing: 0, prior: null}); const b = by[r.broker];
    if (r.target_price && r.report_date) b.reports.push({date: r.report_date, t: tpT(r.report_date), tp: Number(r.target_price), opinion: r.opinion, prior: r.tp_prior ? Number(r.tp_prior) : null, title: r.title});
    else b.missing++; });
  Object.values(by).forEach(b => b.reports.sort((x, y) => x.t - y.t));
  return by;
}
function tpMedianPath(by, t0, t1){
  const days = []; for (let t = t0; t <= t1; t += TP_DAY) days.push(t);
  return days.map(t => {
    const vals = [];
    Object.values(by).forEach(b => { let last = null; for (const r of b.reports) { if (r.t <= t) last = r; else break; }
      if (last && t - last.t <= TP_WINDOW * TP_DAY) vals.push(last.tp); });
    return vals.length >= 3 ? {t, med: tpMed(vals), lo: Math.min(...vals), hi: Math.max(...vals), n: vals.length} : {t, n: vals.length};
  });
}
function tpSpark(reps){
  if (reps.length < 2) return '<span class="tp-sub">—</span>';
  const w = 90, h = 22, v = reps.map(r => r.tp), lo = Math.min(...v), hi = Math.max(...v), t0 = reps[0].t, t1 = reps[reps.length - 1].t || t0 + 1;
  const X = t => 2 + (t - t0) / Math.max(1, t1 - t0) * (w - 4), Y = x => hi === lo ? h / 2 : 3 + (1 - (x - lo) / (hi - lo)) * (h - 6);
  let pts = []; reps.forEach((r, i) => { if (i) pts.push(`${X(r.t)},${Y(reps[i - 1].tp)}`); pts.push(`${X(r.t)},${Y(r.tp)}`); });
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="#495057" stroke-width="1.6" points="${pts.join(' ')}"/><circle cx="${X(reps[reps.length-1].t)}" cy="${Y(reps[reps.length-1].tp)}" r="2.5" fill="#1f2328"/></svg>`;
}
function tpChange(b){
  const r = b.reports, last = r[r.length - 1];
  let prev = r.length > 1 ? r[r.length - 2].tp : null, how = '직전 보고서';
  if (prev == null && last && last.prior) { prev = last.prior; how = '본문의 「기존」'; }
  if (prev == null) return {html: '<span class="tp-eq">첫 보고서</span>', dir: 0};
  const pct = (last.tp - prev) / prev * 100;
  if (Math.abs(pct) < 0.5) return {html: `<span class="tp-eq">유지</span> <span class="tp-sub">(${how})</span>`, dir: 0};
  return {html: `<span class="${pct > 0 ? 'tp-up' : 'tp-dn'}">${pct > 0 ? '▲' : '▼'} ${Math.abs(pct).toFixed(1)}%</span> <span class="tp-sub">(${tpWon(prev)}에서 · ${how})</span>`, dir: pct > 0 ? 1 : -1, t: last.t};
}

function renderTimeline(d){
  const head = tpPickerHtml(d);
  const rows = d.rows.filter(r => r.ticker === S.bTicker);
  const name = (d.companies || {})[S.bTicker] || S.bTicker;
  const by = tpSeries(rows), brokers = Object.entries(by).filter(([, b]) => b.reports.length);
  const missing = Object.values(by).reduce((a, b) => a + b.missing, 0);
  if (!brokers.length) { $('#bBody').innerHTML = head + `<p>이 종목은 본문에서 읽힌 목표주가가 없습니다${missing ? ` (보고서 ${missing}건 모두 미기재)` : ''}.</p>`; tpBindPicker(); return; }

  const all = brokers.flatMap(([, b]) => b.reports);
  const tMin = Math.min(...all.map(r => r.t)), tMax = Math.max(...all.map(r => r.t));
  const t0 = tMin - 3 * TP_DAY, t1 = Math.max(tMax + 7 * TP_DAY, tMin + 30 * TP_DAY);
  const med = tpMedianPath(by, tMin, tMax);
  const lastMed = [...med].reverse().find(m => m.med != null);

  // 최신 상태(마지막 보고서 날 기준, 120일 안 증권사별 최신)
  const latest = brokers.map(([nm, b]) => ({nm, r: b.reports[b.reports.length - 1]})).filter(x => tMax - x.r.t <= TP_WINDOW * TP_DAY);
  const lv = latest.map(x => x.r.tp);
  const ch = brokers.map(([nm, b]) => ({nm, ...tpChange(b)}));
  const recent = ch.filter(c => c.t && tMax - c.t <= 90 * TP_DAY);
  const up = recent.filter(c => c.dir > 0).length, dn = recent.filter(c => c.dir < 0).length;

  // 그림
  const W = 980, H = 400, L = 78, R = 120, T = 22, B = 44;
  const vals = all.map(r => r.tp); let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { lo *= 0.9; hi *= 1.1; }
  const step = tpNice(lo, hi, 5); const y0 = Math.floor((lo - step * 0.3) / step) * step, y1 = Math.ceil((hi + step * 0.3) / step) * step;
  const X = t => L + (t - t0) / (t1 - t0) * (W - L - R), Y = v => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  let g = '';
  for (let v = y0; v <= y1 + 1e-6; v += step) g += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#ecebe6"/><text x="${L - 10}" y="${Y(v) + 4.5}" text-anchor="end" font-size="13" fill="#6b7280">${tpWon(v)}</text>`;
  const d0 = new Date(t0); let m = new Date(d0.getFullYear(), d0.getMonth() + 1, 1); let prevY = null;
  while (+m <= t1) { const x = X(+m); const lab = (prevY !== m.getFullYear() ? `${String(m.getFullYear()).slice(2)}년 ` : '') + `${m.getMonth() + 1}월`; prevY = m.getFullYear();
    g += `<line x1="${x}" x2="${x}" y1="${T}" y2="${H - B}" stroke="#ecebe6"/><text x="${x}" y="${H - B + 20}" text-anchor="middle" font-size="13" fill="#6b7280">${lab}</text>`;
    m = new Date(m.getFullYear(), m.getMonth() + 1, 1); }
  g += `<line x1="${L}" x2="${W - R}" y1="${H - B}" y2="${H - B}" stroke="#c9c6be"/>`;
  // 범위 띠 + 중앙값
  const segs = []; let cur = [];
  med.forEach(p => { if (p.med != null) cur.push(p); else if (cur.length) { segs.push(cur); cur = []; } }); if (cur.length) segs.push(cur);
  segs.forEach(s => {
    const top = s.map(p => `${X(p.t)},${Y(p.hi)}`), bot = s.slice().reverse().map(p => `${X(p.t)},${Y(p.lo)}`);
    g += `<polygon points="${top.concat(bot).join(' ')}" fill="#e9e7e1" opacity=".85"/>`;
  });
  // 증권사 계단선(옅게)
  const focus = S.tpFocus && by[S.tpFocus] ? S.tpFocus : null;
  const stepPts = b => { const p = []; b.reports.forEach((r, i) => { if (i) p.push(`${X(r.t)},${Y(b.reports[i - 1].tp)}`); p.push(`${X(r.t)},${Y(r.tp)}`); });
    const last = b.reports[b.reports.length - 1]; p.push(`${X(Math.min(t1 - 2 * TP_DAY, last.t + TP_WINDOW * TP_DAY, tMax))},${Y(last.tp)}`); return p.join(' '); };
  brokers.forEach(([nm, b]) => { if (nm === focus) return;
    g += `<polyline fill="none" stroke="#b8bec7" stroke-width="1.6" points="${stepPts(b)}"/>`;
    b.reports.forEach(r => g += `<circle cx="${X(r.t)}" cy="${Y(r.tp)}" r="3.4" fill="#fff" stroke="#9aa1ab" stroke-width="1.4"><title>${esc(nm)} · ${r.date} · 목표주가 ${tpWonFull(r.tp)}${r.opinion ? ' · ' + esc(r.opinion) : ''}</title></circle>`); });
  segs.forEach(s => g += `<polyline fill="none" stroke="#1f2328" stroke-width="3.2" stroke-linejoin="round" points="${s.map(p => `${X(p.t)},${Y(p.med)}`).join(' ')}"/>`);
  if (lastMed) g += `<text x="${X(lastMed.t) + 8}" y="${Y(lastMed.med) + 5}" font-size="14" font-weight="700" fill="#1f2328">중앙값 ${tpWon(lastMed.med)}</text>`;
  if (focus) { const b = by[focus];
    g += `<polyline fill="none" stroke="#e8590c" stroke-width="3" points="${stepPts(b)}"/>`;
    b.reports.forEach((r, i) => { const changed = !i || r.tp !== b.reports[i - 1].tp;
      g += `<circle cx="${X(r.t)}" cy="${Y(r.tp)}" r="5" fill="#e8590c"><title>${esc(focus)} · ${r.date} · ${tpWonFull(r.tp)}</title></circle>`;
      if (changed) g += `<text x="${X(r.t)}" y="${Y(r.tp) + 22}" text-anchor="middle" font-size="13" font-weight="700" fill="#c2410c" paint-order="stroke" stroke="#fff" stroke-width="4">${tpWon(r.tp)}</text>`; });
    const lr = b.reports[b.reports.length - 1]; g += `<text x="${W - R + 8}" y="${Y(lr.tp) + (lastMed && Math.abs(Y(lr.tp) - Y(lastMed.med)) < 16 ? 18 : 5)}" font-size="13" font-weight="700" fill="#c2410c">${esc(focus)}</text>`; }

  const fewNote = latest.length < 3 ? `<div class="tp-warn">최근 120일 안에 목표주가를 낸 증권사가 ${latest.length}곳뿐이라 굵은 중앙값 선을 그리지 않습니다. <b>추이로 보지 마세요.</b></div>` : '';
  const sorted = brokers.slice().sort((a, b) => b[1].reports[b[1].reports.length - 1].t - a[1].reports[a[1].reports.length - 1].t);
  const table = `<table class="tp-table"><tr><th>증권사</th><th>최근 보고서</th><th style="text-align:right">최근 목표주가</th><th>직전 대비</th><th>흐름</th><th style="text-align:right">보고서</th><th>의견</th></tr>
    ${sorted.map(([nm, b]) => { const r = b.reports[b.reports.length - 1], c = tpChange(b), old = tMax - r.t > TP_WINDOW * TP_DAY;
      return `<tr data-tpb="${esc(nm)}" class="${nm === focus ? 'on' : ''}"><td><b>${esc(nm)}</b>${old ? ' <span class="tp-sub">(120일 지남 · 집계 제외)</span>' : ''}</td><td>${esc(r.date)}</td>
        <td class="n"><b>${tpWonFull(r.tp)}</b></td><td>${c.html}</td><td>${tpSpark(b.reports)}</td><td class="n">${b.reports.length}${b.missing ? ` <span class="tp-sub">+미기재 ${b.missing}</span>` : ''}</td><td>${esc(r.opinion || '—')}</td></tr>`; }).join('')}</table>`;

  $('#bBody').innerHTML = head + `
    <div class="tp-head"><h3>${esc(name)} 목표주가 변화</h3><span class="tp-sub">${esc(S.bTicker)} · 보고서 ${rows.length}건 · 증권사 ${brokers.length}곳 · 마지막 보고서 ${tpYmd(tMax)}</span></div>
    <div class="tp-kpis">
      <div class="tp-kpi"><div class="k">최근 목표주가 중앙값</div><div class="v">${latest.length >= 3 ? tpWon(tpMed(lv)) : '—'}</div><div class="s">증권사별 최신 값 · 120일 안 ${latest.length}곳</div></div>
      <div class="tp-kpi"><div class="k">범위 (최저 ~ 최고)</div><div class="v" style="font-size:18px">${lv.length ? tpWon(Math.min(...lv)) + ' ~ ' + tpWon(Math.max(...lv)) : '—'}</div><div class="s">${lv.length >= 2 ? '최고가 최저의 ' + (Math.max(...lv) / Math.min(...lv)).toFixed(2) + '배' : ''}</div></div>
      <div class="tp-kpi"><div class="k">최근 90일 바꾼 증권사</div><div class="v">▲ ${up} · ▼ ${dn}</div><div class="s">같은 증권사 직전 값 대비(±0.5% 안은 유지)</div></div>
      <div class="tp-kpi"><div class="k">목표주가 미기재</div><div class="v">${missing}건</div><div class="s">본문 글자에서 읽지 못한 보고서</div></div>
    </div>${fewNote}
    <div class="tp-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(name)} 증권사 목표주가 변화">${g}</svg>
      <div class="tp-legend"><span><i></i>중앙값 (증권사별 최신 · 120일 안 · 3곳 이상)</span><span><i class="band"></i>최저~최고 범위</span><span><i class="one"></i>증권사 하나</span>${focus ? `<span><i class="hl"></i>${esc(focus)} (표에서 다시 누르면 해제)</span>` : '<span class="tp-sub">아래 표에서 증권사를 누르면 그 선만 진하게 보여요.</span>'}</div></div>
    <h3 class="tp-h">증권사별 최근 목표주가</h3>
    <div class="tp-sub">최근 보고서 순 · 행을 누르면 그림에서 강조</div>${table}
    <div class="tp-notes">• 컨센서스가 아닙니다. 사용자가 넣은 보고서에서 읽은 숫자이며, 같은 증권사가 그 사이 바꾼 목표주가는 보고서가 없으면 반영되지 않습니다.<br>
    • 선은 다음 보고서가 나올 때까지 같은 값이 유지된다고 보고 계단 모양으로 그렸습니다(마지막 보고서 뒤 최대 120일).<br>
    • 「본문의 「기존」」 = 보고서 본문에 적힌 이전 목표주가와 비교한 것입니다(날짜 미상).<br>
    • 목표주가는 판단 재료를 비교해 보는 용도로만 이 화면에 보입니다. 앱의 계산(N02)에는 들어가지 않습니다.</div>`;
  tpBindPicker();
  document.querySelectorAll('[data-tpb]').forEach(tr => tr.onclick = () => { S.tpFocus = S.tpFocus === tr.dataset.tpb ? null : tr.dataset.tpb; renderTimeline(d); });
}
