/* ---------- 연구용 데이터: KIS 현재가 · 컨센서스 (엔진 v0.39.2, PM 2026-11-15) ----------
   엔진 스위치(MODU_SHOW_QUOTES·MODU_SHOW_CONSENSUS)가 켜져 있을 때만 보인다. 「연구용(계약 전)」 표시를 숨기지 않는다.
   시세는 회사 이름 옆에만 — 답 카드·근거 확인서에는 넣지 않는다. 오르내림을 색으로 나타내지 않는다(기호·숫자만). */
let rdFlags = null;
async function rdFlagsGet() { if (!rdFlags) { try { rdFlags = await api('/api/research/flags'); } catch (e) { rdFlags = { quotes: false, consensus: false }; } } return rdFlags; }
const rdHm = (iso) => { const d = new Date(iso); if (isNaN(d)) return ''; const k = new Date(d.getTime() + 9 * 3600 * 1000).toISOString(); return k.slice(11, 16); };
async function showQuote(t, el) {
  if (!el || !(await rdFlagsGet()).quotes) return;
  let q; try { q = await api(`/api/quote/${encodeURIComponent(t)}`); } catch (e) { return; }
  if (!q.enabled) return;
  const old = el.querySelector('.rd-quote'); if (old) old.remove();
  const pct = q.pct == null ? '' : ` · 전일 대비 ${q.pct > 0 ? '▲ +' : q.pct < 0 ? '▼ ' : ''}${Number(q.pct).toFixed(2)}%`;
  el.insertAdjacentHTML('beforeend', q.available
    ? `<span class="chip rd-quote" title="${esc(q.label)} — ${esc(q.note)}">현재가 ${Number(q.price).toLocaleString('ko-KR')}원${pct} · ${esc(rdHm(q.as_of))} · 연구용</span>`
    : `<span class="chip rd-quote" title="${esc(q.note)}">시세 없음 · 연구용</span>`);
}
const rdMoney = (mn) => { const v = Number(mn); if (!isFinite(v)) return '—'; return Math.abs(v) >= 1e6 ? `${(v / 1e6).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}조 원` : `${(v / 100).toLocaleString('ko-KR', { maximumFractionDigits: 0 })}억 원`; };
async function viewConsensus() {
  crumbs(-1); tab('#/consensus');
  view().innerHTML = `<section class="rs-head"><h2>컨센서스 (연구용)</h2><p>${esc(S.company.name)} · 기준 ${esc(fmtCut(cutoff()))} · 회사는 「질문하기」에서 바꿔요</p></section><div id="rdC" class="rs-view"><div class="rs-empty">불러오는 중…</div></div>`;
  let c; try { c = await api(`/api/consensus/${encodeURIComponent(S.company.ticker)}?${qs({ cutoff: cutoff() })}`); } catch (e) { $('#rdC').innerHTML = errBox(e); return; }
  if (!c.enabled) { $('#rdC').innerHTML = `<div class="rs-box unk"><p>${esc(c.note)}</p></div>`; return; }
  const key = (r) => `${r.fiscal_year}|${r.metric}`;
  const prov = {}; c.provider.forEach((r) => { (prov[key(r)] = prov[key(r)] || []).push(r); });
  const keys = [...new Set(c.broker.map(key).concat(c.provider.map(key)))].sort();
  const bro = Object.fromEntries(c.broker.map((r) => [key(r), r]));
  const rows = keys.map((k) => {
    const [fy, m] = k.split('|'); const b = bro[k]; const ps = prov[k] || [];
    const label = (b && b.metric_label) || (ps[0] && ps[0].metric_label) || m;
    return `<tr><td class="rs-date">${esc(fy)}</td><td>${esc(label)}</td>
      <td>${b ? `<b>${esc(rdMoney(b.median_mn))}</b><div class="muted" style="font-size:12px">범위 ${esc(rdMoney(b.min_mn))} ~ ${esc(rdMoney(b.max_mn))} · 보고서 ${esc(b.n)}곳 · <span class="rs-date">${esc(b.date)}</span>${b.thin ? ' · 3곳 미만이라 추이로 보지 마세요' : ''}</div>` : '<span class="muted">승인된 보고서 없음</span>'}</td>
      <td>${ps.length ? ps.map((p) => `<b>${esc(rdMoney(p.value_mn))}</b> <span class="muted" style="font-size:12px">${esc(p.provider)}${p.n_estimates != null ? ` · 추정 ${esc(p.n_estimates)}곳` : ''} · <span class="rs-date">${esc(p.as_of)}</span></span>`).join('<br>') : '<span class="muted">계약 전 — 없음</span>'}</td></tr>`;
  }).join('');
  $('#rdC').innerHTML = `<div class="rs-box not"><h3><i class="ti ti-info-circle" aria-hidden="true"></i>이 화면이 아닌 것</h3><p>${esc(c.note)}</p></div>
    ${rows ? `<div class="rs-tbl"><table><thead><tr><th>연도</th><th>항목</th><th>① 증권사 보고서 집계(앱 계산)</th><th>② 정식 데이터(계약 뒤 파일)</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="rs-empty">이 회사는 아직 승인된 증권사 보고서도, 정식 데이터 파일도 없어요.</div>'}
    <details class="rs-fold"><summary>정식 데이터 파일 넣는 법</summary><div>
      <p class="muted" style="font-size:13px">계약한 곳에서 받은 자료를 아래 칸 이름의 CSV로 저장해 엔진 옆 <span class="rs-date">_sources/consensus/</span> 폴더에 넣으면 이 화면 ②칸에 바로 나와요. 값은 백만원 단위 정수, 날짜는 YYYY-MM-DD, 항목은 revenue·operatingProfit·netIncome.</p>
      <p class="rs-date" style="font-size:13px">${esc(c.provider_format)}</p>
      <p class="muted" style="font-size:13px">지금 들어 있는 파일: ${c.provider_files.length ? c.provider_files.map(esc).join(', ') : '없음'}</p>
      ${c.provider_problems.length ? `<ul class="muted" style="font-size:13px;padding-left:20px">${c.provider_problems.map((p) => `<li>${esc(p)}</li>`).join('')}</ul>` : ''}</div></details>
    <div class="rs-ai"><span>AI 모델 호출</span><span class="n">${esc(c.model_calls ?? 0)}회</span></div>`;
}

