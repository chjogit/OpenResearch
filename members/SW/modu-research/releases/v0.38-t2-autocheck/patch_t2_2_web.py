"""v0.38 T2-2 화면: 관심 종목 화면에 「새로 나온 공시」(자동 확인 결과 · 등급별 · 묶음) 칸을 더한다. 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])


def patch(rel, old, new, mark):
    p = N / rel; s = p.read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); return
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 바꿀 자리를 정확히 하나 찾지 못함({s.count(old)})')
    p.write_text(s.replace(old, new), encoding='utf-8', newline='')
    print(f'{rel}: 적용')


patch('web/easy.html',
      "    <h3>담아 둔 회사</h3>\n    <div id=\"wList\"></div>",
      "    <h3>새로 나온 공시 <span class=\"hint\">(자동 확인)</span></h3>\n    <div id=\"wNew\"></div>\n"
      "    <h3>담아 둔 회사</h3>\n    <div id=\"wList\"></div>",
      'id="wNew"')

JS = r'''
/* v0.38 T2-2 「새로 나온 공시」: 앱이 켜져 있는 동안 관심 종목 공시 목록을 자동 확인한 결과를 등급별로 보여 준다.
   1·2등급(숫자가 나오는 공시) → 상(꼭 알아 둘) → 중(알아 둘) 은 펼쳐 두고, 하(참고)는 접어 둔다. 같은 종류가 여러 건이면 한 줄로 묶는다. 판단(호재·악재) 없음. */
const kst = iso => iso ? new Date(iso).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—';
async function wLoadNew(){ W.ac = await api('/api/watch/autocheck'); wDrawNew(); }
function wRow(x){
  const tag = x.first_check ? ' <span class="hint">(등록 때 본 공시)</span>' : '';
  const fix = x.corrected ? ' <span class="b estimate">정정</span>' : '';
  let act = '';
  if (x.grade === 1 && x.can_compute) act = `<button data-calc="${esc(x.rcept_no)}" data-t="${esc(x.ticker)}">숫자로 보기</button>`;
  else if (x.grade === 1) act = '<span class="hint">계산 준비 중</span>';
  else if (x.grade === 2) act = '<span class="hint">가정이 필요한 공시(다음 단계)</span>';
  return `<tr><td>${esc(x.rcept_dt)}</td><td>${esc(x.name || x.ticker)}</td><td>${esc(x.label)}${fix}</td>
    <td><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.report_nm)}</a>${tag}</td><td>${act}</td></tr>`;
}
function wItem(x){
  if (!x.group) return wRow(x);
  return `<tr class="wgrp"><td>${esc(x.from)}~${esc(x.to)}</td><td>${esc(x.name || x.ticker)}</td>
    <td colspan="3"><details><summary>${esc(x.label)} <b>${x.count}건</b></summary>
    <table class="jt">${x.rows.map(wRow).join('')}</table></details></td></tr>`;
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
    ${any ? sec('숫자로 볼 수 있는 공시', '1·2등급', b.computable, true) + sec(`상 · ${a.tier_note['상']}`, '3등급', b['상'], true)
      + sec(`중 · ${a.tier_note['중']}`, '3등급', b['중'], true) + sec(`하 · ${a.tier_note['하']}`, '3등급 · 접어 둠', b['하'], false)
      : '<p class="hint">관심 종목의 새 공시가 아직 없어요.</p>'}
    <p class="hint">${esc(a.note)} 등급은 제목만 보고 나눈 것이고, 좋다·나쁘다를 뜻하지 않아요.</p>`;
  $('#wCheck').onclick = async () => {
    const btn = $('#wCheck'); btn.disabled = true; btn.textContent = '확인하는 중…';
    try { const r = await api('/api/watch/autocheck/run', {method: 'POST'}); toast(`${r.status_label}: ${r.message || ''}`); }
    catch(e){ toast(e.message); }
    await wLoadNew().catch(e => toast(e.message));
  };
  $('#wNew').querySelectorAll('[data-calc]').forEach(btn => btn.onclick = async () => {
    btn.disabled = true;
    try { await api('/api/watch/fetch', {method: 'POST', body: {ticker: btn.dataset.t, rcept_no: btn.dataset.calc}}); runFiling(btn.dataset.t, btn.dataset.calc); }
    catch(e){ toast(e.message); btn.disabled = false; }
  });
}
'''
patch('web/watch.js', "$('#nWatch').onclick = () => openWatch()", JS + "$('#nWatch').onclick = () => openWatch()", 'function wLoadNew')
patch('web/watch.js', "  await Promise.all([wLoadList(), wLoadPick()]).catch(e => toast(e.message));",
      "  await Promise.all([wLoadList(), wLoadPick(), wLoadNew()]).catch(e => toast(e.message));   // v0.38 T2-2 wLoadNew", 'wLoadNew()]')
patch('web/easy.css', ".wfil td:first-child,.wfil th:first-child{white-space:nowrap}",
      ".wfil td:first-child,.wfil th:first-child{white-space:nowrap}\n"
      "/* v0.38 T2-2 새로 나온 공시 */\n"
      ".wstat{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;margin:4px 0 8px}.wstat p{margin:0}\n"
      ".wsec{margin:6px 0}.wsec>summary{cursor:pointer;padding:6px 0}\n"
      ".wgrp details>summary{cursor:pointer}.wgrp details table{margin-top:6px}\n"
      "#wNew td:first-child,#wNew th:first-child{white-space:nowrap}\n"
      "@media (max-width:520px){.wstat{flex-direction:column}}",
      'v0.38 T2-2 새로 나온 공시')
