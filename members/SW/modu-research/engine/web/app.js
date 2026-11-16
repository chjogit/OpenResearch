'use strict';
/* 모두의리서치 노드 0.1 — canvas UI. Vanilla JS, no external requests. */
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const STATUS = {waiting:'대기', running:'실행 중', succeeded:'성공', partial:'일부 확인', held:'보류', not_connected:'미연결',
  failed:'실패', cancelled:'취소', interrupted:'중단', cancelling:'취소 요청됨'};
const IMPL = {real:'실동작', partial:'일부', not_connected:'미연결'};
const TIER = {basic:'기본', extension:'확장', tool:'공통도구', addon:'부가'};
const ACTIVE = ['waiting','running'];

const S = {reg:null, specs:{}, doc:null, wfId:null, wfVersion:null, dirty:false, editedSinceRun:false,
  run:null, runId:null, poll:null, sel:null, selEdge:null, armed:null, issues:[], scale:1, pan:{x:20,y:20}, tab:'config', history:[]};

/* ---------------- api ---------------- */
function csrf(){ const m = document.cookie.match(/(?:^|; )mrn_csrf=([^;]+)/); return m ? m[1] : ''; }
async function api(path, opt={}){
  const o = {method: opt.method || 'GET', headers: {'Content-Type':'application/json'}};
  if (o.method !== 'GET') o.headers['X-CSRF-Token'] = csrf();
  if (opt.body !== undefined) o.body = JSON.stringify(opt.body);
  const r = await fetch(path, o);
  let data = null; try { data = await r.json(); } catch(e) {}
  if (!r.ok){ const err = new Error((data && (typeof data.detail === 'string' ? data.detail : '요청 거절')) || r.statusText); err.data = data && data.detail; err.status = r.status; throw err; }
  return data;
}
function toast(msg){ const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(t._h); t._h = setTimeout(()=>t.classList.remove('on'), 3200); }

/* ---------------- doc helpers ---------------- */
function blankDoc(){ return {name:'새 워크플로', cutoff:'', nodes:[], edges:[], viewport:{}}; }
function spec(t){ return S.specs[t]; }
function nodeById(id){ return S.doc.nodes.find(n => n.id === id); }
function easyLink(){ const a = document.getElementById('bEasy'); if (a) a.href = S.runId ? '/#answer=' + S.runId : '/'; }
setInterval(easyLink, 1000);
(function modeTip(){
  const b = document.getElementById('mbWhy'), t = document.getElementById('mbTip'); if (!b || !t) return;
  const set = on => { t.classList.toggle('open', on); b.setAttribute('aria-expanded', on); };
  b.onclick = e => { e.stopPropagation(); set(!t.classList.contains('open')); };
  document.addEventListener('click', e => { if (!t.contains(e.target) && e.target !== b) set(false); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
})();
function touch(){ S.dirty = true; if (S.run) S.editedSinceRun = true; S.issues = []; renderIssues(); }
function newId(type){ let i = 1, base = type.toLowerCase(); let id = base; while (nodeById(id)) id = base + '-' + (++i); return id; }
function defaults(type){ const c = {}; for (const [k,v] of Object.entries(spec(type).config_schema)) c[k] = JSON.parse(JSON.stringify(v.default ?? '')); return c; }

/* ---------------- library & plan ---------------- */
function renderLibrary(){
  const q = $('#libSearch').value.trim().toLowerCase();
  const groups = [['common','공통도구']].concat(S.reg.perspectives);
  let h = '';
  for (const [pid, label] of groups){
    const items = S.reg.nodes.filter(n => n.perspective === pid && (!q || (n.id + n.display_name + label).toLowerCase().includes(q)));
    if (!items.length) continue;
    h += `<div class="libgrp"><i style="background:var(--p-${pid})"></i>${esc(label)}</div>`;
    for (const n of items) h += `<div class="libitem" draggable="true" data-type="${n.id}" title="${esc(n.description)}">
      <span class="id">${n.id}</span><span class="nm">${esc(n.display_name)}</span><span class="badge b-${n.implementation}">${IMPL[n.implementation]}</span></div>`;
  }
  $('#library').innerHTML = h;
  document.querySelectorAll('.libitem').forEach(el => {
    el.addEventListener('click', () => addNode(el.dataset.type));
    el.addEventListener('dragstart', e => e.dataTransfer.setData('text/node-type', el.dataset.type));
  });
}
/* v0.23.4: 관점마다 「이럴 때 체크」와 체크하면 더해지는 확장 노드 미리보기 — 모두 체크할 필요는 없다 */
const PERSP_WHEN = {
  fundamentals: '가정을 넣어 기업가치를 계산해 보고 싶을 때 (가정 입력 필요)',
  industry: '사업보고서 문장으로 제품·시장 경쟁력을 비교하고 싶을 때',
  macro: '환율·금리가 이만큼 바뀌면 손익이 얼마나 달라지나 보고 싶을 때',
  flow: '외국인·기관 매수 방향이 바뀐 때, 주가와 엇갈린 날을 보고 싶을 때',
  technical: '변동성·추세가 바뀐 구간을 더 자세히 보고 싶을 때',
  sentiment: '주요 공시 뒤 1·5·20거래일 주가 반응을 보고 싶을 때'};
function renderPersp(){
  // v0.24.1: 관점마다 「기본 분석(항상 포함, 체크 없음)」과 「심층 분석 추가(선택, 체크)」를 두 줄로 나눠 보여 준다.
  // 체크가 없다고 그 관점이 빠지는 것이 아님을 화면에서 바로 알 수 있게. 체크 칸의 값(관점 id)과 동작은 그대로.
  const nodeOf = (pid, tier) => S.reg.nodes.find(n => n.perspective === pid && n.tier === tier);
  $('#persp').innerHTML = S.reg.perspectives.map(([id,l]) => { const b = nodeOf(id, 'basic'), x = nodeOf(id, 'extension');
    return `<div class="pp" style="--pc:var(--p-${id})"><div class="ph">${esc(l)}</div>
      <div class="pbase"><span class="lock" aria-hidden="true">✓</span><span>기본 분석 <b>항상 포함</b> — ${b ? `${esc(b.id)} ${esc(b.display_name)}` : ''}</span></div>
      ${x ? `<label class="pext"><input type="checkbox" value="${id}"><span><span class="add">＋ 심층 분석 추가</span> <span class="opt">(선택)</span> — <em>${esc(x.id)} ${esc(x.display_name)}</em>
        <span class="pw">이럴 때: ${esc(PERSP_WHEN[id] || '')}</span><span class="pstate"></span></span></label>` : ''}</div>`; }).join('')
    + '<p class="hint pall">아무것도 체크하지 않아도 6개 관점 모두 기본 분석으로 배치돼요. 회사 전체를 깊이 훑는 「종합 점검」이나 공부할 때만 여러 개를 체크하세요.</p>';
  $('#persp').addEventListener('change', updatePlanCount); updatePlanCount();
}
function selectedPersp(){ return [...document.querySelectorAll('#persp input:checked')].map(i => i.value); }
async function updatePlanCount(){
  const p = await api('/api/plan?perspectives=' + selectedPersp().join(','));
  const ext = p.plan.count - 6;
  $('#planCount').innerHTML = `배치할 분석 ${p.plan.count}개<br><span class="mute">기본 6 (항상) + 심층 ${ext}${ext ? '' : ' (추가 안 함)'}</span>`;
}
async function placePlan(){
  if (S.doc.nodes.length && !confirm('현재 캔버스를 계획으로 바꿀까요? 저장하지 않은 변경은 사라집니다.')) return;
  const p = await api('/api/plan?perspectives=' + selectedPersp().join(','));
  const keepName = S.wfId ? S.doc.name : p.name;
  S.doc = {name: keepName, cutoff: S.doc.cutoff, nodes: p.nodes, edges: p.edges, viewport:{}};
  S.sel = null; S.selEdge = null; touch(); renderAll(); fit();
  toast(`계획 노드 ${p.plan.count}개와 필요한 자료 도구를 배치했습니다.`);
}
function addNode(type, x, y){
  const c = $('#canvas').getBoundingClientRect();
  const nx = x ?? ((c.width/2 - S.pan.x)/S.scale - 115 + (Math.random()*40-20));
  const ny = y ?? ((c.height/2 - S.pan.y)/S.scale - 50 + (Math.random()*40-20));
  const n = {id:newId(type), type, x:Math.round(nx), y:Math.round(ny), config:defaults(type)};
  S.doc.nodes.push(n); S.sel = n.id; S.selEdge = null; S.tab = 'config'; touch(); renderAll();
}


/* ---------------- example cases & personas ---------------- */
// Persona = how much explanation and how wide a first case. It never changes facts, approved forecasts or calculations.
const PERSONAS = {
  'novice-narrow': {label:'입문 · 좁게', desc:'공시를 읽는 법부터, 한 가지를 확실하게 보는 흐름을 추천합니다.', example:'facts-only'},
  'novice-wide':   {label:'입문 · 넓게', desc:'설명을 충분히 보면서, 실적과 거시 환경을 함께 보는 흐름을 추천합니다.', example:'facts-macro'},
  'expert-narrow': {label:'숙련 · 좁게', desc:'증권사 전망 한 건을 근거까지 따라가며 기업가치를 계산하는 흐름을 추천합니다.', example:'samsung-broker-dcf'},
  'expert-wide':   {label:'숙련 · 넓게', desc:'같은 가정에 증권사 전망 여러 건을 넣어 결과가 어떻게 갈리는지 보는 흐름을 추천합니다.', example:'broker-compare'},
};
function loadPersona(){ try { return localStorage.getItem('mrn_persona') || null; } catch(e) { return null; } }
function savePersona(v){ S.persona = v; try { v ? localStorage.setItem('mrn_persona', v) : localStorage.removeItem('mrn_persona'); } catch(e) {} }
const isNovice = () => (S.persona || '').startsWith('novice');

const K = {fact:'공식 원문 확인 사실', ext:'증권사 외부 전망', ill:'학습용 예시 가정', der:'계산 파생값', agg:'취합(새 판단 없음)'};
const ND = {
  T01: ['T01', '공식 원문 원천', '공시 원문(DART)과 거시 원문을 불러오고, 해시로 원본이 바뀌지 않았는지 확인합니다.', K.fact],
  N01: ['N01', '실적·현금흐름 분석', '원문 표의 셀을 그대로 읽어 매출액·영업이익·현금흐름 등을 「확인된 사실」로 만듭니다. 해석은 하지 않습니다.', K.fact],
  N05: ['N05', '기업별 거시 노출 분석', '금리·환율 등 거시 지표 관측값과, 기업이 공시에 직접 쓴 거시 노출 문장을 나란히 보여 줍니다. 영향 크기는 추정하지 않습니다.', K.fact],
  T03: ['T03', '사용자 가정 입력', '할인율 9%·영구성장률 2%·세율·감가상각·투자 등 증권사 전망에 없는 나머지 가정입니다. 지금 값은 학습용이므로 직접 바꿔 보세요.', K.ill],
  T04: ['T04', '증권사 전망 가져오기', '선택한 보고서 하나에서 사람이 승인한 전망치(2026E·2027E 매출액·영업이익)만 내보냅니다. 승인 안 된 값은 넘어가지 않습니다.', K.ext],
  N02: ['N02', '가치평가·실적 전망 시나리오', 'N01 사실을 원문과 다시 대조한 뒤, 전망으로 성장률(=올해 매출/작년 매출−1)과 이익률(=영업이익/매출)을 계산해 DCF에 넣고 민감도 표를 만듭니다.', K.der],
  T06: ['T06', '가격·거래량 자료', '팀 공용 DB에서 PC로 고정해 둔 사본에서 금융위원회 일별 시세를 불러오고, 사본 해시가 그대로인지 확인합니다.', K.fact],
  N09: ['N09', '가격·추세·거래량 기본', '기간 수익률, 이동평균과의 차이, 1년 최고·최저, 거래량 변화를 계산합니다. 과거 요약이며 매매 판단이 아닙니다.', K.der],
  N10: ['N10', '거래량·변동성·추세 심층', '변동성, 최대 낙폭, 거래량이 유난히 많았던 날, 추세가 이어진 정도를 계산합니다. 국면 판단은 하지 않습니다.', K.der],
  T07: ['T07', '투자자별 수급 자료', '팀 공용 DB 사본에서 외국인·기관·개인 순매수(포털 수집값)와 대차잔고(금융위)를 불러오고, 사본 해시가 그대로인지 확인합니다.', '포털 수집 사실'],
  N07: ['N07', '수급·유동성 현황', '누가 얼마나 사고팔았는지(5·20·60일 누적), 외국인 보유율 변화, 대차잔고를 계산합니다. 매매 판단이 아닙니다.', K.der],
  N08: ['N08', '수급 전환·가격 불일치', '외국인·기관의 방향이 바뀐 날, 외국인 매매와 주가가 엇갈린 날을 셉니다. 원인 해석이나 신호가 아닙니다.', K.der],
  T09: ['T09', '산업·비교기업 자료', '팀이 고른 반도체 비교군(국내·해외 30곳)과 그 회사들의 분기 재무·시가총액을 사본에서 불러옵니다. 업종만 같은 자동 묶음은 쓰지 않습니다.', K.fact],
  N03: ['N03', '산업 위치·비교기업 현황', '반도체 제조·설계 기업들과 매출 성장률·이익률·ROE·부채비율, 국내 시가총액 순위를 비교합니다. 우열이나 매매 판단이 아닙니다.', K.der],
  T10: ['T10', '거시 지표 시계열', '환율·금리·반도체 수출 등 거시 지표 25종을 사본에서 불러옵니다. 공개 시차를 반영해 기준시점에 이미 발표된 값만 씁니다.', K.fact],
  N06: ['N06', '거시 시나리오·민감도', '회사가 공시한 환율·금리 민감도에, 그 뒤 실제로 변한 환율·금리를 비례로 넣어 「이 가정이라면」 영향을 계산합니다. 예측이 아닙니다.', K.der],
  T11: ['T11', '회사 공시 재무·민감도', '고른 회사의 사업보고서 재무(DART 공시 API, 연결 우선)와 공시된 환율·금리 민감도를 사본에서 불러옵니다. 기준시점 전에 접수된 보고서만 씁니다. 원문 표 셀과 직접 대조한 값은 아니에요.', K.fact],
  T08: ['T08', '뉴스·사건 자료', '고른 회사의 DART 공시 목록(공식)과 뉴스 제목·링크(포털, 본문 없음), 규칙 감성 점수·검색 건수를 사본에서 불러옵니다. 같은 제목은 하나로 합쳐요.', K.fact],
  N11: ['N11', '주요 사건·감성 현황', '공시를 종류별로 세고 주요 공시를 추려 보여 주며, 주별 뉴스 수·규칙 감성 점수·검색 건수 변화를 계산합니다. 호재·악재 판단은 하지 않아요.', K.der],
  N12: ['N12', '심리 변화·후속 시장 반응', '주요 공시 뒤 1·5·20거래일 주가와 코스피 대비 차이, 거래량 배수를 셉니다. 공시 때문에 움직였다는 뜻이 아니에요.', K.der],
  T02: ['T02', '사업보고서 문장 검색', '저장된 사업보고서 원문에서 검색어에 맞는 문단을 원문 그대로 가져옵니다. 문단마다 원문 해시가 붙어요.', K.fact],
  N04: ['N04', '제품·시장 경쟁력 심층 비교', '사업보고서 문단에서 점유율·경쟁사·순위·시장 규모 문장을 원문 그대로 뽑아 숫자 표현을 표시합니다. 우열 판단은 하지 않아요.', K.fact],
  T12: ['T12', '지분·대주주 공시', '최대주주·특수관계인 지분, 5% 대량보유 보고, 임원·주요주주 보고 개수를 사본에서 불러옵니다.', K.fact],
  N13: ['N13', '대주주·경영진 지분', '최대주주 측 지분 합계와 변화, 5% 보고 내역, 임원 보고 건수를 보여 줍니다. T02를 이으면 원문과 대조해요. 지배구조 평가는 하지 않아요.', K.fact],
  N14: ['N14', '수출 통계로 실적 조기 확인', '관세청 수출 통계와 과거 「매출÷수출」 비율로 아직 공시 전인 분기 매출 범위를 계산합니다. 과거 오차가 크면 보류해요. 모델 추정입니다.', K.der],
  T05: ['T05', '보고서 취합', '연결된 결과를 상태(성공·보류 등) 그대로 한 곳에 모읍니다. 새 결론을 만들지 않습니다.', K.agg],
};
const DCF_T03 = () => Object.assign(defaults('T03'), {method:'dcf', model: JSON.parse(JSON.stringify(TEMPLATES.dcf2)), input_kind:'illustrative_assumptions',
  label:'증권사 전망 적용 (나머지 학습용)', shares:'5846279000', share_basis:'증권사 보고서에 기재된 발행주식수(보통주) — 희석주식수 확인 필요',
  assumptions_note:'성장률·이익률은 N02에서 승인된 증권사 전망으로 대체. 나머지는 학습용 임의 가정'});
const mkN = (id, type, x, y, cfg) => ({id, type, x, y, config: Object.assign(defaults(type), cfg || {})});
const mkE = (a, ap, b, bp) => ({from_node:a, from_port:ap, to_node:b, to_port:bp});

const EXAMPLES = [
 {id:'facts-only', persona:'novice-narrow', needs:0,
  title:'공시로 확인된 실적만 보기 — 삼성전자·SK하이닉스',
  question:'「두 회사의 2024·2025년 매출액·영업이익·현금흐름은 공시 원문에 정확히 얼마로 적혀 있나?」',
  meaning:'전망도 가정도 없이, 공시 원문 표의 숫자만 확인합니다. 모든 리서치의 출발점인 「확인된 사실」이 무엇인지, 그리고 숫자마다 원문의 어느 표·어느 칸에서 왔는지를 익히는 사례입니다.',
  nodes:['T01','N01','T05'],
  build: () => ({nodes:[mkN('t01','T01',40,80), mkN('n01','N01',420,80), mkN('t05','T05',800,80)],
                 edges:[mkE('t01','corpus','n01','corpus'), mkE('n01','facts','t05','results')]}),
  read:['N01 → 「결과」 탭에서 회사·연도·항목별 금액을 봅니다. 금액은 원문 셀 값 그대로입니다.',
        'N01 → 「근거」 탭에서 각 숫자의 원문 표 번호·행·열과 문서 해시를 확인할 수 있습니다.',
        'N01을 눌러 「설정」에서 항목(예: 재고자산, 유형자산 취득)을 더 고르고 다시 실행해 보세요.'],
  caution:['증감의 원인이나 앞으로의 지속성은 판단하지 않습니다. 「얼마였나」까지만 답합니다.',
           '최신·정정 공시를 자동으로 찾지는 않습니다. 저장된 원문 기준입니다.']},
 {id:'facts-macro', persona:'novice-wide', needs:0,
  title:'실적과 거시 환경 함께 보기 — 금리·환율 노출',
  question:'「실적 숫자와 함께, 이 회사가 공시에서 스스로 밝힌 금리·환율 노출은 무엇이고 그해 지표는 어땠나?」',
  meaning:'같은 공식 원문에서 두 갈래로 나눠 봅니다. 한쪽(N01)은 실적 숫자, 다른 쪽(N05)은 거시 지표 관측값과 회사가 직접 쓴 노출 문장입니다. 「숫자」와 「환경」을 한 화면에 놓되, 둘 사이의 인과를 앱이 지어내지 않는다는 점을 보는 사례입니다.',
  nodes:['T01','N01','N05','T05'],
  build: () => ({nodes:[mkN('t01','T01',40,200), mkN('n01','N01',420,60), mkN('n05','N05',420,340), mkN('t05','T05',800,200)],
                 edges:[mkE('t01','corpus','n01','corpus'), mkE('t01','corpus','n05','corpus'), mkE('n01','facts','t05','results'), mkE('n05','exposure','t05','results')]}),
  read:['T01에서 선이 두 갈래로 나갑니다. 같은 원문을 두 노드가 각자 다른 관점으로 읽는다는 뜻입니다.',
        'N05 → 「결과」에서 지표 관측값(기준연도)과 회사 공시 문장을 나란히 봅니다.',
        'T05는 두 결과를 상태 그대로 모읍니다. 「영향이 컸다/작았다」 같은 결론은 만들지 않습니다.'],
  caution:['거시 지표가 실적에 준 영향의 크기는 추정하지 않습니다(N06 시나리오 노드는 아직 일부만 구현).',
           '지표는 기준연도 관측값입니다. 예측이 아닙니다.']},
 {id:'samsung-broker-dcf', persona:'expert-narrow', needs:1,
  title:'삼성전자 — 증권사 전망 한 건으로 기업가치 계산해 보기',
  question:'「증권사가 내놓은 2026·2027년 실적 전망이 맞다고 가정하면, 공시 사실과 내 가정 위에서 기업가치는 얼마로 계산되는가?」',
  meaning:'공시로 확인된 과거 사실(2025년)에서 출발해, 사람이 승인한 증권사 전망 한 건으로 앞으로 2년의 성장률·이익률을 채우고, 나머지는 내가 정한 가정으로 DCF를 계산하는 흐름입니다. 사실·외부 전망·내 가정이 어디서 들어와 어떻게 합쳐지는지를 한 화면에서 보는 것이 목적입니다.',
  nodes:['T01','N01','T04','T03','N02'],
  build: (picks) => ({nodes:[mkN('t01','T01',40,40), mkN('n01','N01',40,230), mkN('t03','T03',40,420,DCF_T03()),
      mkN('t04','T04',40,610,{report: picks[0] ? picks[0].file : ''}), mkN('n02','N02',460,300,{apply_forecast:'yes'})],
    edges:[mkE('t01','corpus','n01','corpus'), mkE('n01','facts','n02','facts'), mkE('t03','assumptions','n02','assumptions'), mkE('t04','forecasts','n02','forecasts')]}),
  read:['상단이 「실행 성공 · 성공 5」이고 T04→N02 선이 초록 실선이면 전망이 실제로 들어간 것입니다. 점선이면 전달되지 않았습니다.',
        'N02 → 「결과」 탭의 「적용된 증권사 전망」 표에서 어떤 보고서의 어떤 숫자가 성장률·이익률로 바뀌었는지 확인합니다.',
        '「근거」 탭에서 값마다 출처(공시 셀, 보고서 쪽 번호·인용, 내 가정)를 따라갈 수 있습니다.',
        'T04의 보고서만 바꿔 다시 실행하면 증권사마다 결과가 어떻게 달라지는지 비교할 수 있습니다.'],
  caution:['결과는 목표주가나 매매 의견이 아닙니다. 「이 전망과 이 가정이라면」의 계산입니다.',
           '증권사 전망 한 건만 씁니다. 여러 보고서를 평균 내지 않습니다(컨센서스 아님).',
           '할인율·투자 등 나머지 가정은 학습용 예시입니다. 실제 판단에 쓰려면 직접 근거를 갖고 바꾸세요.']},
 {id:'broker-compare', persona:'expert-wide', needs:3,
  title:'증권사 3곳 전망을 같은 가정에 넣어 비교하기',
  question:'「할인율 등 내 가정은 그대로 두고 증권사 전망만 바꾸면, 계산된 기업가치는 얼마나 벌어지는가?」',
  meaning:'공시 사실(N01)과 내 가정(T03) 하나를 세 개의 가치평가 노드에 똑같이 넣고, 각 노드에는 서로 다른 증권사 전망(T04)을 하나씩 연결합니다. 결과 차이는 오직 전망 차이에서 나옵니다. 보고서를 합치지 않고 나란히 둔다는 것이 핵심입니다.',
  nodes:['T01','N01','T03','T04','N02','T05'],
  build: (picks) => { const n = [mkN('t01','T01',40,60), mkN('n01','N01',40,280), mkN('t03','T03',40,500,DCF_T03()), mkN('t05','T05',1180,330)];
    const e = [mkE('t01','corpus','n01','corpus')];
    for (let i = 0; i < 3; i++){ n.push(mkN(`t04_${i+1}`,'T04',420,110+i*240,{report: picks[i] ? picks[i].file : ''}), mkN(`n02_${i+1}`,'N02',800,90+i*240,{apply_forecast:'yes'}));
      e.push(mkE('n01','facts',`n02_${i+1}`,'facts'), mkE('t03','assumptions',`n02_${i+1}`,'assumptions'), mkE(`t04_${i+1}`,'forecasts',`n02_${i+1}`,'forecasts'), mkE(`n02_${i+1}`,'valuation','t05','results')); }
    return {nodes:n, edges:e}; },
  read:['N01과 T03에서 선이 세 갈래로 나갑니다. 사실과 가정은 세 계산에 똑같이 들어간다는 뜻입니다.',
        'N02 세 개를 하나씩 눌러 「결과」의 주당 가치와 「적용된 증권사 전망」 표를 비교합니다.',
        '「증권사 전망」 → 「비교표」에서 같은 보고서들의 원래 전망치와 함께 보면, 어떤 가정 차이가 결과 차이를 만들었는지 보입니다.',
        '전망 차이에 비해 결과 차이가 작다면 말기가치 비중 때문입니다(N02 결과의 「해석 안내」). 이때는 「정상화 이익 시나리오」 사례로 이어서 보세요.',
        'T04의 보고서를 바꿔 다른 조합으로 다시 실행해 보세요.'],
  caution:['세 결과를 평균 내거나 하나를 정답으로 고르지 않습니다. 「전망에 따라 이만큼 갈린다」를 보는 것이 목적입니다.',
           '할인율·투자 등 공통 가정은 학습용입니다. 공통 가정이 바뀌면 세 결과가 함께 움직입니다.',
           '결과는 목표주가나 매매 의견이 아닙니다.']},

 {id:'price-basic', persona:'novice-wide', needs:0,
  title:'주가 흐름과 거래량 기본 보기 — 기술적 분석',
  question:'「최근 1개월·1년 동안 주가와 거래량은 어떻게 움직였고, 변동성과 고점 대비 낙폭은 얼마였나?」',
  meaning:'팀 공용 DB에서 PC로 고정해 둔 금융위원회 일별 시세 사본(T06)을 두 노드가 읽습니다. N09는 기간 수익률·이동평균·1년 최고/최저·거래량 비교를, N10은 변동성·최대 낙폭·거래량 급증일을 계산합니다. 모두 과거 가격의 요약이며, 앞으로의 방향이나 매매 판단을 말하지 않습니다.',
  nodes:['T06','N09','N10','T05'],
  build: () => ({nodes:[mkN('t06','T06',40,200,{company:'000660'}), mkN('n09','N09',420,60), mkN('n10','N10',420,340), mkN('t05','T05',800,200)],
                 edges:[mkE('t06','prices','n09','prices'), mkE('t06','prices','n10','prices'), mkE('n09','finding','t05','results'), mkE('n10','finding','t05','results')]}),
  read:['T06 → 「결과」에서 사본 이름·표 해시·출처 등급(금융위원회 공공자료)을 확인합니다.',
        'N09 → 수익률과 이동평균은 「계산 파생값」입니다. 산식 칸에 계산 방법이 적혀 있습니다.',
        'N10 → 국면(상승·하락) 판단은 하지 않으므로 「일부」로 끝납니다.'],
  caution:['수정주가가 아닌 시세 원값입니다.', '기준시점에 확정된 거래일까지만 씁니다.', '과거 가격의 요약이며 앞으로의 방향이나 매매 판단이 아닙니다.']},
 {id:'flow-basic', persona:'novice-wide', needs:0,
  title:'누가 사고팔았나 — 수급과 주가 함께 보기',
  question:'「최근 외국인·기관·개인은 얼마나 사고팔았고, 주가와 같은 방향이었나? 지금 국면은?」',
  meaning:'팀 공용 DB 사본에서 투자자별 순매수(T07, 포털 수집값)와 일별 시세(T06)를 불러옵니다. N07은 누적 순매수·보유율·대차잔고를, N08은 수급과 주가가 엇갈린 날을, N10은 변동성과 이동평균 배열 규칙에 따른 국면을 계산합니다.',
  nodes:['T06','T07','N07','N08','N10','T05'],
  build: () => ({nodes:[mkN('t07','T07',40,80,{company:'000660'}), mkN('t06','T06',40,330,{company:'000660'}), mkN('n07','N07',420,20), mkN('n08','N08',420,200), mkN('n10','N10',420,380), mkN('t05','T05',800,200)],
                 edges:[mkE('t07','flows','n07','flows'), mkE('t07','flows','n08','flows'), mkE('t06','prices','n08','prices'), mkE('t06','prices','n10','prices'),
                        mkE('n07','finding','t05','results'), mkE('n08','finding','t05','results'), mkE('n10','finding','t05','results')]}),
  read:['T07 → 「결과」에서 「포털 수집 사실」 배지를 확인합니다. 거래소 공식 자료와 아직 대조하지 않은 값입니다.',
        'N08 → 「순매도인데 상승」 같은 날 수는 기록일 뿐, 이유나 신호가 아닙니다.',
        'N10 → 국면은 이동평균 배열 규칙에 따른 분류입니다. 산식 칸에 규칙이 적혀 있습니다.'],
  caution:['순매수는 주식 수 기준입니다(금액 아님).', '수급과 국면은 과거 기록이며 매매 판단이 아닙니다.']},
 {id:'peers-macro', persona:'expert-wide', needs:0,
  title:'반도체 비교군 속 위치와 환율·금리 영향',
  question:'「SK하이닉스는 반도체 기업들 사이에서 이익률·성장률이 어디쯤이고, 올해 환율·금리 변화를 공시 민감도에 넣으면 영향은 얼마쯤인가?」',
  meaning:'T09가 팀이 고른 반도체 비교군을, N03이 같은 잣대(최근 4분기 비율)로 순위를 냅니다. 아래 줄에서는 공식 원문(T01)의 공시 민감도(N05)에 거시 지표(T10)의 실제 변화를 넣어 N06이 「이 가정이라면」 영향을 계산합니다.',
  nodes:['T09','N03','T01','N05','T10','N06','T05'],
  build: () => ({nodes:[mkN('t09','T09',40,40,{company:'000660'}), mkN('n03','N03',420,40), mkN('t01','T01',40,260), mkN('n05','N05',420,260), mkN('t10','T10',40,460), mkN('n06','N06',780,340), mkN('t05','T05',1120,200)],
                 edges:[mkE('t09','peers','n03','peers'), mkE('t01','corpus','n05','corpus'), mkE('n05','exposure','n06','exposure'), mkE('t10','macro','n06','macro'),
                        mkE('n03','finding','t05','results'), mkE('n06','finding','t05','results')]}),
  read:['N03 → 「비교 표」에서 각 회사의 마지막 분기와 출처(DART·SEC)를 확인합니다.',
        'N03 → 순이익률이 영업이익률보다 높으면 영업 밖 이익이 섞였다는 안내가 붙습니다.',
        'N06 → 산식 칸에 「공시 민감도 × 실제 변화 ÷ 공시 충격」이 적혀 있습니다. 실현손익이 아닙니다.'],
  caution:['순위는 과거 재무 비율의 비교이며 우열·매매 판단이 아닙니다.', '해외 기업은 통화가 달라 비율만 비교합니다.', 'N06은 다른 변수가 같다는 선형 가정의 계산입니다.']},
 {id:'events-holders', persona:'novice-wide', needs:0,
  title:'최근 무슨 일이 있었나 — 공시·뉴스·반응·대주주',
  question:'「한미반도체에 최근 어떤 공시와 뉴스가 있었고, 공시 뒤 주가는 어떻게 움직였으며, 대주주 지분은 어떤가?」',
  meaning:'T08이 공시 목록(공식)과 뉴스 제목(포털)을 모으면 N11이 종류별로 세고, N12가 주요 공시 뒤 1·5·20거래일 주가를 잽니다. T12→N13은 최대주주와 5% 보고를 보여 줍니다. 회사 칸만 바꾸면 다른 회사도 됩니다.',
  nodes:['T08','N11','T06','N12','T12','N13','T05'],
  build: () => ({nodes:[mkN('t08','T08',40,40,{company:'042700'}), mkN('n11','N11',420,40), mkN('t06','T06',40,230,{company:'042700'}), mkN('n12','N12',420,200),
                        mkN('t12','T12',40,420,{company:'042700'}), mkN('n13','N13',420,400), mkN('t05','T05',800,220)],
                 edges:[mkE('t08','events','n11','events'), mkE('t08','events','n12','events'), mkE('t06','prices','n12','prices'), mkE('t12','ownership','n13','ownership'),
                        mkE('n11','finding','t05','results'), mkE('n12','finding','t05','results'), mkE('n13','finding','t05','results')]}),
  read:['N11 → 「주요 공시」 표에서 원문 링크로 바로 갈 수 있습니다.', 'N12 → 공시별 표에 1·5·20일 수익률과 코스피 대비 차이가 있습니다. 표본 5건 미만은 경향으로 보지 마세요.',
        'N13 → 최대주주 측 합계와 5% 보고 내역(보고자·증감·사유)을 공시 그대로 보여 줍니다.'],
  caution:['뉴스는 제목만 썼고, 감성 점수는 단어 사전 규칙 값입니다.', '공시 뒤 주가 변화는 공시가 원인이라는 뜻이 아닙니다.']},
 {id:'kit2-nowcast', persona:'expert-wide', needs:0,
  title:'다른 회사 실적·환율 영향 + 수출로 실적 조기 확인',
  question:'「한미반도체의 사업보고서 실적과 환율 영향은? 그리고 SK하이닉스 이번 분기 매출을 수출 통계로 미리 가늠할 수 있나?」',
  meaning:'T11이 공시 API 재무와 공시 민감도 표를 읽어 N01(실적)·N05→N06(환율·금리 「이 가정이라면」)에 줍니다. 아래 줄은 T11(SK하이닉스 분기 매출)과 T10(관세청 수출)을 N14가 비율로 이어 아직 공시 전인 분기 매출 범위를 계산합니다.',
  nodes:['T11','N01','N05','T10','N06','N14','T05'],
  build: () => ({nodes:[mkN('t11','T11',40,40,{company:'042700'}), mkN('n01','N01',420,20,{companies:[]}), mkN('n05','N05',420,190), mkN('t10','T10',40,330), mkN('n06','N06',780,260),
                        mkN('t11b','T11',40,520,{company:'000660'}), mkN('n14','N14',420,480), mkN('t05','T05',1120,260)],
                 edges:[mkE('t11','filings','n01','filings'), mkE('t11','filings','n05','filings'), mkE('n05','exposure','n06','exposure'), mkE('t10','macro','n06','macro'),
                        mkE('t11b','filings','n14','filings'), mkE('t10','macro','n14','macro'),
                        mkE('n01','facts','t05','results'), mkE('n06','finding','t05','results'), mkE('n14','finding','t05','results')]}),
  read:['N01 → 다른 회사 값에는 「공시 API」 표시가 붙습니다(원문 셀 대조 아님).', 'N06 → 다른 회사 민감도는 표에서 규칙으로 읽은 값이라 부호를 원문으로 확인하라는 안내가 붙습니다.',
        'N14 → 「과거 맞히기 시험」 오차가 15%를 넘으면 계산하지 않고 보류합니다(삼성전자는 보류).'],
  caution:['N14 결과는 모델 추정이며 실적 공시가 나오면 공시 값이 우선입니다.']},
 {id:'normalized-scenario', persona:'expert-narrow', needs:1,
  title:'정상화 이익 시나리오 — 정점 이후 이익을 얼마로 보느냐',
  question:'「증권사 전망 한 건은 그대로 두고, 업황 정점 이후의 정상 현금흐름(정상화 FCFF)만 낮음·중간·높음으로 바꾸면 기업가치는 얼마나 달라지는가?」',
  meaning:'경기순환 업종은 2~3년 전망보다 「정점이 지난 뒤 이익이 어디쯤 자리 잡느냐」가 기업가치를 훨씬 크게 좌우합니다. 같은 사실·같은 증권사 전망에 정상화 FCFF만 세 가지로 넣어, 장기 가정 하나가 결과를 얼마나 움직이는지 직접 봅니다.',
  nodes:['T01','N01','T04','T03','N02','T05'],
  build: (picks) => { const lv = [['낮음', '150000000', '업황 정점 이후 이익이 크게 되돌아간다고 본 학습용 시나리오(정상화 FCFF 150조)'],
                                  ['중간', '250000000', '정점과 저점의 중간쯤으로 본 학습용 시나리오(정상화 FCFF 250조)'],
                                  ['높음', '350000000', '정점 이익이 상당 부분 유지된다고 본 학습용 시나리오(정상화 FCFF 350조)']];
    const n = [mkN('t01','T01',40,60), mkN('n01','N01',40,280), mkN('t04','T04',40,500,{report: picks[0] ? picks[0].file : ''}), mkN('t05','T05',1180,320)];
    const e = [mkE('t01','corpus','n01','corpus')];
    lv.forEach(([nm, v, why], i) => { const c = DCF_T03(); c.model.terminal_fcff = v; c.model.terminal_reason = why; c.label = `정상화 이익 ${nm}`;
      n.push(mkN(`t03_${i+1}`,'T03',420,60+i*260,c), mkN(`n02_${i+1}`,'N02',800,60+i*260,{apply_forecast:'yes'}));
      e.push(mkE('n01','facts',`n02_${i+1}`,'facts'), mkE(`t03_${i+1}`,'assumptions',`n02_${i+1}`,'assumptions'), mkE('t04','forecasts',`n02_${i+1}`,'forecasts'), mkE(`n02_${i+1}`,'valuation','t05','results')); });
    return {nodes:n, edges:e}; },
  read:['T04(증권사 전망)와 N01(사실)에서 선이 세 갈래로 나갑니다. 전망과 사실은 세 계산에 똑같고, T03의 정상화 FCFF만 다릅니다.',
        'N02 세 개의 주당가치를 비교하세요. 「증권사 3곳 비교」 사례의 결과 차이와 견주면, 어느 쪽이 결과를 더 크게 움직이는지 보입니다.',
        '각 N02의 「해석 안내」에서 말기가치 비중을 확인하세요. 비중이 클수록 장기 가정의 영향이 큽니다.',
        'T03의 정상화 FCFF를 직접 바꾸려면 실행 후 T03에서 「이의 제기」를 쓰세요(사유가 기록됩니다).'],
  caution:['150조·250조·350조는 학습용 시나리오 값입니다. 실제 정상 이익 추정이 아닙니다.',
           '정상화 FCFF는 장기 재투자·수익성과 함께 일관되게 정해야 합니다. 값 하나만 바꾸는 단순화입니다.',
           '결과는 목표주가나 매매 의견이 아닙니다.']},
];

async function pickReports(n){
  try { const r = await api('/api/broker/reports');
    const ok = r.reports.filter(x => { const a = r.candidates.filter(c => c.file === x.file && c.state === 'approved');
      return [2026, 2027].every(fy => ['revenue','operatingProfit'].every(m => a.some(c => c.fiscal_year === fy && c.metric === m))); });
    ok.sort((a, b) => (b.report_date || '').localeCompare(a.report_date || ''));
    const seen = new Set(), out = [];
    for (const x of ok) if (!seen.has(x.broker)) { seen.add(x.broker); out.push(x); }   // distinct brokers first
    for (const x of ok) if (out.length < n && !out.includes(x)) out.push(x);
    return {reports: out.slice(0, n), scanned: r.reports.length}; } catch(e) { return {reports: [], scanned: 0}; }
}
async function loadExample(id, opts = {}){
  const ex = EXAMPLES.find(e => e.id === id) || EXAMPLES[0];
  if (S.doc.nodes.length && S.dirty && !confirm('저장하지 않은 변경이 있습니다. 예시 사례로 바꿀까요?')) return;
  const pick = ex.needs ? await pickReports(ex.needs) : {reports: [], scanned: 0};
  const g = ex.build(pick.reports);
  S.doc = {name: '예시: ' + ex.title, cutoff: '', viewport: {}, nodes: g.nodes, edges: g.edges};
  S.example = {id: ex.id, reports: pick.reports, scanned: pick.scanned};
  S.wfId = null; S.wfVersion = null; S.history = []; S.run = null; S.runId = null; S.issues = []; S.sel = null; S.selEdge = null;
  stopPoll(); renderRunbar(); renderIssues(); setHash(); S.dirty = false; S.editedSinceRun = false; renderAll(); fit();
  if (opts.quiet){ if ($('#dlg').open) $('#dlg').close(); return; }
  if (isNovice() || !S.persona) showExampleGuide(); else { if ($('#dlg').open) $('#dlg').close(); toast('예시를 배치했습니다. 설명은 오른쪽 패널의 「사례 설명 전체 보기」에 있습니다.'); }
}
function exampleStatusHtml(){
  const e = S.example; if (!e) return '';
  const ex = EXAMPLES.find(x => x.id === e.id); if (!ex || !ex.needs) return `<div class="ok-note">준비할 것이 없습니다. 「실행」을 누르면 됩니다.</div>`;
  const names = e.reports.map(r => `<b>${esc(r.report_date)} ${esc(r.broker)}</b>`).join(', ');
  if (e.reports.length >= ex.needs) return `<div class="ok-note">T04에 ${names} 보고서를 넣었습니다 (2026·2027 매출액·영업이익이 승인된 것 중 최근 순${ex.needs > 1 ? ', 서로 다른 증권사 우선' : ''}). 「실행」을 누르면 됩니다.</div>`;
  const lack = ex.needs - e.reports.length;
  return `<div class="stale-note">${e.scanned ? `2026·2027년 매출액·영업이익이 모두 승인된 보고서가 ${lack}개 더 필요합니다${e.reports.length ? ` (현재 ${names})` : ''}.` : '아직 스캔된 보고서가 없습니다.'} 「증권사 전망」 → ${e.scanned ? '' : '「PDF 다시 스캔」 → '}「승인」 탭에서 승인한 뒤, 빈 T04에서 보고서를 고르세요. 그대로 실행하면 빈 T04는 보류되고 해당 N02는 학습용 가정만으로 계산됩니다.</div>`;
}
function exampleGuideHtml(ex){
  const novice = isNovice() || !S.persona;
  let h = `<p class="desc"><b>이 사례가 답하는 질문</b><br>${esc(ex.question)}</p><p>${esc(ex.meaning)}</p>${exampleStatusHtml()}
    <h3>노드별 역할 (자료가 흐르는 순서)</h3><table><tr><th>노드</th><th>하는 일</th><th>값의 종류</th></tr>${ex.nodes.map(t => { const [k, nm, d, kind] = ND[t]; return `<tr><td style="white-space:nowrap"><b>${k}</b> ${esc(nm)}</td><td>${esc(d)}</td><td>${esc(kind)}</td></tr>`; }).join('')}</table>
    <h3>결과 읽는 법</h3><ol>${ex.read.map(x => `<li>${esc(x)}</li>`).join('')}</ol>
    <h3>주의</h3><ul>${ex.caution.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (novice) h += `<h3>처음이라면</h3><ul><li>노드 오른쪽 점(출력) → 다른 노드 왼쪽 점(입력)으로 선이 이어집니다. 선은 「자료가 넘어간다」는 뜻이지 승인이나 정답이 아닙니다.</li><li>노드를 누르면 오른쪽에 설정·결과·근거·상태 탭이 열립니다. 숫자의 출처는 항상 「근거」 탭에 있습니다.</li><li>색 표시: 초록 「공식 원문 확인 사실」, 보라 「증권사 외부 전망」, 회색 「학습용 예시 가정」.</li></ul>`;
  return h;
}
function showExampleGuide(){
  const ex = EXAMPLES.find(e => e.id === (S.example || {}).id) || EXAMPLES[0];
  $('#dlgBody').innerHTML = `<h2>예시 사례: ${esc(ex.title)}</h2>${exampleGuideHtml(ex)}`;
  openWide();
}
function openWide(){ $('#dlg').classList.add('wide'); $('#dlg').addEventListener('close', () => $('#dlg').classList.remove('wide'), {once:true}); if (!$('#dlg').open) $('#dlg').showModal(); }
function personaChip(){ const p = PERSONAS[S.persona]; return p ? `<span class="pchip">내 유형: ${esc(p.label)}</span>` : `<span class="pchip none">유형 미정</span>`; }

function openExamplePicker(){
  const rec = PERSONAS[S.persona] ? PERSONAS[S.persona].example : null;
  const order = rec ? [EXAMPLES.find(e => e.id === rec), ...EXAMPLES.filter(e => e.id !== rec)] : EXAMPLES;
  $('#dlgBody').innerHTML = `<h2>질문으로 시작하기</h2>
    <div class="askrow"><input id="askQ" placeholder="예: SK하이닉스 최근 1년 주가 낙폭이랑 환율 민감도 같이 보고 싶어" maxlength="500"><button class="primary" id="askGo">질문으로 조립하기</button></div>
    <p class="hint">질문에 답하는 데 필요한 노드를 앱이 거꾸로 찾아 근거 사슬로 깔아 드려요. 사람이 정할 곳(가정·보고서 선택)은 비워 두고 알려 드리며, 아직 없는 노드는 지어내지 않고 「아직 답할 수 없음」으로 밝혀요. 매매 판단은 하지 않아요.
      <button id="askMap" class="linkbtn">질문 지도 보기</button></p><div id="planOut"></div>
    <h2 style="margin-top:18px">또는 예시 사례 고르기</h2>
    <div class="prow">${personaChip()} <button id="bPersona">${S.persona ? '유형 다시 정하기' : '3문항으로 내 유형 정하기'}</button>
      <span class="mute">유형은 설명의 양과 추천 순서만 바꿉니다. 사실·전망·계산 결과는 누구에게나 같습니다.</span></div>
    <div class="excards">${order.map(e => { const p = PERSONAS[e.persona];
      return `<div class="excard ${e.id === rec ? 'rec' : ''}"><div class="exhead">${e.id === rec ? '<span class="recb">추천</span> ' : ''}<span class="mute">${esc(p.label)}에 맞춤</span></div>
        <b>${esc(e.title)}</b><p>${esc(e.question)}</p><div class="mute">노드: ${e.nodes.join(' · ')}${e.needs ? ` · 승인된 증권사 보고서 ${e.needs}개 필요` : ' · 준비 필요 없음'}</div>
        <button class="primary" data-ex="${e.id}">이 사례 불러오기</button></div>`; }).join('')}</div>`;
  openWide();
  $('#bPersona').onclick = openPersonaQuiz;
  $('#dlgBody').querySelectorAll('[data-ex]').forEach(b => b.onclick = () => loadExample(b.dataset.ex));
  $('#askGo').onclick = () => askAssemble(); $('#askQ').onkeydown = e => { if (e.key === 'Enter') askAssemble(); };
  $('#askMap').onclick = openQuestionMap;
  setTimeout(() => $('#askQ') && $('#askQ').focus(), 50);
}
async function askPlan(){
  const q = $('#askQ').value.trim(); if (!q){ $('#askQ').focus(); return; }
  $('#planOut').innerHTML = '<p><span class="spin"></span> 계획 중…</p>';
  let r; try { r = await api('/api/agent/plan', {method:'POST', body:{question:q, persona:S.persona}}); } catch(e){ $('#planOut').innerHTML = `<p class="stale-note">계획 실패: ${esc(e.message)}</p>`; return; }
  const ex = EXAMPLES.find(e => e.id === r.example_id);
  $('#planOut').innerHTML = `<div class="plancard"><div><span class="recb">${r.method === 'model' ? 'AI 모델 계획' : '키워드 계획'}</span> <b>${esc(ex.title)}</b></div>
    <p>${esc(r.reason)}</p>${r.notes.map(n => `<div class="stale-note">${esc(n)}</div>`).join('')}
    <div class="mute">노드: ${ex.nodes.join(' · ')}${ex.needs ? ` · 승인된 증권사 보고서 ${ex.needs}개 필요` : ''}${r.model_note && r.method !== 'model' ? ` · 모델: ${esc(r.model_note)}` : ''}</div>
    <div class="prow"><button class="primary" id="planRun">배치하고 에이전트 실행</button><button id="planPlace">배치만</button>
    <select id="planAlt"><option value="">다른 사례로 바꾸기…</option>${r.alternatives.map(a => `<option value="${a.id}">${esc(a.title)}</option>`).join('')}</select></div></div>`;
  $('#planRun').onclick = async () => { await loadExample(r.example_id, {quiet:true}); S.doc.name = '질문: ' + q.slice(0, 60); renderHeader(); runAgent(); };
  $('#planPlace').onclick = () => loadExample(r.example_id);
  $('#planAlt').onchange = e => { if (e.target.value) loadExample(e.target.value); };
}
/* ---------------- 목표부터 조립 (질문 → 근거 사슬 자동 배치) ---------------- */
async function askAssemble(pick){
  const q = $('#askQ').value.trim(); if (!q && !pick){ $('#askQ').focus(); return; }
  $('#planOut').innerHTML = '<p><span class="spin"></span> 질문에 필요한 노드를 거꾸로 찾는 중…</p>';
  let r; try { r = await api('/api/agent/assemble', {method:'POST', body:{question:q, pick: pick || null, cutoff: $('#cutoff').value.trim()}}); }
  catch(e){ $('#planOut').innerHTML = `<p class="stale-note">조립 실패: ${esc(e.message)}</p>`; return; }
  S.lastAssembly = r;
  const notes = r.notes.map(n => `<div class="stale-note">${esc(n)}</div>`).join('');
  const gaps = r.gaps.length ? `<div class="asm-gap"><b>아직 답할 수 없는 부분</b><ul>${r.gaps.map(g => `<li>${esc(g.label)}${g.hits.length ? ` <span class="mute">(「${esc(g.hits.slice(0,3).join('·'))}」)</span>` : ''} — ${esc(g.why)}</li>`).join('')}</ul>
      <div class="mute">이런 질문이 쌓이면 「질문 지도」에서 어떤 노드를 먼저 만들지 볼 수 있어요.</div></div>` : '';
  if (r.status !== 'ok'){
    $('#planOut').innerHTML = `<div class="plancard">${r.ask ? `<p><b>${esc(r.ask)}</b></p>` : ''}${notes}${gaps}
      <div class="asm-choices">${r.choices.map(c => `<button data-pick="${c.id}">${esc(c.label)}</button>`).join('')}</div></div>`;
    $('#planOut').querySelectorAll('[data-pick]').forEach(b => b.onclick = () => askAssemble([b.dataset.pick]));
    return;
  }
  const n = r.doc.nodes.length, human = r.human || [];
  const t03 = human.find(h => h.type === 'T03');
  const t03co = t03 ? (r.doc.nodes.find(x => x.id === t03.for) || {config:{}}).config.company : null;
  $('#planOut').innerHTML = `<div class="plancard asm">
    <div><span class="recb">목표부터 조립</span> <b>이 질문에 답하려면 노드 ${n}개가 필요해요</b></div>
    <ol class="asm-chain">${r.chains.map(c => `<li><div class="mono">${esc(c.chain)}</div><div>${esc(c.text)}</div></li>`).join('')}</ol>
    ${human.length ? `<div class="asm-human"><b>사람 차례 ${human.length}곳</b> — 앱이 대신 정하지 않아요<ul>${human.map(h => `<li><b>${esc(h.type)}</b> ${esc(h.what)}</li>`).join('')}</ul>
      ${t03 && t03co === '005930' ? '<label class="mute"><input type="checkbox" id="asmIll" checked> T03을 「학습용 예시 가정」으로 먼저 채우기 (실제 추정 아님)</label>' : ''}</div>` : ''}
    ${gaps}${notes}
    ${(r.issues || []).filter(i => i.code !== 'assumption_invalid').length ? `<div class="stale-note">배치한 뒤 아래 확인 목록을 봐 주세요.</div>` : ''}
    <div class="prow"><button class="primary" id="asmRun">배치하고 실행</button><button id="asmPlace">배치만</button>
      <button id="asmOld" title="미리 만든 예시 사례 6개 중에서 고르는 예전 방식">예시 사례로 답하기</button></div>
    <p class="hint">숫자는 코드가 계산하고, 매수·매도 판단은 하지 않아요. 배치한 뒤 노드를 지우거나 더해도 됩니다.</p></div>`;
  const place = () => {
    if (S.doc.nodes.length && S.dirty && !confirm('저장하지 않은 변경이 있습니다. 조립한 계획으로 바꿀까요?')) return false;
    const doc = JSON.parse(JSON.stringify(r.doc));
    const ill = $('#asmIll') && $('#asmIll').checked;
    for (const nd of doc.nodes){ if (nd.type === 'T03' && ill) nd.config = DCF_T03(); }
    S.doc = {name: doc.name, cutoff: $('#cutoff').value.trim(), viewport: {}, nodes: doc.nodes, edges: doc.edges};
    S.example = null; S.assembly = {question: r.question, chains: r.chains, human: r.human, gaps: r.gaps};
    S.wfId = null; S.wfVersion = null; S.history = []; S.run = null; S.runId = null; S.issues = []; S.sel = null; S.selEdge = null;
    stopPoll(); renderRunbar(); setHash(); S.dirty = true; S.editedSinceRun = false; renderAll(); fit();
    if ($('#dlg').open) $('#dlg').close();
    doValidate(true);
    return true;
  };
  $('#asmPlace').onclick = () => { if (place()) toast(human.length ? `배치했어요. 「사람 차례」 ${human.length}곳을 먼저 확인해 주세요.` : '배치했어요. 「실행」을 누르면 됩니다.'); };
  $('#asmRun').onclick = async () => { if (!place()) return; const ok = await doValidate(true); if (ok) runAgent(); else toast('실행 전에 손볼 것이 있어요. 아래 목록의 버튼을 눌러 보세요.'); };
  $('#asmOld').onclick = askPlan;
}
async function openQuestionMap(){
  $('#dlgBody').innerHTML = '<h2>질문 지도</h2><p><span class="spin"></span> 불러오는 중…</p>'; openWide();
  let m; try { m = await api('/api/agent/assemble/map'); } catch(e){ $('#dlgBody').innerHTML = `<h2>질문 지도</h2><p class="stale-note">${esc(e.message)}</p>`; return; }
  const bar = (c) => `<span class="qbar" style="width:${Math.max(6, Math.round(c / Math.max(1, m.total) * 220))}px"></span> ${c}`;
  $('#dlgBody').innerHTML = `<h2>질문 지도 <span class="mute">— 지금까지 물어본 질문 ${m.total}개</span></h2>
    <p class="mute">「목표부터 조립」에 들어온 질문을 모아, 어떤 근거 사슬이 쓰였고 어떤 노드가 비어 있었는지 보여 줘요. 이 PC의 앱 안에만 저장돼요.</p>
    <h3>아직 없어서 답하지 못한 것 (만들 우선순위 후보)</h3>
    ${m.gaps.length ? `<table><tr><th>필요했던 노드</th><th>질문 수</th><th>예시 질문</th></tr>${m.gaps.map(g => `<tr><td>${esc(g.label)} <span class="mono mute">${esc(g.id)}</span></td><td>${bar(g.count)}</td><td class="mute">${g.examples.map(esc).join('<br>')}</td></tr>`).join('')}</table>` : '<p class="mute">아직 없어요.</p>'}
    <h3>많이 쓰인 목표</h3>
    ${m.goals.length ? `<table>${m.goals.map(g => `<tr><td>${esc(g.label)} <span class="mono mute">${esc(g.id)}</span></td><td>${bar(g.count)}</td></tr>`).join('')}</table>` : '<p class="mute">아직 없어요.</p>'}
    <h3>자주 쓰인 근거 사슬</h3>
    ${m.chains.length ? `<table>${m.chains.map(c => `<tr><td class="mono">${esc(c.chain)}</td><td>${c.count}</td></tr>`).join('')}</table>` : '<p class="mute">아직 없어요.</p>'}`;
}
function openPersonaQuiz(){
  const Q = [['q1','공시(사업보고서)나 재무제표를 직접 읽어 본 적이 있나요?',[['y','네, 여러 번'],['n','아니요 / 거의 없음']]],
             ['q2','DCF·PER 같은 가치평가를 직접 계산해 본 적이 있나요?',[['y','네'],['n','아니요']]],
             ['q3','처음 볼 때 어떤 쪽이 편한가요?',[['narrow','한 가지를 깊게 (좁게)'],['wide','여러 관점을 한 번에 (넓게)']]]];
  $('#dlgBody').innerHTML = `<h2>내 유형 정하기 (3문항)</h2>
    <p class="mute">리서치 경험과 보고 싶은 범위만 묻습니다. 투자 성향(위험 선호)을 분류하거나, 이에 따라 다른 숫자·종목·매매 판단을 보여 주지 않습니다. 답은 이 브라우저에만 저장됩니다.</p>
    ${Q.map(([k, q, opts]) => `<div class="pq"><b>${esc(q)}</b><div>${opts.map(([v, l]) => `<label><input type="radio" name="${k}" value="${v}"> ${esc(l)}</label>`).join(' ')}</div></div>`).join('')}
    <div class="prow"><button class="primary" id="bPersonaOk">결과 보기</button>${S.persona ? ' <button id="bPersonaClear">유형 지우기</button>' : ''}</div><div id="personaOut"></div>`;
  openWide();
  if ($('#bPersonaClear')) $('#bPersonaClear').onclick = () => { savePersona(null); renderPanel(); openExamplePicker(); };
  $('#bPersonaOk').onclick = () => { const v = k => (document.querySelector(`input[name=${k}]:checked`) || {}).value;
    if (!v('q1') || !v('q2') || !v('q3')) { $('#personaOut').innerHTML = '<p class="stale-note">세 문항 모두 골라 주세요.</p>'; return; }
    const key = `${v('q1') === 'y' && v('q2') === 'y' ? 'expert' : 'novice'}-${v('q3')}`; savePersona(key);
    const p = PERSONAS[key], ex = EXAMPLES.find(e => e.id === p.example);
    $('#personaOut').innerHTML = `<div class="ok-note"><b>${esc(p.label)}</b> — ${esc(p.desc)}<br><span class="mute">입문/숙련은 두 경험 문항이 모두 「네」일 때 숙련입니다. 입문이면 사례 설명을 자세히 펼치고, 숙련이면 간단히 접어 둡니다.</span></div>
      <p>추천 사례: <b>${esc(ex.title)}</b></p><button class="primary" id="bPersonaGo">추천 사례 불러오기</button> <button id="bPersonaList">다른 사례 보기</button>`;
    $('#bPersonaGo').onclick = () => loadExample(ex.id); $('#bPersonaList').onclick = openExamplePicker; renderPanel(); };
}


/* ---------------- agent (rule-based self-correcting runner) ---------------- */
const AKIND = {iter:'회차', run:'실행', fix:'자동 수정', ask:'사람 확인', accept:'받아들임', stop:'중단', retry:'재시도', gate:'근거 관문', end:'종료'};
const ASTATUS = {running:'진행 중', completed:'완료', needs_human:'사람 확인 필요', stopped:'중단', failed:'오류', interrupted:'서버 재시작으로 중단'};
async function runAgent(){
  if (!S.doc.nodes.length){ toast('캔버스에 노드가 없습니다. 「예시 사례」를 불러오거나 노드를 배치하세요.'); return; }
  if (S.poll || (S.run && ACTIVE.includes(S.run.status))){ toast('실행이 끝난 뒤 다시 누르세요.'); return; }
  let r;
  try { r = await api('/api/agent/runs', {method:'POST', body:{doc:S.doc, goal:S.doc.name}}); }
  catch(e){ if (e.data && e.data.issues){ S.issues = e.data.issues; renderIssues(); } toast('에이전트 시작 실패: ' + e.message); return; }
  S.agentId = r.id; S.agentStartName = S.doc.name;
  $('#dlgBody').innerHTML = `<h2>에이전트 실행</h2><div id="agBody"><p><span class="spin"></span> 시작했습니다…</p></div>`;
  openWide();
  const tick = async () => {
    let a; try { a = await api('/api/agent/runs/' + S.agentId); } catch(e){ return; }
    if ($('#agBody')) $('#agBody').innerHTML = agentHtml(a);
    if (a.status === 'running'){ S.agentTimer = setTimeout(tick, 600); return; }
    applyAgentResult(a);
  };
  tick();
}
function agentHtml(a){
  const ch = a.changes || [], asks = a.asks || [], acc = a.accepted || [];
  const head = `<div class="prow"><span class="chip s-${a.status === 'completed' ? 'succeeded' : a.status === 'running' ? 'running' : a.status === 'needs_human' ? 'held' : 'failed'}">${a.status === 'running' ? '<span class="spin"></span>' : ''}${ASTATUS[a.status] || a.status}</span>
    <span class="mute">${a.iteration || 0}회차 / 최대 ${a.max_iters} · 실행 ${(a.runs || []).length}번 · 자동 수정 ${ch.length}건 · AI 모델 0회</span></div>${a.note ? `<p><b>${esc(a.note)}</b></p>` : ''}`;
  let h = head;
  if (ch.length) h += `<h3>에이전트가 바꾼 것</h3><table><tr><th>노드</th><th>항목</th><th>전</th><th>후</th></tr>${ch.map(c => `<tr><td>${esc(c.node)}</td><td>${esc(c.field)}</td><td>${esc(fmtVal(c.before))}</td><td><b>${esc(c.label || fmtVal(c.after))}</b>${c.need ? `<div class="mute">조건: ${esc(c.need.join(', '))} 승인 · 후보 ${c.candidates}개</div>` : ''}</td></tr>`).join('')}</table>`;
  if (asks.length) h += `<h3>사람이 해야 할 일</h3><ul>${asks.map(x => `<li><b>${esc(x.node || '')}</b> ${esc(x.reason || x.message || '')}<br><span class="mute">→ ${esc(x.ask || '')} (규칙 ${esc(x.rule)})</span></li>`).join('')}</ul>`;
  if (acc.length) h += `<h3>받아들인 한계</h3><ul>${acc.map(x => `<li>${esc(x.node)} ${esc(STATUS[x.status] || x.status)} — ${esc(x.reason || '')}</li>`).join('')}</ul>`;
  const sm = a.summary;
  if (sm){ h += `<h3>근거 검증된 요약 <span class="mute" style="font-weight:normal">— 모든 숫자가 공시 셀·승인 전망·노드 계산 패킷에 연결된 문장만 공개 (연결 값 ${sm.bound || 0}개, 보류 ${(sm.held || []).length}문장)</span></h3>`;
    h += sm.error ? `<div class="stale-note">관문 오류로 요약을 공개하지 않았습니다: ${esc(sm.error)}</div>` : `<ul class="agsum">${(sm.published || []).map(t => `<li>${esc(t)}</li>`).join('')}</ul>`;
    if ((sm.held || []).length) h += `<details><summary>보류된 문장 ${sm.held.length}개</summary><ul>${sm.held.map(x => `<li>${esc(x.text)} <span class="mute">— ${esc(x.reason)}</span></li>`).join('')}</ul></details>`; }
  h += `<h3>진행 기록</h3><table class="aglog"><tr><th>회차</th><th>종류</th><th>내용</th><th>근거 원칙</th></tr>${(a.steps || []).filter(s => s.kind !== 'iter').map(s => `<tr class="k-${s.kind}"><td>${s.iteration}</td><td>${AKIND[s.kind] || s.kind}</td><td>${esc(s.msg)}</td><td class="mute">${esc(s.why || '')}</td></tr>`).join('')}</table>`;
  h += `<p class="hint">에이전트는 규칙표만 따릅니다: 전망 승인·매매 판단·공식 원문 값·기준시점은 바꾸지 않습니다. <a href="#" id="agRules">규칙표 보기</a></p>`;
  setTimeout(() => { const l = $('#agRules'); if (l) l.onclick = ev => { ev.preventDefault(); showAgentRules(); }; }, 0);
  return h;
}
function fmtVal(v){ return Array.isArray(v) ? v.join(', ') : (v === '' || v == null ? '(비어 있음)' : String(v)); }
async function applyAgentResult(a){
  if (a.doc_final && (a.changes || []).length){ S.doc = a.doc_final; S.doc.name = S.agentStartName; S.dirty = true; }
  if (a.final_run){ S.editedSinceRun = false; await loadRun(a.final_run); setHash(); }
  renderAll();
  toast(a.status === 'completed' ? '에이전트 완료. 결과가 캔버스에 반영됐습니다.' : '에이전트가 멈췄습니다. 대화상자의 「사람이 해야 할 일」을 확인하세요.');
}
async function showAgentRules(){
  const r = await api('/api/agent/rules');
  $('#dlgBody').innerHTML = `<h2>에이전트 규칙표</h2><p class="mute">노드 상태·이유 코드 → 행동. 위에서부터 처음 맞는 규칙 하나를 씁니다. 모르는 상황(R99)은 추측하지 않고 사람에게 넘깁니다.</p>
    <table><tr><th>규칙</th><th>대상</th><th>상황</th><th>행동</th><th>원칙</th></tr>${r.rules.map(x => `<tr><td>${x.id}</td><td>${x.scope === 'check' ? '실행 전 검증' : esc(x.node === '*' ? '모든 노드' : x.node)}</td><td>${esc(x.title)}<div class="mute">${esc(x.status)} · ${esc(x.code)}</div></td><td><b>${esc(r.labels[x.action] || x.action)}</b></td><td class="mute">${esc(x.why)}${x.ask ? '<br>→ ' + esc(x.ask) : ''}</td></tr>`).join('')}</table>
    <button id="agBack">에이전트 결과로 돌아가기</button>`;
  openWide();
  $('#agBack').onclick = async () => { if (!S.agentId) return; const a = await api('/api/agent/runs/' + S.agentId); $('#dlgBody').innerHTML = `<h2>에이전트 실행</h2><div id="agBody">${agentHtml(a)}</div>`; };
}


function terminalHint(p){
  const tw = Number(p.terminal_weight_pct); if (!(tw >= 60)) return '';
  const fc = (p.forecast_applied || []).length;
  return `<div class="interp"><b>해석 안내</b> 이 계산에서 주당가치의 <b>${tw.toFixed(1)}%</b>는 말기가치(T03에 입력한 정상화 FCFF)에서 나옵니다.
    ${fc ? `증권사 전망은 명시 기간(나머지 ${(100 - tw).toFixed(1)}%)에만 반영되므로, 전망이 크게 달라도 주당가치 차이는 작게 나옵니다.` : '명시 기간 가정보다 장기 가정이 결과를 좌우합니다.'}
    결과를 움직이는 핵심은 「정상화 이후 이익을 얼마로 보느냐」입니다. ${(S.example || {}).id === 'normalized-scenario' ? '→ 세 N02의 주당가치 차이가 바로 그 영향입니다.' : '→ 예시 사례 「정상화 이익 시나리오」로 비교하거나, T03에서 이의 제기로 정상화 FCFF를 바꿔 보세요.'}</div>`;
}

/* ---------------- objection -> re-deliberation ---------------- */
function canObject(n){
  return ['T03','T04','N02','N01'].includes(n.type) && S.run && S.runId && !ACTIVE.includes(S.run.status) && !S.editedSinceRun
    && (S.run.doc || {nodes:[]}).nodes.some(x => x.id === n.id);
}
async function openObjection(nodeId){
  let f; try { f = await api(`/api/agent/objection-fields?run_id=${S.runId}&node_id=${encodeURIComponent(nodeId)}`); } catch(e){ toast('이의 항목을 불러오지 못했습니다: ' + e.message); return; }
  const fields = f.fields;
  $('#dlgBody').innerHTML = `<h2>이의 제기 → 재심의 · ${esc(nodeId)} (${f.type})</h2>
    <p class="mute">원래 실행 결과는 그대로 두고, 같은 기준시점(${esc(f.cutoff || '')})으로 바꾼 구성을 에이전트가 다시 실행해 전후를 비교합니다. 공식 원문 사실의 값은 바꿀 수 없고, 재대조만 요청할 수 있습니다.</p>
    <div class="pq"><b>무엇에 동의하지 않나요?</b><br><select id="obField">${fields.map((x, i) => `<option value="${i}">${esc(x.label)}${x.current !== '' ? ' — 지금: ' + esc(x.options ? ((x.options.find(o => o.value === x.current) || {}).label || x.current) : x.current) : ''}</option>`).join('')}</select></div>
    <div class="pq" id="obValWrap"></div>
    <div class="pq"><b>사유 (필수, 기록에 남습니다)</b><br><textarea id="obReason" rows="3" style="width:100%" placeholder="예: 금리 수준을 보면 할인율 9%는 낮다고 봅니다."></textarea></div>
    <div class="prow"><button class="primary" id="obGo">재심의 요청</button></div><div id="obOut"></div>`;
  openWide();
  const renderVal = () => { const x = fields[+$('#obField').value];
    $('#obValWrap').innerHTML = x.field === '' ? '<span class="mute">값을 바꾸지 않고 공식 원문과 다시 대조합니다.</span>' :
      x.options ? `<b>바꿀 값</b><br><select id="obVal">${x.options.map(o => `<option value="${esc(o.value)}" ${o.value === x.current ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`
                : `<b>바꿀 값</b> <span class="mute">(지금 ${esc(x.current)})</span><br><input id="obVal" value="${esc(x.current)}">`; };
  $('#obField').onchange = renderVal; renderVal();
  $('#obGo').onclick = async () => { const x = fields[+$('#obField').value];
    const body = {run_id: S.runId, node_id: nodeId, field: x.field, value: x.field === '' ? '' : $('#obVal').value, reason: $('#obReason').value};
    let r; try { r = await api('/api/agent/objections', {method:'POST', body}); } catch(e){ $('#obOut').innerHTML = `<div class="stale-note">${esc(typeof e.data === 'string' ? e.data : e.message)}</div>`; return; }
    $('#obOut').innerHTML = '<p><span class="spin"></span> 재심의 중 (에이전트 실행)…</p>';
    const tick = async () => { const ob = await api('/api/agent/objections/' + r.id);
      if (ob.agent.status === 'running'){ setTimeout(tick, 600); return; }
      $('#dlgBody').innerHTML = objectionHtml(ob); openWide();
      $('#obApply') && ($('#obApply').onclick = async () => { S.doc = ob.agent.doc_final; S.dirty = true; S.editedSinceRun = false; await loadRun(ob.agent.final_run); setHash(); renderAll(); $('#dlg').close(); toast('재심의 구성과 결과를 캔버스에 적용했습니다. 저장하면 새 버전으로 남습니다.'); }); };
    tick(); };
}
function objectionHtml(ob){
  const c = ob.comparison || {}, ch = ob.change, ag = ob.agent;
  let h = `<h2>재심의 결과</h2><div class="prow"><span class="chip s-${ag.status === 'completed' ? 'succeeded' : 'held'}">${ASTATUS[ag.status] || ag.status}</span><span class="mute">이의 기록 ${esc(ob.id.slice(0, 8))} · ${esc(ob.created_at.slice(0, 19).replace('T', ' '))}</span></div>
    <table><tr><th>대상</th><td>${esc(ob.node)} · ${esc(ch.label)}</td></tr><tr><th>변경</th><td>${ch.field === '' ? '값 변경 없음 (원문 재대조)' : `${esc(ch.before)} → <b>${esc(ch.after)}</b>`}</td></tr><tr><th>사유</th><td>${esc(ob.reason)}</td></tr></table>`;
  if ((c.per_share || []).length) h += `<h3>주당가치 계산 전후</h3><table><tr><th>노드</th><th>원래</th><th>재심의</th><th>변화</th></tr>${c.per_share.map(r => `<tr><td>${esc(r.node)}</td><td>${r.before ? Number(r.before).toLocaleString('ko-KR', {maximumFractionDigits: 2}) + '원' : '—'}</td><td><b>${r.after ? Number(r.after).toLocaleString('ko-KR', {maximumFractionDigits: 2}) + '원' : '—'}</b></td><td>${r.change_pct ? r.change_pct + '%' : '—'}</td></tr>`).join('')}</table><p class="hint">같은 기준시점·같은 사실에서 이의 항목만 바꾼 계산입니다. 목표주가나 매매 의견이 아닙니다.</p>`;
  if (ob.node_type === 'N01') h += `<h3>원문 재대조</h3><p>${c.facts_compared}건을 다시 대조했고, ${c.facts_changed && c.facts_changed.length ? `<b>${c.facts_changed.length}건이 달라졌습니다: ${esc(c.facts_changed.join(', '))}</b>` : '<b>모두 원래 값과 같습니다.</b> 공식 원문 기준으로 숫자는 바뀌지 않습니다.'}</p>`;
  if ((c.status_changes || []).length) h += `<h3>노드 상태 변화</h3><ul>${c.status_changes.map(x => `<li>${esc(x.node)}: ${esc(STATUS[x.before] || x.before || '—')} → ${esc(STATUS[x.after] || x.after || '—')}</li>`).join('')}</ul>`;
  if ((ag.asks || []).length) h += `<h3>사람이 해야 할 일</h3><ul>${ag.asks.map(x => `<li>${esc(x.node || '')} ${esc(x.reason || x.message || '')} → ${esc(x.ask || '')}</li>`).join('')}</ul>`;
  const sm = ag.summary; if (sm && (sm.published || []).length) h += `<details><summary>근거 검증된 요약 (${sm.published.length}문장, 보류 ${(sm.held || []).length})</summary><ul class="agsum">${sm.published.map(t => `<li>${esc(t)}</li>`).join('')}</ul></details>`;
  h += ag.final_run ? `<div class="prow"><button class="primary" id="obApply">재심의 구성을 캔버스에 적용</button><span class="mute">적용하지 않으면 원래 구성과 결과가 그대로 남습니다. 이의 기록은 어느 쪽이든 보존됩니다.</span></div>` : '';
  return h;
}


/* ---------------- documents (RAG T1) & DART XBRL ---------------- */
S.dTab = 'search';
async function openDocs(){
  const tabs = [['search','사업보고서 검색'],['eval','검색 평가'],['xbrl','DART 재무데이터(XBRL)']];
  $('#dlgBody').innerHTML = `<h2>문서·재무</h2><div class="tabs">${tabs.map(([k,l]) => `<button data-dt="${k}" class="${S.dTab===k?'on':''}">${l}</button>`).join('')}</div><div id="docBody"><p><span class="spin"></span> 불러오는 중…</p></div>`;
  openWide();
  $('#dlgBody').querySelectorAll('[data-dt]').forEach(b => b.onclick = () => { S.dTab = b.dataset.dt; openDocs(); });
  if (S.dTab === 'search') return docSearchView();
  if (S.dTab === 'eval') return docEvalView();
  return xbrlView();
}
async function docSearchView(){
  let st; try { st = await api('/api/rag/status'); } catch(e){ $('#docBody').innerHTML = `<div class="stale-note">${esc(e.message)}</div>`; return; }
  if (!st.ready){ $('#docBody').innerHTML = `<div class="stale-note">${esc(st.error)}</div>`; return; }
  $('#docBody').innerHTML = `<p class="mute">2025 사업보고서 전체 (${st.receipts.map(r => `${r[0] === '005930' ? '삼성전자' : 'SK하이닉스'} ${r[1]}`).join(', ')}) · ${st.files}개 대목차 · ${st.chunks.toLocaleString()}개 청크 · 검색 방식: <b>${st.vectors ? 'BM25 + 임베딩(' + esc(st.model) + ') RRF' : 'BM25 (임베딩 미생성)'}</b> · 색인 ${esc(st.corpusHash)}</p>
    <div class="askrow"><select id="rgCo"><option value="">전체</option><option value="005930">삼성전자</option><option value="000660">SK하이닉스</option></select>
      <input id="rgQ" placeholder="예: 직원 수와 평균 근속연수 / 이사회 구성 / 환율 변동 위험" maxlength="300"><button class="primary" id="rgGo">검색</button></div>
    <p class="hint">검색 결과는 원문 조각과 위치(대목차·제목 경로·표 번호·행)입니다. 답을 지어내지 않으며, 숫자를 쓸 때는 원문에서 직접 확인하세요.</p><div id="rgOut"></div>`;
  const go = async () => { const q = $('#rgQ').value.trim(); if (!q) return; $('#rgOut').innerHTML = '<p><span class="spin"></span></p>';
    const r = await api('/api/rag/search', {method:'POST', body:{query:q, company:$('#rgCo').value || null, k:10}});
    const terms = [...new Set(q.split(/\s+/).filter(t => t.length >= 2))];
    const hl = t => { let x = esc(t); terms.forEach(w => { x = x.split(esc(w)).join(`<mark>${esc(w)}</mark>`); }); return x; };
    $('#rgOut').innerHTML = `<p class="mute">방식 ${esc(r.mode)}${r.note ? ' · ' + esc(r.note) : ''}${r.expanded !== r.query ? ' · 동의어 확장: ' + esc(r.expanded.slice(r.query.length).trim()) : ''}</p>` +
      r.hits.map(h => `<div class="rghit"><div><b>${h.rank}</b> <span class="chip">${esc(h.company)}</span> <span class="mute">${esc(h.path.join(' > '))}</span> <span class="tag">${h.kind === 'table' ? '표' + (h.source.table ? ' ' + h.source.table : '') + (h.source.rows ? ' · ' + h.source.rows.join('~') + '행' : '') : '본문'}</span></div>
        <pre class="rgtext">${h.text.split('\n').map(l => { const key = terms.some(w => l.includes(w)) || /합\s*계|총\s*계|전\s*체/.test(l); return key ? `<span class="hlline">${hl(l)}</span>` : hl(l); }).join('\n')}</pre>
        <div class="mute">원문 해시 ${esc(h.source.file.slice(0, 12))} · <a href="${esc(h.source.url)}" target="_blank" rel="noopener">DART 원문 보기</a> · ${esc(h.id)}</div></div>`).join(''); };
  $('#rgGo').onclick = go; $('#rgQ').onkeydown = e => { if (e.key === 'Enter') go(); }; $('#rgQ').focus();
}
async function docEvalView(){
  $('#docBody').innerHTML = '<p><span class="spin"></span> 평가 질문 16개 검색 중…</p>';
  const r = await api('/api/rag/eval'); const a = r.with_synonyms, b = r.without_synonyms;
  const sumRow = (n, x) => `<tr><td>${n}</td>${['dev','holdout','all'].map(s => ['@5','@10','@16'].map(k => `<td>${x.summary[s][k]}</td>`).join('')).join('')}</tr>`;
  $('#docBody').innerHTML = `<p class="mute">${esc(a.definition)} 질문 출처: 2차_실제 tableaware 앱의 개발·미사용 질문(삼성전자). 동의어 목록은 질문을 본 뒤 작성되어, 동의어 포함 결과는 완전한 미사용 평가가 아닙니다.</p>
    <table><tr><th rowspan="2">방식 (${esc(a.mode)})</th><th colspan="3">개발 8</th><th colspan="3">미사용 8</th><th colspan="3">전체 16</th></tr><tr>${'<th>@5</th><th>@10</th><th>@16</th>'.repeat(3)}</tr>${sumRow('동의어 없음', b)}${sumRow('동의어 포함', a)}</table>
    <h3>질문별 (동의어 포함)</h3><table><tr><th>ID</th><th>질문</th><th>기대값</th><th>처음 나온 순위</th></tr>${a.rows.map(x => `<tr><td>${x.id}</td><td>${esc(x.question)}</td><td>${esc(x.values.join(', '))}</td><td>${x.first_rank || '없음'}</td></tr>`).join('')}</table>
    <p class="hint">한계: 짧은 기대값(예: 11.3, 적정)은 다른 문맥에서 우연히 맞을 수 있습니다. 비교 대상 앱은 답변 단계에서 개발 8/8·미사용 답변 가능 8/8을 보고했습니다(검색 단계 지표와 직접 비교 불가).</p>`;
}
async function xbrlView(){
  const st = await api('/api/xbrl/status');
  $('#docBody').innerHTML = `<p class="mute">DART OpenAPI 「단일회사 전체 재무제표」(XBRL 기반 표준 계정)로 숫자를 가져와, 사업보고서 표에서 읽은 값(N01)과 대조합니다.
    API 키는 서버 환경변수로만 쓰이며 화면·로그·저장 파일에 남지 않습니다. 한 번 가져온 응답은 해시와 함께 저장되어 같은 호출을 반복하지 않습니다.</p>
    ${st.key_configured ? '<div class="ok-note">API 키 설정됨</div>' : '<div class="stale-note">API 키가 설정되지 않았습니다. 앱 폴더의 local-env.cmd에 <code>set DART_API_KEY=발급받은키</code>를 넣고 서버를 다시 시작하세요 (예시: local-env.example.cmd). 키를 대화창에 붙여 넣지 마세요.</div>'}
    <div class="prow"><select id="xbCo">${Object.entries(st.companies).map(([k, v]) => `<option value="${k}">${esc(v.name)}</option>`).join('')}</select>
    <select id="xbY"><option>2025</option></select><label><input type="checkbox" id="xbRf"> 저장본 무시하고 다시 받기</label><button class="primary" id="xbGo">가져오기</button></div>
    <div class="mute">저장본: ${st.cached.length ? esc(st.cached.join(', ')) : '없음'}</div><div id="xbOut"></div>`;
  $('#xbGo').onclick = async () => { $('#xbOut').innerHTML = '<p><span class="spin"></span></p>';
    let r; try { r = await api('/api/xbrl/fetch', {method:'POST', body:{company:$('#xbCo').value, year:+$('#xbY').value, refresh:$('#xbRf').checked}}); }
    catch(e){ $('#xbOut').innerHTML = `<div class="stale-note">${esc(typeof e.data === 'string' ? e.data : e.message)}</div>`; return; }
    const s = r.summary;
    $('#xbOut').innerHTML = `<div class="${s.matched === s.compared ? 'ok-note' : 'stale-note'}">항목 ${s.facts}개 · 표 값과 대조 ${s.compared}개 중 <b>${s.matched}개 일치</b>${s.matched !== s.compared ? ' — 불일치는 아래 표에서 확인하세요(자동으로 고치지 않음)' : ''} · 접수번호 ${esc(r.rcept_no || '')} · ${r.cache.cached ? '저장본 사용' : '새로 받음'} · 응답 해시 ${esc(r.cache.sha256.slice(0, 12))}</div>
      <h3>표 값(N01)과 대조</h3><table><tr><th>연도</th><th>항목</th><th>XBRL</th><th>사업보고서 표</th><th>결과</th></tr>${r.crosscheck.map(x => `<tr><td>${x.year}</td><td>${esc(x.label)}</td><td class="num">${fmt(x.xbrl)}</td><td class="num">${fmt(x.cell)}</td><td>${x.match ? '✓ 일치' : '✗ 차이 ' + fmt(x.diff)}</td></tr>`).join('')}</table>
      <h3>가져온 항목 ${kindTag('fact_official')}</h3><table><tr><th>연도</th><th>항목</th><th>값</th><th>계정 ID</th><th>재무제표</th></tr>${r.facts.map(f => `<tr><td>${f.year}</td><td>${esc(f.label)}</td><td class="num">${fmt(f.value)} ${esc(f.unit)}</td><td class="mono">${esc(f.account_id)}</td><td>${esc(f.sj_div)}</td></tr>`).join('')}</table>`; };
}

/* ---------------- canvas render ---------------- */
function nodeStatus(id){
  if (!S.run) return null;
  return S.run.nodes.find(n => n.node_id === id) || null;
}
function renderAll(){ renderNodes(); renderEdges(); renderPanel(); renderHeader(); renderFocus(); $('#empty').style.display = S.doc.nodes.length ? 'none' : 'flex'; }
function renderHeader(){
  $('#wfName').value = S.doc.name; $('#cutoff').value = S.doc.cutoff || '';
  const active = S.run && ACTIVE.includes(S.run.status);
  $('#bRun').disabled = !!active; $('#bCancel').disabled = !active;
  document.title = (S.dirty ? '● ' : '') + S.doc.name + ' · 모두의리서치 · 기업분석';
}
function badIds(){ const s = new Set(); S.issues.filter(i => i.severity === 'error').forEach(i => i.nodes.forEach(n => s.add(n))); return s; }
/* v0.23.4: 관점 하나만 진하게 — 그 관점 노드 + 그 노드로 자료를 보내는 도구 + 보고서 취합 */
function focusSet(){
  if (!S.focus) return null;
  const on = new Set(S.doc.nodes.filter(n => spec(n.type)?.perspective === S.focus).map(n => n.id));
  S.doc.edges.forEach(e => { if (on.has(e.to_node) && spec(nodeById(e.from_node)?.type)?.perspective === 'common') on.add(e.from_node); });
  if (on.size) S.doc.nodes.filter(n => n.type === 'T05').forEach(n => on.add(n.id));
  return on;
}
function renderFocus(){
  const box = $('#pfocus'); if (!box || !S.reg) return;
  const has = new Set(S.doc.nodes.map(n => spec(n.type)?.perspective));
  const ps = S.reg.perspectives.filter(([id]) => has.has(id));
  box.innerHTML = ps.length < 2 ? '' : '관점만 진하게: ' + [['', '전체']].concat(ps).map(([id, l]) =>
    `<button data-pf="${id}" class="${(S.focus || '') === id ? 'on' : ''}" style="--pc:${id ? `var(--p-${id})` : '#888'}">${esc(l)}</button>`).join('');
  box.querySelectorAll('[data-pf]').forEach(b => b.onclick = () => { S.focus = b.dataset.pf || ''; renderNodes(); renderEdges(); renderFocus();
    if (S.focus){ const f = focusSet(); const nm = persLabel(S.focus); const ns = S.doc.nodes.filter(n => f.has(n.id) && spec(n.type)?.perspective === S.focus).map(n => n.type).join(' → ');
      toast(`${nm}: 자료 도구 ${[...f].filter(id => spec(nodeById(id).type).perspective === 'common' && nodeById(id).type !== 'T05').length}개 → ${ns}. 위에서 아래, 왼쪽에서 오른쪽 순서로 읽으세요.`); } });
}
function renderNodes(){
  const bad = badIds();
  if (S.focus && !S.doc.nodes.some(n => spec(n.type)?.perspective === S.focus)) S.focus = '';
  const fset = focusSet();
  const wrap = $('#nodes'); wrap.innerHTML = '';
  for (const n of S.doc.nodes){
    const sp = spec(n.type); if (!sp) continue;
    const st = nodeStatus(n.id);
    const el = document.createElement('div');
    el.className = 'node' + (S.sel === n.id ? ' sel' : '') + (bad.has(n.id) ? ' bad' : '') + (fset ? (fset.has(n.id) ? ' focus' : ' dim') : '');
    el.style.left = n.x + 'px'; el.style.top = n.y + 'px'; el.dataset.id = n.id;
    el.style.setProperty('--pc', `var(--p-${sp.perspective})`);
    const ins = sp.inputs.map(p => `<div class="port in ${p.required?'req':'opt'}" data-node="${n.id}" data-port="${p.name}" data-dir="in" data-type="${p.type}" title="${esc(p.label)} (${p.type})${p.required?'':' · 선택'}"><span class="dot"></span><span class="lbl">${esc(p.label)}</span></div>`).join('');
    const outs = sp.outputs.map(p => `<div class="port out" data-node="${n.id}" data-port="${p.name}" data-dir="out" data-type="${p.type}" title="${esc(p.label)} (${p.type})"><span class="lbl">${esc(p.label)}</span><span class="dot"></span></div>`).join('');
    let stHtml = `<span class="badge b-${sp.implementation}">${IMPL[sp.implementation]}</span>`;
    if (st){
      const stale = S.editedSinceRun ? ' (이전 실행)' : '';
      stHtml += ` <span class="chip s-${S.editedSinceRun ? 'stale' : st.status}">${st.status==='running'?'<span class="spin"></span>':''}${STATUS[st.status]}${stale}</span>`;
      if (st.stalled) stHtml += ' <span class="chip s-held">응답 없음</span>';
    }
    el.innerHTML = `<div class="hd"><b>${n.type}</b><span class="nm">${esc(sp.display_name)}</span><span class="tier">${TIER[sp.tier]}</span></div>
      <div class="ports"><div class="col">${ins}</div><div class="col">${outs}</div></div><div class="st">${stHtml}</div>`;
    wrap.appendChild(el);
  }
  markArmed();
}
function portEl(node, port, dir){ return document.querySelector(`.port[data-node="${CSS.escape(node)}"][data-port="${CSS.escape(port)}"][data-dir="${dir}"] .dot`); }
function portXY(el){
  const w = $('#world').getBoundingClientRect(), r = el.getBoundingClientRect();
  return [(r.left + r.width/2 - w.left)/S.scale, (r.top + r.height/2 - w.top)/S.scale];
}
const SHORT = {OfficialCorpus:'공식 원문', FactPackage:'확인된 사실', MacroExposure:'거시 노출', AssumptionSet:'사용자 가정',
  BrokerForecastPackage:'승인 전망', ValuationResult:'가치평가 결과', PriceSeries:'가격 자료', FlowSeries:'수급 자료', CompanyFilings:'공시 재무', OwnershipData:'지분 공시', DocPassages:'원문 문단', MacroSeries:'거시 지표',
  NewsEvents:'뉴스·사건', IndustryPeers:'비교기업 자료', NodeFinding:'분석 결과', Report:'보고서'};
/* Edge state: design = before any run (dashed if the sender has no data source);
   flowed = sender produced a packet in the shown run; blocked = sender produced nothing. */
function edgeState(e){
  const from = nodeById(e.from_node);
  const noSource = from && spec(from.type).implementation === 'not_connected';
  if (!S.run || S.editedSinceRun) return noSource ? 'nc' : 'design';
  const st = nodeStatus(e.from_node);
  if (!st) return noSource ? 'nc' : 'design';
  if (st.output_packet && ['succeeded','partial'].includes(st.status)) return st.status === 'partial' ? 'flowed-partial' : 'flowed';
  return 'blocked';
}
const EDGE_TEXT = {design:'', nc:'자료 없음', flowed:'', 'flowed-partial':'일부', blocked:'전달 안 됨'};
function renderEdges(){
  const svg = $('#edges'); let h = '';
  const badEdges = new Set(S.issues.filter(i => i.edge !== null && i.edge !== undefined && i.severity === 'error').map(i => i.edge));
  S.doc.edges.forEach((e, i) => {
    const a = portEl(e.from_node, e.from_port, 'out'), b = portEl(e.to_node, e.to_port, 'in');
    if (!a || !b) return;
    const [x1,y1] = portXY(a), [x2,y2] = portXY(b), dx = Math.max(60, Math.abs(x2-x1)/2);
    const d = `M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`;
    const ty = spec(nodeById(e.from_node).type).outputs.find(p => p.name === e.from_port)?.type || '';
    const st = edgeState(e);
    const fs = focusSet(), dm = fs && !(fs.has(e.from_node) && fs.has(e.to_node)) ? ' dim' : (fs ? ' focus' : '');
    h += `<path class="hit" d="${d}" data-edge="${i}"><title>${esc((SHORT[ty]||ty) + ' · ' + ty)}</title></path><path class="e-${st} ${S.selEdge===i?'sel':''} ${badEdges.has(i)?'bad':''}${dm}" d="${d}" data-edge="${i}" marker-end="url(#arr-${st.startsWith('flowed')?'on':'off'})"></path>`;
    const extra = EDGE_TEXT[st] ? ` · ${EDGE_TEXT[st]}` : '';
    h += `<text class="t-${st}${dm}" x="${(x1+x2)/2}" y="${(y1+y2)/2 - 5}" text-anchor="middle">${esc((SHORT[ty] || ty) + extra)}</text>`;
  });
  svg.innerHTML = `<defs><marker id="arr-off" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#a8a396"></path></marker>
    <marker id="arr-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="#2f6f3a"></path></marker></defs>` + h;
  $('#bDelEdge').disabled = S.selEdge === null;
}
function applyView(){ $('#world').style.transform = `translate(${S.pan.x}px,${S.pan.y}px) scale(${S.scale})`; }
function zoom(f, cx, cy){
  const c = $('#canvas').getBoundingClientRect(); cx = cx ?? c.width/2; cy = cy ?? c.height/2;
  const ns = Math.min(2, Math.max(0.3, S.scale * f));
  S.pan.x = cx - (cx - S.pan.x) * ns / S.scale; S.pan.y = cy - (cy - S.pan.y) * ns / S.scale; S.scale = ns; applyView(); renderEdges();
}
function fit(){
  if (!S.doc.nodes.length){ S.scale = 1; S.pan = {x:20,y:20}; applyView(); return; }
  const xs = S.doc.nodes.map(n => n.x), ys = S.doc.nodes.map(n => n.y);
  const minX = Math.min(...xs), minY = Math.min(...ys), maxX = Math.max(...xs) + 240, maxY = Math.max(...ys) + 150;
  const c = $('#canvas').getBoundingClientRect();
  S.scale = Math.max(0.3, Math.min(1.2, Math.min((c.width-40)/(maxX-minX), (c.height-40)/(maxY-minY))));
  S.pan = {x: 20 - minX*S.scale, y: 20 - minY*S.scale}; applyView(); renderEdges();
}
function autoLayout(){
  const depth = {}; const ids = S.doc.nodes.map(n => n.id);
  const preds = id => S.doc.edges.filter(e => e.to_node === id).map(e => e.from_node);
  const d = (id, seen=new Set()) => { if (depth[id] !== undefined) return depth[id]; if (seen.has(id)) return 0; seen.add(id);
    const p = preds(id); return depth[id] = p.length ? 1 + Math.max(...p.map(x => d(x, seen))) : 0; };
  ids.forEach(id => d(id));
  const rows = {};
  for (const n of S.doc.nodes){ const k = depth[n.id]; rows[k] = (rows[k] || 0); n.x = 40 + k*300; n.y = 40 + rows[k]*140; rows[k]++; }
  touch(); renderAll(); fit();
}

/* ---------------- interactions ---------------- */
function markArmed(){
  document.querySelectorAll('.port').forEach(p => p.classList.remove('armed','target','reject'));
  if (!S.armed) return;
  document.querySelectorAll('.port').forEach(p => {
    if (p.dataset.dir === 'out' && p.dataset.node === S.armed.node && p.dataset.port === S.armed.port) p.classList.add('armed');
    if (p.dataset.dir === 'in') p.classList.add((p.dataset.type === S.armed.type || p.dataset.type === 'Any') && p.dataset.node !== S.armed.node ? 'target' : 'reject');
  });
}
function clickPort(p){
  if (p.dataset.dir === 'out'){ S.armed = {node:p.dataset.node, port:p.dataset.port, type:p.dataset.type}; markArmed(); toast('초록색으로 빛나는 입력 칸이 이 자료를 받을 수 있는 곳이에요. 빨간 칸을 누르면 맞는 노드를 알려 드려요. (Esc: 취소)'); return; }
  if (!S.armed){ const n = nodeById(p.dataset.node); const miss = n ? missingInputs(n).find(i => i.name === p.dataset.port) : null;
    if (miss){ const mk = producersOf(miss.type)[0]; toast(`이 칸은 ${J('「'+typeLabel(miss.type)+'」','을를')} 받아요.` + (mk ? ` ${nodeLabel(mk.id)}의 출력(오른쪽 ●)을 먼저 누르거나, 오른쪽 패널의 「필요한 앞 노드 채우기」를 써 보세요.` : '')); return; }
    toast('먼저 보낼 쪽 노드의 출력(오른쪽 ●)을 누르세요.'); return; }
  const tgtType = p.dataset.type;
  if (tgtType !== 'Any' && tgtType !== S.armed.type){
    showConnectHelp({from:S.armed, to:{node:p.dataset.node, port:p.dataset.port, type:tgtType}}); return;
  }
  if (p.dataset.node === S.armed.node){ toast('노드를 자기 자신에 연결할 수 없습니다.'); return; }
  const e = {from_node:S.armed.node, from_port:S.armed.port, to_node:p.dataset.node, to_port:p.dataset.port};
  if (S.doc.edges.some(x => x.from_node===e.from_node && x.from_port===e.from_port && x.to_node===e.to_node && x.to_port===e.to_port)){ toast('이미 연결돼 있습니다.'); return; }
  S.doc.edges.push(e); S.armed = null; touch(); renderAll();
}
// 한국어 조사: 마지막 글자의 받침에 따라 은/는, 이/가, 을/를, 과/와, 으로/로
function J(w, pair){
  const t = String(w).replace(/[」』)\]\s]+$/,''); const ch = t.slice(-1); const c = ch.charCodeAt(0);
  let fin = null;
  if (c >= 0xAC00 && c <= 0xD7A3) fin = (c - 0xAC00) % 28; else if (/[0-9]/.test(ch)) fin = '013678'.includes(ch) ? ('7' === ch ? 8 : 1) : 0;
  else fin = /[LMNR]/i.test(ch) ? 1 : 0;
  const [a, b] = {'은는':['은','는'],'이가':['이','가'],'을를':['을','를'],'과와':['과','와'],'으로로':['으로','로']}[pair];
  if (pair === '으로로') return w + ((fin === 0 || fin === 8) ? b : a);
  return w + (fin ? a : b);
}
/* ---------------- 연결 도우미 (자료형이 맞는 노드를 찾아 주고, 누르면 배치·연결) ---------------- */
const IMPL_RANK = {real:0, partial:1, not_connected:2};
const typeLabel = t => (S.reg.port_types && S.reg.port_types[t]) || t;
const nodeLabel = id => { const sp = spec(id); return sp ? `${sp.id} ${sp.display_name}` : id; };
const implWord = sp => sp.implementation === 'real' ? '' : sp.implementation === 'partial' ? ' (일부 동작)' : ' (아직 준비 중)';
// 이 자료형을 「만드는」 노드 종류 — 실제로 동작하는 것부터
function producersOf(type){
  return S.reg.nodes.filter(n => n.outputs.some(o => o.type === type))
    .sort((a, b) => IMPL_RANK[a.implementation] - IMPL_RANK[b.implementation] || (a.tier === 'tool' ? -1 : 1) - (b.tier === 'tool' ? -1 : 1));
}
// 이 자료형을 「받는」 노드 종류
function consumersOf(type){
  return S.reg.nodes.filter(n => n.inputs.some(i => i.type === type && i.type !== 'Any'))
    .sort((a, b) => IMPL_RANK[a.implementation] - IMPL_RANK[b.implementation]);
}
function missingInputs(n){
  const sp = spec(n.type); if (!sp) return [];
  const linked = i => S.doc.edges.some(e => e.to_node === n.id && e.to_port === i.name);
  const anyIn = sp.inputs.some(linked);
  return sp.inputs.filter(i => (i.required || (i.auto && !anyIn)) && !linked(i));
}
function placeNear(ref, dx, dy){
  let x = ref.x + dx, y = ref.y + dy;
  while (S.doc.nodes.some(o => Math.abs(o.x - x) < 200 && Math.abs(o.y - y) < 110)) y += 130;
  return {x, y};
}
function makeNode(type, x, y){
  const n = {id:newId(type), type, x:Math.round(x), y:Math.round(y), config:defaults(type)};
  S.doc.nodes.push(n); return n;
}
function linkEdge(from, fromPort, to, toPort){
  if (!S.doc.edges.some(e => e.from_node === from && e.from_port === fromPort && e.to_node === to && e.to_port === toPort))
    S.doc.edges.push({from_node:from, from_port:fromPort, to_node:to, to_port:toPort});
}
// 대상 노드의 비어 있는 필수 입력을 채운다: 캔버스에 같은 자료를 내는 노드가 있으면 그걸 잇고, 없으면 새로 놓는다. 앞 노드의 빈 입력도 차례로 채운다.
function fillInputs(n, depth=0, added=[]){
  if (depth > 5) return added;
  for (const inp of missingInputs(n)){
    const have = S.doc.nodes.find(o => o.id !== n.id && spec(o.type) && spec(o.type).outputs.some(op => op.type === inp.type));
    if (have){ const op = spec(have.type).outputs.find(op => op.type === inp.type); linkEdge(have.id, op.name, n.id, inp.name); continue; }
    const pick = producersOf(inp.type)[0]; if (!pick) continue;
    const pos = placeNear(n, -300, 0);
    const m = makeNode(pick.id, pos.x, pos.y); added.push(m.id);
    linkEdge(m.id, pick.outputs.find(op => op.type === inp.type).name, n.id, inp.name);
    fillInputs(m, depth + 1, added);
  }
  return added;
}
function addSourceFor(toNodeId, toPort, type, specId){
  const to = nodeById(toNodeId), sp = spec(specId);
  const pos = placeNear(to, -300, 0); const m = makeNode(specId, pos.x, pos.y);
  linkEdge(m.id, sp.outputs.find(o => o.type === type).name, toNodeId, toPort);
  const more = fillInputs(m);
  S.armed = null; S.sel = m.id; touch(); renderAll(); fit(); hideHelp();
  toast(`${J(nodeLabel(specId),'을를')} 놓고 연결했어요.` + (more.length ? ` 필요한 앞 노드 ${more.length}개(${more.map(id => nodeById(id).type).join('·')})도 함께 놓았어요.` : ''));
}
function addConsumerFor(fromNodeId, fromPort, type, specId){
  const from = nodeById(fromNodeId), sp = spec(specId);
  const pos = placeNear(from, 300, 0); const m = makeNode(specId, pos.x, pos.y);
  linkEdge(fromNodeId, fromPort, m.id, sp.inputs.find(i => i.type === type).name);
  const more = fillInputs(m);
  S.armed = null; S.sel = m.id; touch(); renderAll(); fit(); hideHelp();
  toast(`${nodeLabel(specId)}에 연결했어요.` + (more.length ? ` 이 노드에 필요한 앞 노드 ${more.length}개도 함께 놓았어요.` : ''));
}
function hideHelp(){ const h = $('#helper'); if (h) h.classList.remove('on'); }
function showConnectHelp({from, to}){
  const src = nodeById(from.node), dst = nodeById(to.node), dsp = spec(dst.type), ssp = spec(src.type);
  const inp = dsp.inputs.find(i => i.name === to.port);
  const onCanvas = S.doc.nodes.filter(o => o.id !== dst.id && spec(o.type).outputs.some(op => op.type === to.type));
  const makers = producersOf(to.type).filter(n => n.id !== dst.type);
  const takers = consumersOf(from.type).filter(n => n.id !== src.type).slice(0, 4);
  let h = `<button class="x" title="닫기">×</button>
    <div class="ttl">이 두 노드는 바로 이을 수 없어요</div>
    <p><b>${esc(J(nodeLabel(src.type),'은는'))}</b> ${esc(J('「'+typeLabel(from.type)+'」','을를'))} 내보내는데,
       <b>${esc(J(nodeLabel(dst.type),'은는'))}</b> 「${esc(typeLabel(to.type))}」만 받아요. 서로 다른 자료라서 앱이 연결을 막았어요.</p>`;
  if (dsp.implementation === 'not_connected')
    h += `<p class="soft">참고로 ${esc(J(dst.type,'은는'))} 아직 준비 중인 노드라, 무엇을 연결해도 지금은 결과가 나오지 않아요. ${esc(dsp.not_connected_reason || '')}</p>`;
  h += `<div class="opt"><div class="q">① ${esc(dst.type)}에 맞는 자료를 넣고 싶다면</div>`;
  if (onCanvas.length) h += onCanvas.map(o => { const op = spec(o.type).outputs.find(x => x.type === to.type);
      return `<button data-link="${o.id}|${op.name}">캔버스에 있는 ${esc(J(nodeLabel(o.type),'과와'))} 잇기</button>`; }).join('');
  h += makers.length ? makers.map(n => `<button class="${n.implementation==='real'?'primary':''}" data-src="${n.id}">${esc(nodeLabel(n.id))} 놓고 잇기${implWord(n)}</button>`).join('')
                     : `<p class="mute">이 자료를 만드는 노드가 아직 없어요.</p>`;
  h += `</div>`;
  if (takers.length){
    h += `<div class="opt"><div class="q">② ${esc(src.type)}의 결과를 쓰고 싶다면 — 이 노드들이 받을 수 있어요</div>`;
    h += takers.map(n => `<button data-dst="${n.id}">${esc(J(nodeLabel(n.id),'으로로'))} 보내기${implWord(n)}</button>`).join('') + `</div>`;
  }
  h += `<p class="hint">「놓고 잇기」를 누르면 그 노드에 필요한 앞 노드까지 자동으로 놓아 드려요. 마음에 안 들면 노드를 선택해 Delete로 지우면 돼요.</p>`;
  let el = $('#helper'); if (!el){ el = document.createElement('div'); el.id = 'helper'; document.body.appendChild(el); }
  el.innerHTML = h; el.classList.add('on');
  el.querySelector('.x').onclick = () => { S.armed = null; markArmed(); hideHelp(); };
  el.querySelectorAll('[data-src]').forEach(b => b.onclick = () => addSourceFor(dst.id, to.port, to.type, b.dataset.src));
  el.querySelectorAll('[data-dst]').forEach(b => b.onclick = () => addConsumerFor(src.id, from.port, from.type, b.dataset.dst));
  el.querySelectorAll('[data-link]').forEach(b => b.onclick = () => { const [nid, op] = b.dataset.link.split('|'); linkEdge(nid, op, dst.id, to.port); S.armed = null; touch(); renderAll(); hideHelp(); toast('연결했어요.'); });
}
function deleteSelected(){
  if (S.selEdge !== null){ S.doc.edges.splice(S.selEdge, 1); S.selEdge = null; touch(); renderAll(); return; }
  if (S.sel){ const id = S.sel; S.doc.nodes = S.doc.nodes.filter(n => n.id !== id); S.doc.edges = S.doc.edges.filter(e => e.from_node !== id && e.to_node !== id); S.sel = null; touch(); renderAll(); }
}
function setupCanvas(){
  const cv = $('#canvas'); let drag = null;
  cv.addEventListener('mousedown', ev => {
    const port = ev.target.closest('.port'); if (port){ clickPort(port); ev.stopPropagation(); return; }
    const hd = ev.target.closest('.node .hd'); const node = ev.target.closest('.node');
    if (node){ S.sel = node.dataset.id; S.selEdge = null; renderNodes(); renderEdges(); renderPanel();
      if (hd){ const n = nodeById(node.dataset.id); drag = {kind:'node', n, sx:ev.clientX, sy:ev.clientY, ox:n.x, oy:n.y, moved:false}; } return; }
    const edge = ev.target.closest('path[data-edge]');
    if (edge){ S.selEdge = +edge.dataset.edge; S.sel = null; renderEdges(); renderNodes(); renderPanel(); return; }
    S.sel = null; S.selEdge = null; S.armed = null; renderNodes(); renderEdges(); renderPanel();
    drag = {kind:'pan', sx:ev.clientX, sy:ev.clientY, ox:S.pan.x, oy:S.pan.y};
  });
  $('#edges').addEventListener('mousedown', ev => { const e = ev.target.closest('path[data-edge]'); if (e){ S.selEdge = +e.dataset.edge; S.sel = null; renderEdges(); renderNodes(); renderPanel(); ev.stopPropagation(); } });
  window.addEventListener('mousemove', ev => {
    if (!drag) return;
    if (drag.kind === 'node'){ drag.n.x = Math.round(drag.ox + (ev.clientX - drag.sx)/S.scale); drag.n.y = Math.round(drag.oy + (ev.clientY - drag.sy)/S.scale); drag.moved = true;
      const el = document.querySelector(`.node[data-id="${CSS.escape(drag.n.id)}"]`); el.style.left = drag.n.x+'px'; el.style.top = drag.n.y+'px'; renderEdges(); }
    else { S.pan.x = drag.ox + ev.clientX - drag.sx; S.pan.y = drag.oy + ev.clientY - drag.sy; applyView(); }
  });
  window.addEventListener('mouseup', () => { if (drag && drag.kind === 'node' && drag.moved){ S.dirty = true; renderHeader(); } drag = null; });
  cv.addEventListener('wheel', ev => { ev.preventDefault(); const r = cv.getBoundingClientRect(); zoom(ev.deltaY < 0 ? 1.1 : 1/1.1, ev.clientX - r.left, ev.clientY - r.top); }, {passive:false});
  cv.addEventListener('dragover', ev => ev.preventDefault());
  cv.addEventListener('drop', ev => { const t = ev.dataTransfer.getData('text/node-type'); if (!t) return; ev.preventDefault();
    const r = cv.getBoundingClientRect(); addNode(t, (ev.clientX - r.left - S.pan.x)/S.scale - 20, (ev.clientY - r.top - S.pan.y)/S.scale - 15); });
  window.addEventListener('keydown', ev => {
    if (['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)) return;
    if (ev.key === 'Escape'){ S.armed = null; markArmed(); hideHelp(); }
    if (ev.key === 'Delete' || ev.key === 'Backspace'){ deleteSelected(); ev.preventDefault(); }
    if ((ev.ctrlKey || ev.metaKey) && ev.key === 's'){ ev.preventDefault(); save(); }
  });
}

/* ---------------- panel ---------------- */
const fmt = v => { if (v === null || v === undefined || v === '') return '<span class="mute">—</span>'; const s = String(v);
  if (/^-?\d+(\.\d+)?$/.test(s)){ const [i, f] = s.split('.'); const fi = Number(i).toLocaleString('ko-KR'); return esc(f && /[1-9]/.test(f) ? fi + '.' + f.replace(/0+$/,'').slice(0,4) : fi); }
  return esc(s); };
const kindTag = k => `<span class="kind k-${k}" title="${esc(S.reg.kinds[k] || k)}">${esc(S.reg.kinds[k] || k)}</span>`;
const chip = s => `<span class="chip s-${s}">${STATUS[s] || s}</span>`;

function renderPanel(){
  const p = $('#panel');
  if (S.selEdge !== null){ const e = S.doc.edges[S.selEdge];
    if (!e){ S.selEdge = null; return renderPanel(); }
    return renderEdgePanel(e);
  }
  if (!S.sel) return renderOverview();
  const n = nodeById(S.sel); if (!n){ S.sel = null; return renderOverview(); }
  const sp = spec(n.type); const st = nodeStatus(n.id);
  const tabs = [['config','설정'],['result','결과'],['evidence','근거'],['status','상태·오류']];
  p.innerHTML = `<h2>${n.type} ${esc(sp.display_name)}</h2>
    <div><span class="badge b-${sp.implementation}">${IMPL[sp.implementation]}</span> <span class="mute">${TIER[sp.tier]} · ${esc(persLabel(sp.perspective))} · v${sp.version} · 노드 ID ${esc(n.id)}</span></div>
    <p class="desc">${esc(sp.description)}</p>
    ${sp.not_connected_reason ? `<div class="reason">미연결 사유: ${esc(sp.not_connected_reason)}</div>` : ''}
    ${canObject(n) ? `<div class="objrow"><button id="pObj" title="이 노드의 입력에 동의하지 않으면 사유와 함께 바꿔 다시 계산합니다 (원래 결과는 그대로 보존)">이의 제기 → 재심의</button> <span class="mute">${n.type === 'N01' ? '사실이 이상하면 원문 재대조를 요청' : '가정·전망 선택에 동의하지 않을 때'}</span></div>` : ''}
    <div class="tabs">${tabs.map(([k,l]) => `<button data-tab="${k}" class="${S.tab===k?'on':''}">${l}</button>`).join('')}</div>
    <div id="tabBody"></div><hr><button id="pDel">노드 삭제</button>`;
  p.querySelectorAll('.tabs button').forEach(b => b.onclick = () => { S.tab = b.dataset.tab; renderPanel(); });
  if ($('#pObj')) $('#pObj').onclick = () => openObjection(n.id);
  $('#pDel').onclick = deleteSelected;
  const body = $('#tabBody');
  if (S.tab === 'config') renderConfig(body, n, sp);
  else if (S.tab === 'status') renderStatusTab(body, n, sp, st);
  else renderPacketTab(body, n, sp, st, S.tab);
}
const STATE_TEXT = {
  design: ['실행 전', '아직 실행하지 않았습니다. 실행하면 앞 노드의 결과가 이 선을 따라 넘어갑니다.'],
  nc: ['자료 없음', '보내는 노드가 「미연결」이라 실행해도 넘어갈 자료가 없습니다. 받는 노드는 보류되거나 미연결로 기록됩니다.'],
  flowed: ['전달됨', '앞 노드가 만든 결과가 이 선을 따라 실제로 넘어갔습니다.'],
  'flowed-partial': ['일부 확인 자료 전달', '앞 노드가 「일부 확인」 상태로 끝나, 확인된 부분만 넘어갔습니다. 미확보 항목은 결과 탭에서 보세요.'],
  blocked: ['전달 안 됨', '앞 노드가 결과를 만들지 못해(보류·미연결·실패·취소) 아무것도 넘어가지 않았습니다.'],
};
function packetSummary(pkt){
  const p = pkt.payload, t = pkt.header.type;
  if (t === 'OfficialCorpus') return [`원문 문서 ${p.documents.length}건`, ...p.documents.map(d => `· ${d.title} (접수 ${d.rcpNo})`)];
  if (t === 'FactPackage'){ const cos = [...new Set(p.facts.map(f => f.company_name))], yrs = [...new Set(p.facts.map(f => f.period))].sort();
    return [`확인된 사실 ${p.facts.length}건 (${cos.join('·')} / ${yrs.join('·')})`, `계산 파생값 ${p.derived.length}건`, `미확보 ${p.missing.length}건`]; }
  if (t === 'MacroExposure') return [`거시 지표 ${p.indicators.length}개`, `기업 공시 노출 ${p.exposures.length}건`];
  if (t === 'AssumptionSet') return [`가정 항목 ${p.items.length}개 (${p.method.toUpperCase()})`, p.input_kind === 'illustrative_assumptions' ? '학습용 예시 가정 (실제 추정 아님)' : '사용자 직접 입력 가정'];
  if (t === 'ValuationResult') return [`주당가치 ${fmt(Math.round(Number(p.per_share)))}원 (가정 기반 계산값)`, `입력 ${p.inputs.length}개 · 민감도 ${p.sensitivity.length}칸`];
  if (t === 'IndustryPeers') return [`${p.name} 비교군 「${p.group.method}」 ${p.members.length}곳`, `재무: ${p.financial_cutoff} 이전 분기 말까지`];
  if (t === 'NewsEvents') return [`${p.name} ${p.window[0]}~${p.window[1]}`, `공시 ${p.disclosures.length}건 · 뉴스 제목 ${p.news.length}건 (중복 ${p.news_duplicates_removed} 합침)`];
  if (t === 'DocPassages') return [`${p.name} 사업보고서 문단 ${p.hits.length}개`, `검색어: ${p.query}`];
  if (t === 'OwnershipData') return [`${p.name} 최대주주 현황 ${p.holders.length}행`, `5% 보고 ${p.reports.length}건 · 임원 보고 ${p.insider_dates.length}건`];
  if (t === 'CompanyFilings'){ const ys = [...new Set(p.facts.map(f => f.year))].sort(); return [`${p.name} 사업보고서 재무 ${p.facts.length}건${ys.length ? ` (${ys[0]}~${ys[ys.length-1]})` : ''}`, `공시 민감도 ${p.exposures.length}건`, `사본 ${p.source.financials.snapshot}`]; }
  if (t === 'MacroSeries') return [`거시 지표 ${Object.keys(p.series).length}종`, `사본 ${p.source.obs.snapshot}`];
  if (t === 'FlowSeries') return [`${p.name} 투자자별 순매수 ${p.rows.length}거래일 (포털 수집값)`, `대차잔고 ${(p.lending||[]).length}일`, `사본 ${p.source.flows.snapshot}`];
  if (t === 'PriceSeries') return [`${p.name} 일별 가격 ${p.rows.length}거래일`, p.rows.length ? `${p.rows[0].trade_date} ~ ${p.rows[p.rows.length-1].trade_date}` : '', `사본 ${p.source.snapshot} · ${p.source.source_grade}`];
  if (t === 'NodeFinding') return [`분석 항목 ${(p.findings||[]).length}건`, `보류 ${(p.held||[]).length}건`];
  if (t === 'Report') return [`취합한 노드 ${p.entries.length}개`];
  return [t];
}
async function renderEdgePanel(e){
  const p = $('#panel'); const from = nodeById(e.from_node), to = nodeById(e.to_node);
  const op = spec(from.type).outputs.find(x => x.name === e.from_port), ip = spec(to.type).inputs.find(x => x.name === e.to_port);
  const st = edgeState(e); const [stLabel, stText] = STATE_TEXT[st];
  p.innerHTML = `<h2>연결선: ${esc(SHORT[op.type] || op.type)}</h2>
    <p class="desc"><b>${esc(from.type)} ${esc(spec(from.type).display_name)}</b>의 「${esc(op.label)}」을<br><b>${esc(to.type)} ${esc(spec(to.type).display_name)}</b>의 「${esc(ip.label)}」 입력으로 넘깁니다.</p>
    <p><span class="estate es-${st}">${esc(stLabel)}</span> ${esc(stText)}</p>
    <div id="edgeLoad"></div>
    <p class="reason">연결선은 자료를 넘긴다는 뜻일 뿐, 그 자료가 맞다는 승인이나 인과관계를 뜻하지 않습니다. 믿을 수 있는지는 각 노드의 상태와 근거 탭으로 판단하세요.</p>
    <p class="mute">자료형 코드: ${esc(op.type)}</p>
    <div style="display:flex;gap:6px"><button id="goFrom">보내는 노드 보기</button><button id="goTo">받는 노드 보기</button><button id="pDelEdge">이 연결 삭제</button></div>`;
  $('#pDelEdge').onclick = deleteSelected;
  $('#goFrom').onclick = () => { S.selEdge = null; S.sel = from.id; S.tab = 'result'; renderAll(); };
  $('#goTo').onclick = () => { S.selEdge = null; S.sel = to.id; S.tab = 'status'; renderAll(); };
  const sf = nodeStatus(from.id), stTo = nodeStatus(to.id);
  if (!st.startsWith('flowed') || !sf) return;
  $('#edgeLoad').innerHTML = '<p class="mute">넘어간 자료를 불러오는 중…</p>';
  const pkt = await api('/api/packets/' + sf.output_packet);
  if (S.selEdge === null || S.doc.edges[S.selEdge] !== e) return;
  const used = stTo && stTo.input_digests.find(d => d.packet_id === pkt.header.packet_id);
  $('#edgeLoad').innerHTML = `<h3>넘어간 자료</h3><ul>${packetSummary(pkt).map(x => `<li>${esc(x)}</li>`).join('')}</ul>
    <table><tr><th>결과 해시</th><td class="mono">${esc(pkt.header.payload_digest.slice(0,16))}…</td></tr>
    <tr><th>받는 쪽 기록</th><td>${used ? `받는 노드가 같은 해시로 입력을 기록했습니다 (${esc(STATUS[stTo.status])})` : (stTo ? `받는 노드 기록에 이 자료가 없습니다 (${esc(STATUS[stTo.status])})` : '받는 노드 실행 기록 없음')}</td></tr></table>`;
}
function persLabel(id){ return id === 'common' ? '공통' : (S.reg.perspectives.find(p => p[0] === id) || [id,id])[1]; }

function needsCard(n, sp){
  const miss = missingInputs(n);
  let h = '';
  if (sp.implementation === 'not_connected') h += `<div class="needs soft">이 노드는 아직 준비 중이에요. 연결은 할 수 있지만 실행하면 「미연결」로 기록되고 결과는 나오지 않아요.</div>`;
  if (!miss.length) return h;
  h += `<div class="needs"><b>이 노드가 일하려면 자료가 더 필요해요</b><ul>${miss.map(i => { const mk = producersOf(i.type)[0];
        return `<li>「${esc(i.label)}」 — ${mk ? `${esc(J(nodeLabel(mk.id),'이가'))} 만들어요${implWord(mk)}` : '만드는 노드가 아직 없어요'}</li>`; }).join('')}</ul>
      <button class="primary" id="bFill">필요한 앞 노드 채우기</button> <span class="mute">캔버스에 이미 있는 노드는 그대로 잇고, 없는 노드만 새로 놓아요.</span></div>`;
  return h;
}
function renderConfig(body, n, sp){
  const schema = sp.config_schema; const keys = Object.keys(schema);
  let h = needsCard(n, sp);
  if (!keys.length) h += '<p class="mute">설정 항목이 없습니다.</p>';
  for (const k of keys){
    const f = schema[k], v = n.config[k] ?? f.default;
    h += `<div class="field"><label>${esc(f.label || k)}</label>`;
    if (f.type === 'enum') h += `<select data-k="${k}">${f.options.map(o => `<option value="${esc(o)}" ${String(o)===String(v)?'selected':''}>${esc(optLabel(k,o))}</option>`).join('')}</select>`;
    else if (f.type === 'multi') h += `<div class="checks" data-k="${k}">${f.options.map(o => `<label><input type="checkbox" value="${esc(o)}" ${(v||[]).map(String).includes(String(o))?'checked':''}> ${esc(optLabel(k,o))}</label>`).join('')}</div>`;
    else if (f.type === 'company') h += `<input type="text" data-co="${k}" list="coList" value="${esc(coLabel(v))}" placeholder="회사 이름이나 6자리 종목코드" autocomplete="off"><datalist id="coList"></datalist><div class="hint" id="coHint">회사 이름 몇 글자만 적어도 목록이 나와요. 자료가 있는 회사는 「근거 지도」에서 볼 수 있어요.</div>`;
    else if (f.type === 'broker_report') h += `<select data-k="${k}" data-broker="1"><option value="">불러오는 중…</option></select><div class="hint">「증권사 전망」 화면에서 스캔·승인한 보고서 중 하나를 고릅니다.</div>`;
    else if (f.type === 'json') h += `<div style="display:flex;gap:6px;margin-bottom:4px"><button id="tplBlank">방법별 빈 양식</button><button id="tplIll">학습용 예시 (실제 추정 아님)</button><button id="tplFc" title="증권사 전망을 2026·2027 성장률·이익률에 적용할 때">전망 적용용 2개년</button></div>
        <textarea data-k="${k}" spellcheck="false">${esc(JSON.stringify(v, null, 2))}</textarea><div id="jsonErr" class="mute"></div>`;
    else h += `<input type="text" data-k="${k}" value="${esc(v)}">`;
    h += '</div>';
  }
  if (n.type === 'T03') h += `<p class="hint">숫자는 문자열로 적습니다(예: "9.5"). 금액은 백만원, 비율은 %입니다. 빈 가정을 자동으로 채우지 않습니다.</p>`;
  if (sp.data_sources.length) h += `<h3>자료 출처</h3><table><tr><th>출처</th><th>범위</th><th>기준</th><th>수집</th><th>권리</th></tr>${sp.data_sources.map(s => `<tr><td>${esc(s.provider)}</td><td>${esc(s.scope)}</td><td>${esc(s.as_of)}</td><td>${esc(s.collected_at)}</td><td>${esc(s.rights_status)}</td></tr>`).join('')}</table>`;
  if (sp.reuse_origin) h += `<p class="hint">재사용 출처: ${esc(sp.reuse_origin)}</p>`;
  h += `<h3>포트</h3><table><tr><th>방향</th><th>이름</th><th>자료형</th><th>필수</th></tr>${sp.inputs.map(p => `<tr><td>입력</td><td>${esc(p.label)}</td><td>${p.type}</td><td>${p.required?'필수':'선택'}${p.multiple?' · 여러 개':''}</td></tr>`).join('')}${sp.outputs.map(p => `<tr><td>출력</td><td>${esc(p.label)}</td><td>${p.type}</td><td></td></tr>`).join('')}</table>`;
  body.innerHTML = h;
  const bf = body.querySelector('#bFill'); if (bf) bf.onclick = () => { const added = fillInputs(n); touch(); renderAll(); if (added.length) fit(); toast(added.length ? `앞 노드 ${added.length}개(${added.map(id => nodeById(id).type).join('·')})를 놓고 연결했어요.` : '캔버스에 있던 노드로 연결했어요.'); };
  body.querySelectorAll('input[data-co]').forEach(async el => { const u = await loadUniverse(); const dl = body.querySelector('#coList'), hint = body.querySelector('#coHint');
      if (!u){ hint.textContent = 'Neon 사본이 없어 회사 목록을 못 불러왔어요. 종목코드 6자리를 직접 적어 주세요.'; }
      else dl.innerHTML = u.companies.filter(c => c.market === 'KR').map(c => `<option value="${esc(c.ticker + ' ' + c.name)}"></option>`).join('');
      el.onchange = el.oninput = () => { const t = resolveCo(el.value);
        if (t){ n.config[el.dataset.co] = t; const c = coInfo(t); hint.innerHTML = c ? `<b>${esc(c.name)}</b> (${esc(t)}) — 시세 ${c.cover.price_fsc ? c.cover.price_fsc.n + '일' : '없음'} · 수급 ${c.cover.flow ? c.cover.flow.n + '일' : '없음'}` : esc(t); touch(); renderHeader(); }
        else { const cs = coCands(el.value); hint.textContent = !el.value.trim() ? '' : cs.length > 1 ? `${cs.length}곳이 맞아요: ${cs.slice(0, 6).join(', ')}${cs.length > 6 ? ' …' : ''} — 하나를 골라 주세요.` : '사본에 없는 회사예요. 「근거 지도」에서 자료가 있는 회사를 확인해 주세요.'; } }; });
  body.querySelectorAll('select[data-broker]').forEach(async el => { try { const r = await api('/api/broker/reports'); const cur = n.config[el.dataset.k] || '';
      const cnt = f => r.candidates.filter(c => c.file === f && c.state === 'approved').length;
      el.innerHTML = '<option value="">— 선택 —</option>' + r.reports.map(x => `<option value="${esc(x.file)}" ${x.file===cur?'selected':''}>${esc(x.report_date)} ${esc(x.broker)} · 승인 ${cnt(x.file)}건${x.status!=='ok'?' · '+esc(x.status):''}</option>`).join('');
      if (!r.reports.length) el.innerHTML = '<option value="">스캔된 보고서 없음 — 「증권사 전망」에서 스캔</option>'; } catch(e) { el.innerHTML = '<option>목록 실패</option>'; } });
  body.querySelectorAll('select[data-k]').forEach(el => el.onchange = () => { const f = schema[el.dataset.k]; const raw = el.value;
    n.config[el.dataset.k] = typeof f.options?.[0] === 'number' ? Number(raw) : raw; touch(); renderHeader(); if (n.type === 'T03' && el.dataset.k === 'method') toast('방법을 바꿨다면 「방법별 빈 양식」으로 가정 양식을 새로 받으세요.'); });
  body.querySelectorAll('.checks[data-k]').forEach(el => el.onchange = () => { const f = schema[el.dataset.k];
    n.config[el.dataset.k] = [...el.querySelectorAll('input:checked')].map(i => typeof f.options?.[0] === 'number' ? Number(i.value) : i.value); touch(); renderHeader(); });
  body.querySelectorAll('input[type=text][data-k]').forEach(el => el.oninput = () => { n.config[el.dataset.k] = el.value; touch(); renderHeader(); });
  const ta = body.querySelector('textarea[data-k]');
  if (ta){ ta.oninput = () => { try { n.config[ta.dataset.k] = JSON.parse(ta.value || '{}'); $('#jsonErr').textContent = ''; touch(); renderHeader(); } catch(e) { $('#jsonErr').textContent = 'JSON 형식 오류: ' + e.message; } };
    $('#tplBlank').onclick = () => { n.config.model = TEMPLATES[n.config.method || 'dcf'].blank; n.config.input_kind = 'user_assumptions'; touch(); renderPanel(); };
    $('#tplIll').onclick = () => { const t = TEMPLATES[n.config.method || 'dcf'];
      Object.assign(n.config, {model: t.ill, input_kind:'illustrative_assumptions', label: '학습용 ' + (n.config.method||'dcf').toUpperCase(),
        shares: '5900000000', share_basis: '학습용 예시 주식 수 (실제 희석주식수 아님)', assumptions_note: '계산 흐름 체험용 임의 가정. 실제 기업가치 추정이 아님'});
      touch(); renderPanel(); toast('학습용 예시를 채웠습니다. 결과는 실제 추정이 아니라고 표시됩니다.'); };
    $('#tplFc').onclick = () => { n.config.method = 'dcf';
      Object.assign(n.config, {model: TEMPLATES.dcf2, input_kind:'illustrative_assumptions', label:'증권사 전망 적용 (나머지 학습용)', shares:'5846279000',
        share_basis:'증권사 보고서에 기재된 발행주식수(보통주) — 희석주식수 확인 필요', assumptions_note:'성장률·이익률은 N02에서 승인된 증권사 전망으로 대체. 나머지는 학습용 임의 가정'});
      touch(); renderPanel(); toast('2개년 DCF 양식을 채웠습니다. 성장률·이익률은 T04 승인 전망으로 대체됩니다.'); };
  }
}
/* ---------------- C: 시장 근거 지도 · 기업 목록 ---------------- */
async function loadUniverse(force){
  if (S.uni && !force) return S.uni;
  try { S.uni = await api('/api/universe'); } catch(e){ S.uni = null; }
  return S.uni;
}
function coInfo(t){ return S.uni ? S.uni.companies.find(c => c.ticker === t) : null; }
function coLabel(t){ const c = coInfo(t); return c ? `${t} ${c.name}` : ({'005930':'005930 삼성전자','000660':'000660 SK하이닉스'}[t] || t || ''); }
function resolveCo(v){ v = (v || '').trim(); if (!v) return null; const m = v.match(/^(\d{6})/); if (m) return (!S.uni || coInfo(m[1])) ? m[1] : null;
  if (!S.uni) return null; const kr = S.uni.companies.filter(c => c.market === 'KR');
  const c = kr.find(c => c.name === v) || (kr.filter(c => c.name.includes(v)).length === 1 ? kr.find(c => c.name.includes(v)) : null); return c ? c.ticker : null; }
function coCands(v){ v = (v || '').trim(); return v && S.uni ? S.uni.companies.filter(c => c.market === 'KR' && c.name.includes(v)).map(c => c.name) : []; }
async function openEvidenceMap(){
  $('#dlgBody').innerHTML = '<h2>근거 지도</h2><p><span class="spin"></span> 불러오는 중…</p>'; openWide();
  const u = await loadUniverse(true);
  if (!u){ $('#dlgBody').innerHTML = `<h2>근거 지도</h2><p class="stale-note">Neon 사본이 없어요. PC에서 <b>_tools\\neon_snapshot\\run-neon-snapshot.cmd</b>를 실행한 뒤 다시 열어 주세요.</p>`; return; }
  const cols = u.columns.filter(c => c.key !== 'price_other');
  const st = S.mapState = S.mapState || {q:'', market:'KR', only:'', sort:''};
  const draw = () => {
    let rows = u.companies.filter(c => (!st.market || c.market === st.market) && (!st.q || c.name.includes(st.q) || c.ticker.includes(st.q) || (c.krx_sector || '').includes(st.q)));
    if (st.only) rows = rows.filter(c => !c.cover[st.only].n);
    if (st.sort) rows = [...rows].sort((a, b) => b.cover[st.sort].n - a.cover[st.sort].n);
    const cell = (c, k) => { const v = c.cover[k]; return v.n ? `<td class="cv yes" title="${esc(v.n + '건 · 최근 ' + (v.last || ''))}">${v.n > 999 ? Math.round(v.n / 100) / 10 + '천' : v.n}</td>` : '<td class="cv no">—</td>'; };
    $('#mapRows').innerHTML = rows.map(c => `<tr><td><b>${esc(c.name)}</b> <span class="mono mute">${esc(c.ticker)}</span><div class="mute small">${esc(c.krx_sector || c.sector_desc || '')}</div></td>${cols.map(k => cell(c, k.key)).join('')}
      <td>${c.market === 'KR' && c.cover.price_fsc && c.cover.price_fsc.n ? `<button class="linkbtn" data-ask="${esc(c.name)}">주가·수급 보기</button>` : ''}</td></tr>`).join('') || '<tr><td colspan="99" class="mute">조건에 맞는 회사가 없어요.</td></tr>';
    $('#mapCount').textContent = `${rows.length}곳 표시`;
    $('#mapRows').querySelectorAll('[data-ask]').forEach(b => b.onclick = () => { openExamplePicker(); $('#askQ').value = `${b.dataset.ask} 주가 추세와 투자자별 수급, 엇갈림`; askAssemble(); });
  };
  const n = u.companies.filter(c => c.market === 'KR').length;
  $('#dlgBody').innerHTML = `<h2>근거 지도 <span class="mute">— 사본 ${esc(u.snapshot)} · 회사 ${u.count}곳(국내 ${n})</span></h2>
    <p class="mute">회사마다 어떤 근거 자료가 사본에 들어 있는지 개수로 보여 줘요(숫자 = 행 수, — = 없음). 행 자체는 읽지 않고 개수만 세서 빨라요. <b>지금 모든 회사에 바로 쓰는 자료</b>는 초록 머리글이에요.</p>
    <div class="maptools"><input id="mapQ" placeholder="회사·종목코드·업종 찾기" value="${esc(st.q)}">
      <select id="mapMk"><option value="KR" ${st.market==='KR'?'selected':''}>국내</option><option value="US" ${st.market==='US'?'selected':''}>해외</option><option value="" ${!st.market?'selected':''}>전체</option></select>
      <select id="mapOnly"><option value="">빈칸 필터 없음</option>${cols.map(c => `<option value="${c.key}" ${st.only===c.key?'selected':''}>「${esc(c.label)}」 없는 곳만</option>`).join('')}</select>
      <span id="mapCount" class="mute"></span> <a class="linkbtn" href="/api/universe/gaps.csv" download>빈칸 목록 내려받기(CSV)</a></div>
    <div class="mapwrap"><table class="evmap"><thead><tr><th>회사</th>${cols.map(c => `<th class="${c.ready_now ? 'ready' : ''}" data-sort="${c.key}" title="${esc((c.nodes.length ? '쓰는 노드: ' + c.nodes.join('·') : '아직 쓰는 노드 없음') + ' · 누르면 많은 순 정렬')}">${esc(c.label)}<div class="small">${u.summary[c.key]}곳</div></th>`).join('')}<th></th></tr></thead>
    <tbody id="mapRows"></tbody></table></div>
    ${Object.keys(u.failed || {}).length ? `<p class="stale-note">사본을 만들 때 실패한 항목: ${esc(Object.keys(u.failed).join(', '))}</p>` : ''}`;
  $('#mapQ').oninput = e => { st.q = e.target.value.trim(); draw(); };
  $('#mapMk').onchange = e => { st.market = e.target.value; draw(); };
  $('#mapOnly').onchange = e => { st.only = e.target.value; draw(); };
  document.querySelectorAll('.evmap th[data-sort]').forEach(th => th.onclick = () => { st.sort = st.sort === th.dataset.sort ? '' : th.dataset.sort; draw(); });
  draw();
}
function renderTables(ts){
  if (!ts || !ts.length) return '';
  const cell = v => v && typeof v === 'object' && v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.text || '링크')}</a>` : esc(v ?? '');
  return ts.map(t => `<h3>${esc(t.title)}</h3>${t.rows.length ? `<div class="tblwrap"><table><tr>${t.cols.map(c => `<th>${esc(c)}</th>`).join('')}</tr>${t.rows.map(r => `<tr>${r.map(v => `<td>${cell(v)}</td>`).join('')}</tr>`).join('')}</table></div>` : '<p class="mute">없음</p>'}${t.hint ? `<p class="hint">${esc(t.hint)}</p>` : ''}`).join('');
}
function optLabel(k, o){ const C = {'005930':'삼성전자','000660':'SK하이닉스'}; const M = {revenue:'매출액',operatingProfit:'영업이익',cfo:'영업활동현금흐름',currentAssets:'유동자산',currentLiabilities:'유동부채',assets:'자산총계',liabilities:'부채총계',equity:'자본총계',inventory:'재고자산',ppeAcquisition:'유형자산 취득',intangibleAcquisition:'무형자산 취득'};
  const X = {competition:'경쟁·점유율·업황', holders:'최대주주·주주 현황', risk:'위험 요인', KCS_EXP_854232_USD:'반도체 메모리 수출 (HS 854232)', KCS_EXP_854231_USD:'프로세서·컨트롤러 수출 (HS 854231)', dcf:'DCF (FCFF)',ddm:'DDM',rim:'RIM',nav:'NAV (조정순자산)',user_assumptions:'사용자 가정',illustrative_assumptions:'학습용 예시 (실제 추정 아님)', ECOS_USDKRW:'원/달러 환율', '^KS11':'코스피', '^KQ11':'코스닥', '^SOX':'미국 반도체 지수', '^GSPC':'S&P 500', ECOS_KTB3Y:'국고채 3년', ECOS_KTB10Y:'국고채 10년', DGS10:'미국 10년 국채', ECOS_BASE_RATE:'한국 기준금리', DCOILBRENTEU:'브렌트유', DEXJPUS:'엔/달러', DEXCHUS:'위안/달러', IPG3344S:'미국 반도체 산업생산', PCOPPUSDM:'구리 가격'};
  return C[o] ? `${o} ${C[o]}` : (M[o] || X[o] || o); }

const TEMPLATES = {
  dcf2: {discount_basis:'WACC', rate:'9', terminal_growth:'2', years:[
      {growth:'0',margin:'0',tax:'22',depreciation:'45000000',capex:'60000000',delta_wc:'5000000'},
      {growth:'0',margin:'0',tax:'22',depreciation:'50000000',capex:'65000000',delta_wc:'5000000'}],
    bridge:{debt:'20000000',excess_cash:'90000000',nonoperating_assets:'0',minority:'10000000',preferred:'0',other_claims:'0'},
    terminal_fcff:'250000000', terminal_reason:'학습용 예시: 정상화 FCFF를 임의로 정함 (실제 추정 아님)'},
  dcf: {blank: {discount_basis:'WACC', rate:'', terminal_growth:'', years:[{growth:'',margin:'',tax:'',depreciation:'',capex:'',delta_wc:''}],
         bridge:{debt:'',excess_cash:'',nonoperating_assets:'0',minority:'',preferred:'0',other_claims:'0'}, terminal_fcff:'', terminal_reason:''},
        ill: {discount_basis:'WACC', rate:'9', terminal_growth:'2', years:[{growth:'5',margin:'15',tax:'22',depreciation:'40000000',capex:'50000000',delta_wc:'2000000'}],
         bridge:{debt:'20000000',excess_cash:'90000000',nonoperating_assets:'0',minority:'10000000',preferred:'0',other_claims:'0'}, terminal_fcff:'30000000', terminal_reason:'학습용 예시: 정상화 FCFF를 임의로 정함'}},
  ddm: {blank: {discount_basis:'cost_of_equity', rate:'', terminal_growth:'', dividends:['']},
        ill: {discount_basis:'cost_of_equity', rate:'8', terminal_growth:'2', dividends:['9800000','10000000']}},
  rim: {blank: {discount_basis:'cost_of_equity', rate:'', terminal_growth:'0', common_book:'', years:[{net_income:'',dividends:''}], terminal_mode:'zero', clean_surplus_ack:true},
        ill: {discount_basis:'cost_of_equity', rate:'8', terminal_growth:'0', common_book:'380000000', years:[{net_income:'40000000',dividends:'10000000'}], terminal_mode:'zero', clean_surplus_ack:true}},
  nav: {blank: {asset_adjustment:'0', liability_adjustment:'0', realization_cost:'0', minority:'', preferred:'0', other_claims:'0'},
        ill: {asset_adjustment:'0', liability_adjustment:'0', realization_cost:'0', minority:'10000000', preferred:'0', other_claims:'0'}},
};

function renderStatusTab(body, n, sp, st){
  if (!st){ body.innerHTML = '<p class="mute">이 노드의 실행 기록이 없습니다.</p>'; return; }
  const el = st.started_at ? secs(st.started_at, st.finished_at || S.run.server_time) : null;
  body.innerHTML = `${S.editedSinceRun ? '<div class="stale-note">캔버스를 편집한 뒤라서 아래는 이전 실행의 기록입니다.</div>' : ''}
    <p>${chip(st.status)} ${st.stalled ? chip('held')+' 10초 넘게 응답 없음' : ''} ${st.error_code ? `<span class="mono">${esc(st.error_code)}</span>` : ''}</p>
    ${st.reason ? `<div class="reason">${esc(st.reason)}</div>` : ''}
    <table><tr><th>시작</th><td>${kst(st.started_at)}</td></tr><tr><th>종료</th><td>${kst(st.finished_at)}</td></tr>
    <tr><th>경과</th><td>${el === null ? '—' : el.toFixed(1)+'초'}</td></tr><tr><th>도구 호출</th><td>${st.tool_calls}회 (원문 검증기)</td></tr><tr><th>모델 호출</th><td>${st.model_calls}회</td></tr></table>
    <h3>진행 단계</h3>${st.steps.length ? `<ol class="steps">${st.steps.map(s => `<li>${esc(s.msg)} <span class="mute">${esc(s.at.slice(11,19))}</span></li>`).join('')}</ol>` : '<p class="mute">기록된 단계 없음</p>'}
    <h3>입력 스냅샷</h3>${st.input_digests.length ? `<table><tr><th>포트</th><th>보낸 노드</th><th>상태</th><th>해시</th></tr>${st.input_digests.map(d => `<tr><td>${esc(d.port)}</td><td>${esc(d.from)}</td><td>${chip(d.upstream_status)}</td><td class="mono">${esc(d.payload_digest.slice(0,16))}…</td></tr>`).join('')}</table>` : '<p class="mute">입력 없음</p>'}`;
}
function kst(t){ if (!t) return '—'; return new Date(t).toLocaleString('ko-KR', {timeZone:'Asia/Seoul', hour12:false}); }
function secs(a, b){ return (new Date(b) - new Date(a)) / 1000; }

async function renderPacketTab(body, n, sp, st, tab){
  if (!st || !st.output_packet){ body.innerHTML = st ? `<p>${chip(st.status)}</p><div class="reason">${esc(st.reason || '출력이 없습니다.')}</div>` : '<p class="mute">실행 결과가 없습니다. 상단 「실행」을 누르세요.</p>'; return; }
  body.innerHTML = '<p class="mute">불러오는 중…</p>';
  const pkt = await api('/api/packets/' + st.output_packet);
  const stale = S.editedSinceRun ? '<div class="stale-note">캔버스를 편집한 뒤라서 아래는 이전 실행의 결과입니다.</div>' : '';
  const head = `${stale}<p>${chip(st.status)} <span class="mono">${esc(pkt.header.type)} · ${esc(pkt.header.payload_digest.slice(0,16))}…</span></p>${st.reason ? `<div class="reason">${esc(st.reason)}</div>` : ''}`;
  body.innerHTML = head + (tab === 'result' ? resultView(pkt) : evidenceView(pkt));
  body.querySelectorAll('[data-fact]').forEach(b => b.onclick = () => { S.focusFact = b.dataset.fact; S.tab = 'evidence'; renderPanel(); });
}
function resultView(pkt){
  const p = pkt.payload, t = pkt.header.type;
  if (t === 'OfficialCorpus') return `<h3>대조한 원문</h3><table><tr><th>문서</th><th>접수번호</th><th>공시일</th></tr>${p.documents.map(d => `<tr><td>${esc(d.title)}</td><td><a href="${esc(d.landingUrl)}" target="_blank" rel="noopener">${esc(d.rcpNo)}</a></td><td>${esc(d.publishedDate)}</td></tr>`).join('')}</table>
      <p class="hint">${esc(p.notice)}</p><h3>자료 한계</h3><ul>${p.limits.map(l => `<li>${esc(l)}</li>`).join('')}</ul>`;
  if (t === 'FactPackage') return `<h3>확인된 사실 ${p.facts.length}건</h3><table><tr><th>기업</th><th>연도</th><th>항목</th><th>값</th><th>단위·범위</th><th></th></tr>
      ${p.facts.map(f => `<tr><td>${esc(f.company_name)}</td><td>${f.period}</td><td>${esc(f.metric_label)}</td><td class="num">${esc(f.status === 'api_reported' ? fmt(f.value) : f.source_value)}</td><td>${esc(f.unit)} · ${esc(f.scope)}${f.status === 'api_reported' ? ' · <span class="mute">공시 API</span>' : ''}</td><td><button data-fact="${esc(f.fact_id)}">근거</button></td></tr>`).join('')}</table>
      ${p.missing.length ? `<h3>미확보 ${p.missing.length}건</h3><table>${p.missing.map(m => `<tr><td>${esc(m.company)} ${m.period} ${esc(m.metric)}</td><td>${esc(m.reason)}</td></tr>`).join('')}</table>` : ''}
      <h3>계산 파생값</h3><table><tr><th>기업·연도</th><th>항목</th><th>값</th><th>산식</th></tr>${p.derived.map(d => `<tr><td>${esc(d.company)} ${d.period}</td><td>${esc(d.label)} ${kindTag('derived')}</td><td class="num">${fmt(d.value)} ${esc(d.unit)}</td><td>${esc(d.formula)}</td></tr>`).join('')}</table>`;
  if (t === 'MacroExposure') return `<h3>지표 관측</h3><table><tr><th>지표</th><th>처음</th><th>마지막</th><th>변화</th></tr>${p.indicators.map(i => `<tr><td>${esc(i.title)}<div class="mute">${esc(i.frequency)}</div></td><td>${esc(i.first.date)}<br>${fmt(i.first.value)}</td><td>${esc(i.last.date)}<br>${fmt(i.last.value)}</td><td>${fmt(i.delta)}${esc(i.deltaUnit||'')}</td></tr>`).join('')}</table>
      <h3>기업 공시 노출 ${kindTag('fact_official')}</h3>${p.exposures.map(e => `<p><b>${esc(e.name)}</b><br>환율: ${esc(e.fx_scenario)}<br>금리: ${esc(e.rate_scenario)}</p>`).join('')}
      <div class="warn">지표 변화가 실적에 준 영향은 추정하지 않았습니다.</div>`;
  if (t === 'IndustryPeers'){ const RL = {chip:'반도체 제조·설계', equipment:'반도체 장비', materials:'반도체 소재', parts:'부품·기타', other:'기타'};
    return `<h3>${esc(p.name)} 비교군 「${esc(p.group.method)}」 ${kindTag('fact_official')}</h3>
      <table><tr><th>순번</th><th>기업</th><th>시장</th><th>역할(규칙)</th><th>선정 이유</th></tr>${p.members.map(m => `<tr><td>${m.rank}</td><td>${esc(m.name)} <span class="mono mute">${esc(m.ticker)}</span></td><td>${esc(m.market||'')}</td><td>${esc(RL[m.role]||m.role)}</td><td class="mute">${esc(m.reason||'')}</td></tr>`).join('')}</table>
      ${p.group.excluded_groups.length ? `<p class="mute">쓰지 않은 묶음: ${p.group.excluded_groups.map(g => `${esc(g.method)} — ${esc(g.reason)}`).join(' / ')}</p>` : ''}
      <ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`; }
  if (t === 'NewsEvents') return `<h3>${esc(p.name)} 공시 ${p.disclosures.length}건 ${kindTag('fact_official')}</h3><p class="mute">${esc(p.window[0])} ~ ${esc(p.window[1])}</p>
      <table><tr><th>접수일</th><th>분류(규칙)</th><th>보고서명</th></tr>${p.disclosures.slice(-12).reverse().map(d => `<tr><td>${esc(d.date)}</td><td>${esc(d.category_label)}</td><td><a href="${esc(d.url)}" target="_blank" rel="noopener">${esc(d.title)}</a></td></tr>`).join('')}</table>
      <h3>뉴스 제목 ${p.news.length}건 ${kindTag('fact_portal')}</h3><table>${p.news.slice(-10).reverse().map(n => `<tr><td>${esc(n.date)}</td><td><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a></td></tr>`).join('')}</table>
      <ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (t === 'DocPassages') return `<h3>${esc(p.name)} 사업보고서 문단 ${p.hits.length}개 ${kindTag('fact_official')}</h3><p class="mute">검색어: ${esc(p.query)}</p>
      ${p.hits.map(h => `<div class="passage"><div class="mute">${esc(h.path.join(' › '))} · 접수 ${esc(h.rcept_no)} · 문단 ${esc(h.chunk_id)} · <span class="mono">${esc(h.chunk_sha256.slice(0,12))}…</span></div><div>${esc(h.text.slice(0, 700))}${h.text.length > 700 ? '…' : ''}</div></div>`).join('')}`;
  if (t === 'OwnershipData') return `<h3>${esc(p.name)} 지분 공시 ${kindTag('fact_official')}</h3><p>최대주주 현황 ${p.holders.length}행 · 5% 보고 ${p.reports.length}건 · 임원·주요주주 보고 ${p.insider_dates.length}건</p><ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`;
  if (t === 'CompanyFilings'){ const ys = [...new Set(p.facts.map(f => f.year))].sort().reverse().slice(0, 3), ms = [...new Set(p.facts.map(f => f.metric))];
    const v = (y, m) => { const f = p.facts.find(f => f.year === y && f.metric === m); return f ? fmt(Math.round(Number(f.amount) / 1e6)) : '—'; };
    return `<h3>${esc(p.name)} 사업보고서 재무 ${kindTag('fact_official')} <span class="mute">(백만원, 공시 API)</span></h3>
      <table><tr><th>계정</th>${ys.map(y => `<th>${y}</th>`).join('')}</tr>${ms.map(m => `<tr><td>${esc(p.facts.find(f => f.metric === m).account_nm || m)}</td>${ys.map(y => `<td class="num">${v(y, m)}</td>`).join('')}</tr>`).join('')}</table>
      <h3>공시 민감도 ${p.exposures.length}건 <span class="mute">(사업보고서 표에서 규칙으로 읽음)</span></h3>
      ${p.exposures.length ? `<table><tr><th>연도</th><th>항목</th><th>값</th><th>변동 가정</th><th>근거 문장</th></tr>${p.exposures.map(e => `<tr><td>${e.fiscal_year}</td><td>${esc(e.metric)}</td><td class="num">${fmt(e.value)} ${esc(e.unit_raw || '')}</td><td>${e.change_pct != null ? esc(e.change_pct) + '%' : ''}</td><td class="mute">${esc((e.evidence || '').slice(0, 120))}</td></tr>`).join('')}</table>` : '<p class="mute">없음</p>'}
      <ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`; }
  if (t === 'MacroSeries'){ const ks = Object.keys(p.series);
    return `<h3>거시 지표 ${ks.length}종 ${kindTag('fact_official')}</h3><table><tr><th>지표</th><th>출처</th><th>주기</th><th>마지막 관측</th></tr>${ks.map(k => { const s = p.series[k], o = s.obs[s.obs.length-1];
      return `<tr><td>${esc(s.name)} <span class="mono mute">${esc(k)}</span></td><td>${esc(s.source)}</td><td>${esc(s.frequency)}</td><td>${o ? `${esc(o[0])} · ${fmt(o[1])}` : '-'}</td></tr>`; }).join('')}</table>
      <ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`; }
  if (t === 'FlowSeries'){ const r = p.rows.slice(-10).reverse(), n = v => (v>0?'+':'') + fmt(v);
    return `<h3>${esc(p.name)} 투자자별 순매수 ${kindTag('fact_portal')}</h3><p class="mute">${p.rows.length}거래일 · 기준시점에 확정된 마지막 거래일 ${esc(p.last_usable_date)} · 단위: 주</p>
      <table><tr><th>날짜</th><th>외국인</th><th>기관</th><th>개인</th><th>외국인 보유율</th></tr>${r.map(x => `<tr><td>${esc(x.trade_date)}</td><td class="num">${n(x.foreign_net_qty)}</td><td class="num">${n(x.institution_net_qty)}</td><td class="num">${n(x.individual_net_qty)}</td><td class="num">${esc(x.foreign_hold_pct)}%</td></tr>`).join('')}</table>
      <p class="hint">최근 10거래일만 표시.</p>
      <h3>출처</h3><table>${Object.values(p.source).map(s => `<tr><td>${esc(s.origin)}</td><td>${esc(s.source_grade)}</td><td class="mono">${esc(s.sha256.slice(0,12))}…</td></tr>`).join('')}</table>
      <ul>${p.notes.map(x => `<li>${esc(x)}</li>`).join('')}</ul>`; }
  if (t === 'PriceSeries'){ const r = p.rows.slice(-10).reverse();
    return `<h3>${esc(p.name)} 일별 가격 ${kindTag('fact_official')}</h3><p class="mute">${p.rows.length}거래일 · 기준시점에 확정된 마지막 거래일 ${esc(p.last_usable_date)} · 기준시점 이후 ${p.excluded_after_cutoff}일 제외</p>
      <table><tr><th>날짜</th><th>시가</th><th>고가</th><th>저가</th><th>종가</th><th>거래량</th></tr>${r.map(x => `<tr><td>${esc(x.trade_date)}</td><td class="num">${fmt(x.open)}</td><td class="num">${fmt(x.high)}</td><td class="num">${fmt(x.low)}</td><td class="num">${fmt(x.close)}</td><td class="num">${fmt(x.volume)}</td></tr>`).join('')}</table>
      <p class="hint">최근 10거래일만 표시. ${p.gaps.length ? `6일 넘는 공백 ${p.gaps.length}곳.` : ''}</p>
      <h3>출처</h3><table><tr><td>원천</td><td>${esc(p.source.origin)}</td></tr><tr><td>등급</td><td>${esc(p.source.source_grade)}</td></tr><tr><td>사본</td><td class="mono">${esc(p.source.snapshot)}</td></tr><tr><td>표 해시</td><td class="mono">${esc(p.source.sha256.slice(0,16))}…</td></tr><tr><td>목록 해시</td><td class="mono">${esc(p.source.manifest_sha256.slice(0,16))}…</td></tr></table>
      <ul>${p.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul>`; }
  if (t === 'NodeFinding' && (p.price_source || p.flow_source || p.peer_source || p.macro_source || p.event_source || p.owner_source || p.doc_source || p.tables)) return `${p.notice ? `<div class="warn">${esc(p.notice)}</div>` : ''}<table><tr><th>항목</th><th>값</th><th>종류</th><th>산식</th></tr>${(p.findings||[]).map(f => `<tr><td>${esc(f.name||'')}</td><td>${esc(f.claim || [f.fx_scenario, f.rate_scenario].filter(Boolean).join(' / ') || '')}</td><td>${kindTag(f.kind)}</td><td class="mute">${esc(f.formula||'')}</td></tr>`).join('')}</table>${(p.held||[]).length ? `<h3>보류</h3><ul>${p.held.map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}${p.peer_table ? `<h3>비교 표 (최근 4분기 기준, %)</h3><table><tr><th>기업</th><th>역할</th><th>마지막 분기</th><th>매출 성장</th><th>영업이익률</th><th>순이익률</th><th>ROE</th><th>부채비율</th></tr>${p.peer_table.map(r => `<tr${r.ticker===p.company?' class="base"':''}><td>${esc(r.name)}</td><td>${esc(r.role)}</td><td>${esc(r.end)}</td>${['growth','op_margin','net_margin','roe','debt_ratio'].map(k => `<td class="num">${r[k]==null?'-':r[k].toFixed(1)}</td>`).join('')}</tr>`).join('')}</table><p class="hint">DART(국내)·SEC(해외) 분기 재무로 직접 계산. 해외 기업은 통화가 달라 비율만 비교합니다.</p>` : ''}<p class="hint">${p.price_source ? `가격 출처: 사본 ${esc(p.price_source.snapshot)} · ${esc(p.price_source.source_grade)}` : ''}${p.flow_source ? ` 수급 출처: 사본 ${esc(p.flow_source.flows.snapshot)} · ${esc(p.flow_source.flows.source_grade)} (포털 수집값)` : ''}</p>${renderTables(p.tables)}`;
  if (t === 'NodeFinding') return `<table>${(p.findings||[]).map(f => `<tr><td>${esc(f.name||'')}</td><td>${esc(f.fx_scenario||f.claim||'')}<br>${esc(f.rate_scenario||'')}</td><td>${kindTag(f.kind)}</td></tr>`).join('')}</table>${(p.held||[]).length ? `<h3>보류</h3><ul>${p.held.map(h => `<li>${esc(h)}</li>`).join('')}</ul>` : ''}`;
  if (t === 'AssumptionSet') return `${p.input_kind==='illustrative_assumptions'?'<div class="ill">학습용 예시 가정 — 실제 기업가치 추정이 아닙니다</div>':''}
      <p><b>${esc(p.label)}</b> · ${esc(p.method.toUpperCase())}</p><p class="mute">${esc(p.assumptions_note)}</p>
      <table><tr><th>항목</th><th>값</th><th>종류</th></tr>${p.items.map(i => `<tr><td>${esc(i.key)}</td><td class="num">${fmt(i.value)} ${esc(i.unit)}</td><td>${kindTag(i.kind)}</td></tr>`).join('')}</table>`;
  if (t === 'ValuationResult') return valuationView(p);
  if (t === 'Report') return `<table><tr><th>노드</th><th>관점</th><th>구분</th><th>상태</th><th>사유</th></tr>${p.entries.map(e => `<tr><td>${esc(e.type)} ${esc(e.name)}</td><td>${esc(persLabel(e.perspective))}</td><td>${TIER[e.tier]}</td><td>${chip(e.status)}</td><td>${esc(e.reason||'')}</td></tr>`).join('')}</table><p class="hint">${esc(p.notice)}</p>`;
  return `<pre class="mono">${esc(JSON.stringify(p, null, 2))}</pre>`;
}
function valuationView(p){
  const grid = () => {
    if (!p.sensitivity.length) return `<p class="mute">${esc(p.sensitivity_note)}</p>`;
    const rates = [...new Set(p.sensitivity.map(c => c.rate))], gs = [...new Set(p.sensitivity.map(c => c.growth))];
    const cell = (r, g) => p.sensitivity.find(c => c.rate === r && c.growth === g);
    return `<table class="grid"><tr><th>할인율 \\ 성장률</th>${gs.map(g => `<th>${fmt(g)}%</th>`).join('')}</tr>${rates.map(r => `<tr><th>${fmt(r)}%</th>${gs.map(g => { const c = cell(r,g);
      if (!c) return '<td></td>'; const base = c.d_rate === '0' && c.d_growth === '0';
      return `<td class="${base?'base':''} ${c.status==='held'?'held':''} ${c.warning?'w':''}" title="${esc(c.reason || c.warning || ('입력 해시 ' + (c.input_digest||'').slice(0,12)))}">${c.status==='held'?'보류':fmt(Math.round(Number(c.per_share)))}</td>`; }).join('')}</tr>`).join('')}</table>
      <p class="hint">${esc(p.sensitivity_note)} 굵은 테두리 = 기준 가정, 주황 = 할인율−성장률 2%p 미만, 단위 원/주.</p>`; };
  return `${p.illustrative ? '<div class="ill">학습용 예시 가정으로 계산 — 실제 기업가치 추정이 아닙니다</div>' : ''}
    <p class="mute">${esc(p.company_name)} · 기준연도 ${p.base_year} · ${esc(p.method.toUpperCase())} · 평가 기준일 ${esc(p.valuation_date)}</p>
    <div class="big">${fmt(Math.round(Number(p.per_share)))}원/주</div>
    <p class="mute">입력 가정에서 계산된 주당가치입니다. 목표주가·매수·매도 의견이 아닙니다. 보통주 가치 ${fmt(p.equity_value)}백만원 ÷ 희석 보통주 ${fmt(p.shares)}주 (${esc(p.share_basis)})</p>
    ${(p.alerts || []).map(w => `<div class="warn"><b>주의</b> ${esc(w)}</div>`).join('')}
    <details><summary>계산 전제와 한계 ${(p.caveats || []).length}개</summary><ul>${(p.caveats || []).map(w => `<li>${esc(w)}</li>`).join('')}</ul></details>
    ${(p.forecast_applied||[]).length ? `<h3>적용된 증권사 전망 ${kindTag('forecast_external')}</h3><table><tr><th>연도</th><th>전망 매출</th><th>전망 영업이익</th><th>→ 성장률</th><th>→ 영업이익률</th></tr>${p.forecast_applied.map(a => `<tr><td>${a.fiscal_year}E</td><td class="num">${fmt(a.revenue)}</td><td class="num">${fmt(a.op)}</td><td class="num">${fmt(a.growth)}%</td><td class="num">${fmt(a.margin)}%</td></tr>`).join('')}</table><p class="hint">성장률 = 전망 매출 / 직전 매출(2026년은 N01 원문 2025 매출) − 1. 나머지 가정은 T03 사용자 입력입니다.</p>` : ''}
    ${terminalHint(p)}
    <h3>입력값과 종류</h3><table><tr><th>항목</th><th>값</th><th>종류</th><th>출처</th></tr>${p.inputs.map(i => `<tr><td>${esc(i.label||i.key)}${i.used_in_formula===false?' <span class="mute">(참고)</span>':''}</td><td class="num">${fmt(i.value)} ${esc(i.unit||'')}</td><td>${kindTag(i.kind)}</td><td class="mono">${i.kind==='fact_official'?`<button data-fact="${esc(i.origin_ref)}">근거</button>`:esc(i.origin_ref)}</td></tr>`).join('')}</table>
    <h3>민감도</h3>${grid()}
    <h3>계산 과정</h3>${p.rows.length ? `<table><tr>${Object.keys(p.rows[0]).map(k => `<th>${esc(k)}</th>`).join('')}</tr>${p.rows.map(r => `<tr>${Object.values(r).map(v => `<td class="num">${fmt(v)}</td>`).join('')}</tr>`).join('')}</table>` : ''}
    ${p.bridge.length ? `<table>${p.bridge.map(b => `<tr><td>${esc(b.label)}</td><td class="num">${fmt(b.value)}</td></tr>`).join('')}</table>` : ''}
    <p>말기가치 현재가치 ${fmt(p.terminal_pv)}백만원 · 비중 ${fmt(p.terminal_weight_pct)}%</p>
    <h3>산식</h3><ul>${p.formulas.map(f => `<li>${esc(f)}</li>`).join('')}</ul>
    <p class="hint">N01 사실 ${p.reverification.checked}건을 원문 검증기로 다시 대조해 일치를 확인한 뒤 계산했습니다. ${esc(p.forecast_note)}</p>`;
}
function evidenceView(pkt){
  const p = pkt.payload, h = pkt.header;
  let facts = [];
  if (h.type === 'FactPackage') facts = p.facts;
  if (h.type === 'ValuationResult') facts = p.inputs.filter(i => i.kind === 'fact_official').map(i => ({fact_id:i.origin_ref, metric_label:i.label, source_value:i.value, unit:i.unit, source:i.source, scope:'', period:''}));
  if (S.focusFact) facts = facts.filter(f => f.fact_id === S.focusFact).concat(facts.filter(f => f.fact_id !== S.focusFact));
  const factHtml = facts.map(f => { const s = f.source; return `<div class="${f.fact_id===S.focusFact?'warn':''}" style="padding:6px 0;border-bottom:1px solid #eee">
     <b>${esc(f.fact_id)}</b> ${esc(f.metric_label)} = <b>${esc(f.status === 'api_reported' ? fmt(f.value) : f.source_value)}</b> ${esc(f.unit)} ${kindTag('fact_official')}
     ${f.status === 'api_reported' ? `<table><tr><th>문서</th><td>${esc(s.title)} · <a href="${esc(s.url)}" target="_blank" rel="noopener">DART 원문</a> · 접수 ${esc(s.rcept_no)} · 접수일 ${esc(s.filed_at)}</td></tr>
     <tr><th>계정</th><td>${esc(s.account_nm || '')} <span class="mono mute">${esc(s.account_id)}</span> · ${esc(f.scope)} · 공시값 ${esc(f.source_value)}원</td></tr>
     <tr><th>확인 수준</th><td>${esc(s.verification)}</td></tr><tr><th>사본</th><td class="mono">${esc(s.snapshot)} · ${esc((s.file_sha256||'').slice(0,16))}…</td></tr></table></div>` : `<table><tr><th>문서</th><td>${esc(s.title)} · <a href="${esc(s.url)}" target="_blank" rel="noopener">DART 원문 섹션</a> · 접수 ${esc(s.rcept_no)} · 공시 ${esc(s.filed_at)}</td></tr>
     <tr><th>표·셀</th><td>${esc(s.table_id)} · ${s.row}행 ${s.column}열 · 행 머리글 「${esc(s.row_label)}」</td></tr>
     <tr><th>문서 해시</th><td class="mono">${esc(s.doc_raw_hash)}</td></tr><tr><th>표 해시</th><td class="mono">${esc(s.table_raw_hash)}</td></tr>
     <tr><th>셀 배열 해시</th><td class="mono">${esc(s.matrix_digest)}</td></tr><tr><th>쪽</th><td>${s.page ?? 'HTML 원문 (쪽 번호 없음)'}</td></tr></table></div>`}`; }).join('');
  S.focusFact = null;
  return `${factHtml || '<p class="mute">이 결과에는 셀 단위 근거가 없습니다.</p>'}
    <h3>패킷 정보</h3><table><tr><th>패킷</th><td class="mono">${esc(h.packet_id)}</td></tr><tr><th>생성 노드</th><td>${esc(h.produced_by.node_id)} (${esc(h.produced_by.node_type)} v${esc(h.produced_by.version)})</td></tr>
    <tr><th>기준시점</th><td>${esc(h.cutoff)}</td></tr><tr><th>결과 해시</th><td class="mono">${esc(h.payload_digest)}</td></tr>
    <tr><th>입력 해시</th><td class="mono">${h.input_digests.map(esc).join('<br>') || '—'}</td></tr><tr><th>생성 시각</th><td>${esc(h.created_at)}</td></tr></table>`;
}

function renderOverview(){
  const p = $('#panel'); const r = S.run;
  let h = `<h2>${esc(S.doc.name)}</h2><p class="mute">${S.wfId ? `저장됨 · 버전 ${S.wfVersion}` : '아직 저장하지 않음'}${S.dirty ? ' · 저장하지 않은 변경 있음' : ''}</p>`;
  h += `<p class="desc">노드를 선택하면 설정·결과·근거·오류를 볼 수 있습니다. 실행 순서는 연결 관계에서 계산되며, 연결선 자체가 승인이나 정답을 뜻하지 않습니다.</p>`;
  const showSum = r && S.sum && S.sum.run_id === S.runId && !ACTIVE.includes(r.status);
  if (showSum) h += (S.editedSinceRun ? '<div class="stale-note">캔버스를 편집했습니다. 아래 요약은 편집 전 구성의 실행 결과입니다.</div>' : '') + summaryHtml(S.sum);
  if (r){
    h += `<h3>실행 ${chip(r.status)}</h3>${S.editedSinceRun ? '<div class="stale-note">캔버스를 편집했습니다. 아래 결과는 편집 전 구성의 실행 결과입니다.</div>' : ''}
      <table><tr><th>순서</th><th>노드</th><th>상태</th></tr>${r.order.map((id,i) => { const n = r.nodes.find(x => x.node_id === id); return `<tr><td>${i+1}</td><td>${esc(id)} <span class="mute">${esc(n.node_type)}</span></td><td>${chip(n.status)}</td></tr>`; }).join('')}</table>`;
  }
  if (S.example && S.doc.name.startsWith('예시: ')){ const ex = EXAMPLES.find(e => e.id === S.example.id) || EXAMPLES[0];
    h += `<h3>예시 사례 설명</h3><p class="desc">${esc(ex.question)}</p>${exampleStatusHtml()}<button id="bExGuide">사례 설명 전체 보기</button>`; }
  if (S.history.length) h += `<h3>저장 이력</h3><table>${S.history.map(v => `<tr><td>v${v.version}</td><td>${esc(v.saved_at.slice(0,19).replace('T',' '))}</td><td>${esc(v.note)}</td></tr>`).join('')}</table>`;
  h += `<h3>내 유형</h3><div class="prow">${personaChip()} <button id="bPersona2">${S.persona ? '바꾸기' : '3문항으로 정하기'}</button> <button id="bExList">예시 사례 고르기</button></div>`;
  h += `<h3>값의 종류 표시</h3>${Object.keys(S.reg.kinds).map(k => kindTag(k)).join(' ')}`;
  p.innerHTML = h;
  const g = $('#bExGuide'); if (g) g.onclick = showExampleGuide;
  $('#bPersona2').onclick = openPersonaQuiz; $('#bExList').onclick = openExamplePicker;
  if (showSum) bindSummary();
}

/* ---------------- issues ---------------- */
function friendlyIssue(i){
  const n = i.nodes && i.nodes[0] ? nodeById(i.nodes[0]) : null, sp = n ? spec(n.type) : null;
  let msg = i.message, fix = i.fix, acts = [];
  if (i.code === 'missing_input' && n){
    const miss = missingInputs(n);
    const what = miss.map(m => `「${m.label}」`).join(', ') || '필요한 자료';
    if (sp.implementation === 'not_connected'){
      msg = `${nodeLabel(n.type)}에 ${J(what,'이가')} 연결되지 않았어요. 이 노드는 아직 준비 중이라 연결해도 결과가 나오지 않아요.`;
      fix = '이번 실행에서는 빼 두는 것이 가장 간단해요.';
      acts.push(['del', n.id, `${n.type} 빼기`]);
    } else {
      const mk = miss.map(m => producersOf(m.type)[0]).filter(Boolean);
      msg = `${J(nodeLabel(n.type),'이가')} 일하려면 ${J(what,'이가')} 필요해요.`;
      fix = mk.length ? `${J(mk.map(x => x.id).join('·'),'이가')} 이 자료를 만들어요. 버튼을 누르면 놓고 이어 드려요.` : '이 자료를 만드는 노드가 아직 없어요.';
      if (mk.length) acts.push(['fill', n.id, '필요한 앞 노드 채우기']);
    }
  } else if (i.code === 'type_mismatch' && i.edge !== null && i.edge !== undefined){
    fix = '서로 다른 자료라 이 연결선은 쓸 수 없어요.'; acts.push(['edge', i.edge, '이 연결선 지우기']);
  } else if (i.code === 'not_connected_node' && n){
    msg = `${J(nodeLabel(n.type),'은는')} 아직 준비 중이라, 실행하면 「미연결」로 기록되고 결과는 비어 있어요.`; fix = '그대로 실행해도 다른 노드에는 영향이 없어요.';
  } else if (i.code === 'assumption_invalid' && n && n.type === 'T03'){
    const empty = !Object.keys(n.config.model || {}).length;
    msg = empty ? '가치평가(N02)에 쓸 가정이 비어 있어요. 이 앱은 가정을 대신 지어내지 않아요.' : `가치평가 가정에 고칠 곳이 있어요: ${i.message.replace('가정 입력 오류: ', '')}`;
    fix = '체험만 하려면 「학습용 예시」로 채우세요(결과에 「실제 추정 아님」 표시). 직접 넣으려면 설정을 열고, 가치평가가 필요 없으면 빼도 돼요.';
    acts.push(['t03ill', n.id, '학습용 예시로 채우기'], ['t03open', n.id, '설정 열기'], ['t03del', n.id, '가치평가(T03·N02) 빼기']);
  } else if (i.code === 'cutoff_default'){
    msg = '기준시점을 비워 두어서, 지금 이 순간을 기준으로 계산해요.'; fix = '특정 날짜로 고정하고 싶으면 위쪽 「기준시점」 칸에 입력하세요.';
  }
  return {msg, fix, acts};
}
function renderIssues(){
  const box = $('#issues');
  if (!S.issues.length){ box.hidden = true; return; }
  box.hidden = false;
  const errs = S.issues.filter(i => i.severity === 'error');
  box.innerHTML = `<b>${errs.length ? `실행 전에 ${errs.length}가지만 손보면 돼요` : '실행할 수 있어요'}</b>${S.issues.length - errs.length ? ` · 알아 둘 점 ${S.issues.length - errs.length}가지` : ''}` +
    S.issues.map((i, k) => { const f = friendlyIssue(i);
      return `<div class="iss ${i.severity}"><b>${i.severity === 'error' ? '손볼 것' : '알아 두기'}</b> ${esc(f.msg)} <span class="fix">→ ${esc(f.fix)}</span>
        ${f.acts.map(a => `<button class="issact" data-act="${a[0]}" data-arg="${esc(String(a[1]))}">${esc(a[2])}</button>`).join('')}
        <span class="mute mono" title="오류 코드">${esc(i.code)}</span></div>`; }).join('');
  box.querySelectorAll('.issact').forEach(b => b.onclick = () => {
    const a = b.dataset.act, arg = b.dataset.arg;
    if (a === 'fill'){ const n = nodeById(arg); const added = fillInputs(n); touch(); renderAll(); if (added.length) fit(); toast(added.length ? `앞 노드 ${added.length}개를 놓고 연결했어요.` : '캔버스에 있던 노드로 연결했어요.'); }
    if (a === 'del'){ S.doc.nodes = S.doc.nodes.filter(n => n.id !== arg); S.doc.edges = S.doc.edges.filter(e => e.from_node !== arg && e.to_node !== arg); if (S.sel === arg) S.sel = null; touch(); renderAll(); toast('뺐어요. 필요하면 라이브러리에서 다시 넣을 수 있어요.'); }
    if (a === 't03ill'){ const n = nodeById(arg), t = TEMPLATES[n.config.method || 'dcf'] || TEMPLATES.dcf;
      Object.assign(n.config, {model: JSON.parse(JSON.stringify(t.ill)), input_kind:'illustrative_assumptions', label: '학습용 ' + (n.config.method||'dcf').toUpperCase(),
        shares: '5900000000', share_basis: '학습용 예시 주식 수 (실제 희석주식수 아님)', assumptions_note: '계산 흐름 체험용 임의 가정. 실제 기업가치 추정이 아님'});
      touch(); renderAll(); toast('학습용 예시를 채웠어요. 가치평가 결과에는 「실제 추정 아님」이 붙어요.'); }
    if (a === 't03open'){ S.sel = arg; S.selEdge = null; S.tab = 'config'; renderAll(); }
    if (a === 't03del'){ const drop = new Set([arg, ...S.doc.edges.filter(e => e.from_node === arg && e.to_port === 'assumptions').map(e => e.to_node).filter(id => (nodeById(id) || {}).type === 'N02')]);
      S.doc.nodes = S.doc.nodes.filter(x => !drop.has(x.id)); S.doc.edges = S.doc.edges.filter(e => !drop.has(e.from_node) && !drop.has(e.to_node)); if (drop.has(S.sel)) S.sel = null;
      touch(); renderAll(); toast(`가치평가 노드 ${drop.size}개를 뺐어요. 나머지 분석은 그대로 실행돼요.`); }
    if (a === 'edge'){ S.doc.edges.splice(+arg, 1); touch(); renderAll(); toast('연결선을 지웠어요.'); }
    doValidate(true);
  });
}
async function doValidate(quiet){
  syncHeader();
  try { const r = await api('/api/validate', {method:'POST', body:{doc:S.doc}}); S.issues = r.issues; }
  catch(e){ S.issues = (e.data && e.data.issues) || [{code:'request', severity:'error', message:e.message, fix:'', nodes:[], edge:null}]; }
  renderIssues(); renderNodes(); renderEdges();
  const errs = S.issues.filter(i => i.severity === 'error').length;
  if (!quiet) toast(errs ? `실행 전에 ${errs}가지만 손보면 돼요. 아래 목록의 버튼을 눌러 보세요.` : '확인 끝! 실행할 수 있어요.');
  return errs === 0;
}

/* ---------------- save / open / run ---------------- */
function syncHeader(){ S.doc.name = $('#wfName').value.trim() || '이름 없음'; S.doc.cutoff = $('#cutoff').value.trim(); }
async function save(note){
  syncHeader();
  try {
    const r = S.wfId ? await api('/api/workflows/' + S.wfId, {method:'PUT', body:{doc:S.doc, note: note || '저장'}})
                     : await api('/api/workflows', {method:'POST', body:{doc:S.doc, note: note || '처음 저장'}});
    S.wfId = r.id; S.wfVersion = r.version; S.dirty = false; setHash();
    const wf = await api('/api/workflows/' + S.wfId); S.history = wf.history;
    renderHeader(); renderPanel(); if (!note) toast(`저장했습니다 (버전 ${r.version}).`);
    return true;
  } catch(e){ toast('저장 실패: ' + e.message); return false; }
}
function setHash(){ const p = []; if (S.wfId) p.push('wf=' + S.wfId); if (S.runId) p.push('run=' + S.runId); history.replaceState(null, '', '#' + p.join('&')); }
async function run(){
  if (!(await doValidate(true))){ toast('실행 전 오류를 먼저 고치세요 (아래 목록).'); return; }
  if (!(await save('실행 전 자동 저장'))) return;
  try {
    const r = await api('/api/runs', {method:'POST', body:{doc:S.doc, workflow_id:S.wfId, workflow_version:S.wfVersion}});
    S.runId = r.id; S.editedSinceRun = false; setHash(); await loadRun(r.id); startPoll();
  } catch(e){ if (e.data && e.data.issues){ S.issues = e.data.issues; renderIssues(); } toast('실행 거절: ' + (e.status === 409 ? e.data : e.message)); }
}
async function cancel(){ if (!S.runId) return; const r = await api(`/api/runs/${S.runId}/cancel`, {method:'POST', body:{}}); toast(r.status === 'cancelling' ? '취소를 요청했습니다. 진행 중인 노드를 멈춥니다.' : '이미 끝난 실행입니다.'); }
async function loadRun(id){
  const wasActive = S.run && S.runId === id && ACTIVE.includes(S.run.status);
  S.run = await api('/api/runs/' + id); S.runId = id;
  const done = !ACTIVE.includes(S.run.status);
  if (done && (!S.sum || S.sum.run_id !== id)) await loadSummary(id);
  if (done && wasActive){ S.sel = null; S.selEdge = null; toast('실행이 끝났어요. 오른쪽 「실행 결과 요약」에서 무엇을 확인했고 무엇을 모르는지 한눈에 보세요.'); }
  renderRunbar(); renderNodes(); renderEdges(); renderPanel(); renderHeader();
  if (done) stopPoll();
}
/* ---------------- v0.24.2 실행 결과 요약 — 실행이 끝나면 관점별로 글로 정리 (쉬운 화면 답 카드와 같은 근거) ---------------- */
async function loadSummary(id){
  try { S.sum = await api('/api/easy/answer/' + id); } catch(e){ S.sum = null; }
}
const PERSP_ORDER = ['fundamentals', 'industry', 'macro', 'flow', 'technical', 'sentiment', 'common'];
function summaryGroups(a){
  const ns = (a.nodes || []).filter(n => n.type.startsWith('N'));
  const by = {};
  ns.forEach(n => { const p = spec(n.type)?.perspective || 'common'; (by[p] = by[p] || []).push(n); });
  return PERSP_ORDER.filter(p => by[p]).map(p => ({p, label: persLabel(p), nodes: by[p].map(n => ({...n,
    items: a.items.filter(i => i.node === n.id), unknown: a.unknown.filter(u => u.node === n.id)}))}));
}

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
function summaryHtml(a){
  const c = {}; (a.nodes || []).filter(n => n.type.startsWith('N')).forEach(n => c[n.status] = (c[n.status] || 0) + 1);
  const st = Object.entries(c).map(([k, v]) => `${STATUS[k] || k} ${v}`).join(' · ');
  const tierCls = {fact:'k-fact', calc:'k-der', estimate:'k-model'};
  const groups = summaryGroups(a);
  return `<section class="sum"><h3>실행 결과 요약</h3>
    <p class="sumhead"><b>${esc(a.name || '')}</b> · ${esc(asofText(a))}<br>
      분석 ${groups.reduce((x, g) => x + g.nodes.length, 0)}개: ${esc(st)} — 자료로 확인 <b>${a.count.fact}</b> · 계산 <b>${a.count.calc}</b> · 추정·가정 <b>${a.count.estimate}</b> · 아직 모르는 것 <b>${a.unknown.length}</b></p>
    <p class="mute">결론이 아니라 정리예요. 관점마다 무엇을 확인했고 무엇을 모르는지 그대로 모았어요. 노드 이름을 누르면 그 단계의 결과·근거가 열려요.</p>
    ${groups.map(g => `<div class="sg" style="--pc:var(--p-${g.p})"><div class="sgh">${esc(g.label)}</div>
      ${g.nodes.map(n => `<div class="sn"><a href="#" data-sel="${esc(n.id)}"><b>${esc(n.type)} ${esc(n.name)}</b></a> ${chip(n.status)}
        ${n.items.length ? `<ul>${n.items.slice(0, 4).map(i => `<li><span class="ktag ${tierCls[i.tier] || ''}">${esc(i.tier_label)}</span> <b>${esc(i.label)}</b>: ${esc(i.text)}</li>`).join('')}</ul>
          ${n.items.length > 4 ? `<details><summary>${n.items.length - 4}개 더 보기</summary><ul>${n.items.slice(4).map(i => `<li><span class="ktag ${tierCls[i.tier] || ''}">${esc(i.tier_label)}</span> <b>${esc(i.label)}</b>: ${esc(i.text)}</li>`).join('')}</ul></details>` : ''}` : ''}
        ${n.unknown.length ? `<div class="sunk">아직 모르는 것: ${n.unknown.map(u => esc(u.text)).join(' / ')}</div>` : ''}
        ${!n.items.length && !n.unknown.length ? '<div class="mute">보여 줄 숫자가 없어요 — 결과 탭을 보세요.</div>' : ''}</div>`).join('')}</div>`).join('')}
    ${a.limits.length ? `<div class="snot"><b>이 결과가 아닌 것</b><ul><li>${esc(a.not_this)}</li>${a.limits.slice(0, 4).map(x => `<li>${esc(x)}</li>`).join('')}</ul></div>` : `<div class="snot"><b>이 결과가 아닌 것</b> ${esc(a.not_this)}</div>`}
    <div class="sacts"><a class="btnlink" href="/#answer=${esc(a.run_id)}">쉬운 화면 답 카드로 보기 →</a> <button id="sumCopy">요약을 글로 복사</button> <button id="sumT05">T05 보고서 취합 결과</button></div></section>`;
}
function summaryText(a){
  const L = [`[모두의리서치 · 기업분석 실행 결과 요약] ${a.name || ''} · ${asofText(a)}`,
    `자료로 확인 ${a.count.fact} · 계산 ${a.count.calc} · 추정·가정 ${a.count.estimate} · 아직 모르는 것 ${a.unknown.length}`, ''];
  summaryGroups(a).forEach(g => { L.push(`■ ${g.label}`);
    g.nodes.forEach(n => { L.push(`  ${n.type} ${n.name} (${STATUS[n.status] || n.status})`);
      n.items.forEach(i => L.push(`   - [${i.tier_label}] ${i.label}: ${i.text}`));
      n.unknown.forEach(u => L.push(`   - [아직 모름] ${u.text}`)); }); L.push(''); });
  L.push(`※ ${a.not_this}`, `※ 실행 번호 ${a.run_id} — 같은 기준 날짜로 다시 계산하면 같은 결과가 나와요(근거 확인서는 쉬운 화면에서 내려받기).`);
  return L.join('\n');
}
function bindSummary(){
  const a = S.sum; if (!a) return;
  document.querySelectorAll('.sum [data-sel]').forEach(x => x.onclick = ev => { ev.preventDefault(); S.sel = x.dataset.sel; S.tab = 'result'; renderNodes(); renderPanel(); });
  const cp = $('#sumCopy'); if (cp) cp.onclick = async () => { try { await navigator.clipboard.writeText(summaryText(a)); toast('요약을 글로 복사했어요. 메모·메일에 붙여 넣을 수 있어요.'); } catch(e){ toast('복사하지 못했어요(브라우저 권한).'); } };
  const t5 = $('#sumT05'); if (t5) t5.onclick = () => { const n = S.doc.nodes.find(x => x.type === 'T05'); if (!n){ toast('T05 보고서 취합 노드가 없어요.'); return; } S.sel = n.id; S.tab = 'result'; renderNodes(); renderPanel(); };
}
function startPoll(){ stopPoll(); S.poll = setInterval(() => loadRun(S.runId).catch(() => {}), 1000); }
function stopPoll(){ if (S.poll){ clearInterval(S.poll); S.poll = null; } }
function renderRunbar(){
  const r = S.run, bar = $('#runbar'); if (!r){ bar.hidden = true; return; } bar.hidden = false;
  $('#runStatus').className = 'chip s-' + r.status; $('#runStatus').innerHTML = (r.status === 'running' ? '<span class="spin"></span>' : '') + '실행 ' + (STATUS[r.status] || r.status);
  const done = r.nodes.filter(n => !ACTIVE.includes(n.status)).length;
  $('#runProgress').textContent = `처리 ${done}/${r.nodes.length} 노드`;
  $('#runElapsed').textContent = r.started_at ? `경과 ${secs(r.started_at, r.finished_at || r.server_time).toFixed(1)}초` : '';
  const stalled = r.nodes.some(n => n.stalled);
  $('#runStep').textContent = ACTIVE.includes(r.status) ? (stalled ? '⚠ 진행 신호가 10초 넘게 없습니다. ' : '') + (r.current_step || '대기 중') :
    (r.status === 'interrupted' ? '서버 재시작으로 중단된 실행입니다. 자동으로 다시 실행하지 않습니다.' : `완료 ${kst(r.finished_at)}`);
  const c = {}; r.nodes.forEach(n => c[n.status] = (c[n.status] || 0) + 1);
  const tools = r.nodes.reduce((a, n) => a + n.tool_calls, 0), models = r.nodes.reduce((a, n) => a + n.model_calls, 0);
  $('#runCounts').innerHTML = `<span class="chip s-waiting">계획 ${r.nodes.length}</span>` + Object.entries(c).map(([k,v]) => `<span class="chip s-${k}">${STATUS[k]} ${v}</span>`).join('') +
    ` <span class="mute">도구 ${tools}회 · 모델 ${models}회</span>`;
  let ra = $('#runActs'); if (!ra){ ra = document.createElement('span'); ra.id = 'runActs'; bar.appendChild(ra); }
  ra.innerHTML = ACTIVE.includes(r.status) ? '' : `<button id="raSum" class="primary">결과 요약 보기</button> <a class="btnlink" href="/#answer=${esc(S.runId)}">쉬운 화면 답 카드 →</a>`;
  if ($('#raSum')) $('#raSum').onclick = async () => { if (!S.sum || S.sum.run_id !== S.runId) await loadSummary(S.runId); S.sel = null; S.selEdge = null; renderNodes(); renderEdges(); renderPanel(); $('#panel').scrollTop = 0; };
}
async function openDialog(){
  const list = await api('/api/workflows');
  $('#dlgBody').innerHTML = `<h2>저장된 워크플로</h2>${list.length ? `<table><tr><th>이름</th><th>버전</th><th>수정</th><th></th></tr>${list.map(w => `<tr><td>${esc(w.name)}</td><td>v${w.version}</td><td>${esc(w.updated_at.slice(0,19).replace('T',' '))}</td><td><button data-open="${w.id}">열기</button></td></tr>`).join('')}</table>` : '<p class="mute">저장된 워크플로가 없습니다.</p>'}<div id="dlgRuns"></div>`;
  $('#dlgBody').querySelectorAll('[data-open]').forEach(b => b.onclick = async () => {
    await openWorkflow(b.dataset.open, null);
    const wf = await api('/api/workflows/' + b.dataset.open);
    $('#dlgRuns').innerHTML = `<h3>이 워크플로의 실행 기록</h3>${wf.runs.length ? `<table>${wf.runs.map(r => `<tr><td>${esc(r.created_at.slice(0,19).replace('T',' '))}</td><td>v${r.workflow_version}</td><td>${chip(r.status)}</td><td><button data-run="${r.id}">결과 보기</button></td></tr>`).join('')}</table>` : '<p class="mute">실행 기록 없음</p>'}`;
    $('#dlgRuns').querySelectorAll('[data-run]').forEach(x => x.onclick = async () => { await openRun(x.dataset.run); $('#dlg').close(); });
  });
  $('#dlg').showModal();
}
async function openWorkflow(id, runId){
  const wf = await api('/api/workflows/' + id);
  S.doc = wf.doc; S.wfId = id; S.wfVersion = wf.version; S.history = wf.history; S.dirty = false; S.sel = null; S.selEdge = null;
  S.run = null; S.runId = null; S.editedSinceRun = false; stopPoll(); renderRunbar();
  renderAll(); fit();
  if (runId) await openRun(runId);
  setHash();
}
async function openRun(runId){
  await loadRun(runId);
  if (S.run.workflow_version && S.run.workflow_version !== S.wfVersion){
    S.doc = S.run.doc; S.dirty = false; renderAll(); fit();
    toast(`실행 당시 구성(버전 ${S.run.workflow_version})을 불러왔습니다. 저장하면 새 버전이 됩니다.`);
  }
  if (ACTIVE.includes(S.run.status)) startPoll();
  setHash();
}

/* ---------------- broker forecasts: approve / compare / timeline ---------------- */
const STATE_KO = {proposed:'미승인', approved:'승인', rejected:'제외', stale:'무효(재스캔)'};
const jo = v => v == null || v === '' ? '—' : (Number(v)/1e6).toLocaleString('ko-KR', {maximumFractionDigits:1}) + '조';
S.bTab = 'compare';
async function openBroker(){
  $('#dlgBody').innerHTML = `<h2>증권사 전망 <span class="mute" style="font-size:12px">외부 전망 · 사람 승인 후에만 N02에 사용</span></h2>
    <div class="tabs">${[['inbox','받은 보고서 등록'],['compare','비교표'],['timeline','목표주가 변화'],['review','승인']].map(([k,l]) => `<button data-bt="${k}" class="${S.bTab===k?'on':''}">${l}</button>`).join('')}
    <span style="flex:1"></span><button id="bScan">PDF 다시 스캔</button></div><div id="bBody"><p class="mute">불러오는 중…</p></div>`;
  $('#dlgBody').querySelectorAll('[data-bt]').forEach(b => b.onclick = () => { S.bTab = b.dataset.bt; openBroker(); });
  $('#bScan').onclick = async () => { $('#bBody').innerHTML = '<p class="mute">스캔 중… (보고서 수에 따라 수 초)</p>';
    try { const r = await api('/api/broker/scan', {method:'POST', body:{}}); toast(`보고서 ${r.reports}건 · 후보 ${r.candidates}건 (유지 ${r.kept}, 새로 ${r.new}, 재검토 필요 ${r.reset})`); }
    catch(e){ toast('스캔 실패: ' + e.message); } openBroker(); };
  $('#dlg').classList.add('wide'); $('#dlg').addEventListener('close', () => $('#dlg').classList.remove('wide'), {once:true});
  if (!$('#dlg').open) $('#dlg').showModal();
  try {
    if (S.bTab === 'review') return renderBrokerReview();
    if (S.bTab === 'inbox') return renderBrokerInbox();
    const d = await api('/api/broker/compare');
    if (!d.rows.length){ $('#bBody').innerHTML = '<p>스캔된 보고서가 없습니다. 「PDF 다시 스캔」을 누르세요.</p>'; return; }
    if (S.bTab === 'timeline') return renderTimeline(d);
    renderCompare(d);
  } catch(e){ $('#bBody').innerHTML = `<p class="warn">불러오기 실패: ${esc(e.message)}</p>`; }
}
function cellHtml(c){
  if (!c) return '<td class="mute">—</td>';
  return `<td class="num bc-${c.state}" title="${esc('p.' + c.page + ' · ' + c.quote)}">${jo(c.value_mn)}${c.edited?'✎':''}<div class="bstate">${STATE_KO[c.state]}</div></td>`;
}
function renderCompare(d){
  const L = {'2026:revenue':'2026E 매출','2026:operatingProfit':'2026E 영업이익','2027:revenue':'2027E 매출','2027:operatingProfit':'2027E 영업이익'};
  const st = (k, which) => { const s = d.summary[k] && d.summary[k][which]; return s ? `${jo(s.min)} / ${jo(s.median)} / ${jo(s.max)} <span class="mute">(${s.count}건)</span>` : '—'; };
  const tps = d.summary.target_price.all;
  $('#bBody').innerHTML = `<p class="hint">${esc(d.notice)} 칸에 마우스를 올리면 원문 쪽과 인용이 보입니다.</p>
    <div style="overflow:auto"><table class="btab"><tr><th>보고서일</th><th>증권사</th><th>의견</th><th>목표주가</th><th>배수</th>${d.columns.map(k => `<th>${L[k]}</th>`).join('')}<th>과거 실적 대조</th></tr>
    ${d.rows.map(r => `<tr><td>${esc(r.report_date)}</td><td>${esc(r.broker)}</td><td>${esc(r.opinion||'—')}</td>
      <td class="num" title="${esc(r.tp_quote ? 'p.'+r.tp_page+' · '+r.tp_quote : '본문 텍스트에 없음')}">${r.target_price ? Number(r.target_price).toLocaleString('ko-KR') : '<span class="mute">본문에 없음</span>'}</td>
      <td title="${esc(r.multiple_quote||'')}">${esc(r.multiple||'—')}</td>${d.columns.map(k => cellHtml(r.cells[k])).join('')}
      <td>${r.past_check==='match'?'✅ 원문 일치':r.past_check==='mismatch'?'⚠️ 불일치':r.status==='no_table'?'<span class="mute">표 미추출</span>':'<span class="mute">대조 불가</span>'}</td></tr>`).join('')}
    <tr class="bsum"><td colspan="3">최저 / 중앙 / 최고 (승인+미승인)</td><td class="num">${tps ? `${Number(tps.min).toLocaleString()} / ${Number(tps.median).toLocaleString()} / ${Number(tps.max).toLocaleString()}` : '—'}</td><td></td>${d.columns.map(k => `<td class="num">${st(k,'all')}</td>`).join('')}<td></td></tr>
    <tr class="bsum"><td colspan="5">같은 통계 (승인된 것만)</td>${d.columns.map(k => `<td class="num">${st(k,'approved')}</td>`).join('')}<td></td></tr></table></div>
    <p class="hint">단위: 조원(백만원 값을 표시용으로 환산). ✎ = 사람이 수정한 값. 「과거 실적 대조」는 보고서 표의 2024·2025 실적이 N01 공식 원문과 같은지입니다.</p>
    ${d.rows.filter(r => r.notes.length).map(r => `<div class="mute">• ${esc(r.report_date)} ${esc(r.broker)}: ${esc(r.notes.join(' / '))}</div>`).join('')}`;
}
function renderTimeline(d){
  const brokers = Object.entries(d.timeline);
  const pts = brokers.flatMap(([b, ps]) => ps.filter(p => p.tp && p.date).map(p => ({...p, b})));
  const dates = pts.map(p => +new Date(p.date)); const tpv = brokers.flatMap(([b, ps]) => ps.filter(p => p.tp).map(p => p.tp));
  const x0 = Math.min(...dates) - 4*864e5, x1 = Math.max(...dates) + 4*864e5, y0 = Math.min(...tpv) * 0.9, y1 = Math.max(...tpv) * 1.05;
  const W = 820, H = 380, L = 70, R = 170, T = 20, B = 40;
  const X = t => L + (t - x0) / (x1 - x0) * (W - L - R), Y = v => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
  const pal = ['#1971c2','#e8590c','#2f9e44','#9c36b5','#c2255c','#0c8599','#946200','#495057','#5f3dc4','#f59f00','#087f5b','#868e96'];
  let svg = '', legend = '';
  for (let v = Math.ceil(y0/50000)*50000; v <= y1; v += 50000) svg += `<line x1="${L}" x2="${W-R}" y1="${Y(v)}" y2="${Y(v)}" stroke="#eee"/><text x="${L-6}" y="${Y(v)+4}" text-anchor="end" font-size="10" fill="#888">${(v/10000).toLocaleString()}만</text>`;
  const months = ['2026-09-01','2026-10-01','2026-11-01'].filter(m => +new Date(m) > x0 && +new Date(m) < x1);
  months.forEach(m => svg += `<line x1="${X(+new Date(m))}" x2="${X(+new Date(m))}" y1="${T}" y2="${H-B}" stroke="#eee"/><text x="${X(+new Date(m))}" y="${H-B+16}" text-anchor="middle" font-size="10" fill="#888">${m.slice(5,7)}월</text>`);
  brokers.forEach(([b, ps], i) => {
    const col = pal[i % pal.length]; const real = ps.filter(p => p.tp && p.date).sort((a,c) => a.date.localeCompare(c.date));
    if (real.length > 1) svg += `<polyline fill="none" stroke="${col}" stroke-width="2" points="${real.map(p => X(+new Date(p.date)) + ',' + Y(p.tp)).join(' ')}"/>`;
    real.forEach(p => svg += `<circle cx="${X(+new Date(p.date))}" cy="${Y(p.tp)}" r="4.5" fill="${col}"><title>${esc(b)} ${p.date} 목표주가 ${p.tp.toLocaleString()}원</title></circle>`);
    ps.filter(p => p.kind === 'prior_mention').forEach(p => { const first = real[0]; if (!first) return; const cx = X(+new Date(first.date)) - 14;
      svg += `<line x1="${cx}" y1="${Y(p.tp)}" x2="${X(+new Date(first.date))}" y2="${Y(first.tp)}" stroke="${col}" stroke-dasharray="3 3"/><circle cx="${cx}" cy="${Y(p.tp)}" r="4" fill="#fff" stroke="${col}" stroke-width="2"><title>${esc(p.note)}: ${p.tp.toLocaleString()}원</title></circle>`; });
    const missing = ps.filter(p => p.kind === 'report' && !p.tp).length;
    legend += `<text x="${W-R+12}" y="${T + 14 + i*18}" font-size="11" fill="${col}">● ${esc(b)}${real.length>1 ? ' ('+real.length+'회)' : ''}${missing ? ' · 미기재 '+missing : ''}</text>`;
  });
  const changes = brokers.map(([b, ps]) => { const r = ps.filter(p => p.tp).sort((a,c) => (a.date||'0').localeCompare(c.date||'0')); if (r.length < 2) return null;
    const diff = r[r.length-1].tp - r[0].tp; return `${b}: ${r.map(p => (p.date ? p.date.slice(5) : '이전') + ' ' + (p.tp/10000) + '만').join(' → ')} ${diff ? (diff>0?'▲상향':'▼하향') : '(변화 없음)'}`; }).filter(Boolean);
  $('#bBody').innerHTML = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;max-width:${W}px;background:#fff;border:1px solid var(--line);border-radius:6px">${svg}${legend}</svg>
    <h3>증권사별 변화</h3>${changes.length ? '<ul>' + changes.map(c => `<li>${esc(c)}</li>`).join('') + '</ul>' : '<p class="mute">두 번 이상 나온 증권사가 없습니다.</p>'}
    <p class="hint">점 = 보고서별 목표주가, 속이 빈 점(점선) = 보고서 본문에 「기존 ○○원」으로 언급된 이전 값(날짜 미상). 목표주가가 본문 텍스트에 없는 보고서(키움 10월 노트 등)는 선에서 빠집니다. 수집한 3개월치 보고서 기준이며, 그 밖의 변경은 반영되지 않습니다.</p>`;
}
async function renderBrokerInbox(){
  const r = await api('/api/broker/inbox');
  const todo = r.items.filter(i => !i.registered);
  $('#bBody').innerHTML = `<p class="hint">증권사 리포트를 내려받아 <span class="mono">${esc(r.folder)}</span> 폴더에 넣으세요(폴더가 없으면 만들면 돼요). 앱이 첫 쪽 글자로 칸을 미리 채워요 — <b>틀릴 수 있으니 확인·고친 뒤 등록</b>하세요. 등록하면 보고서 폴더로 복사되고(원본은 그대로) 목록(manifest)에 한 줄이 더해집니다. 그다음 「PDF 다시 스캔」 → 「승인」.</p>
    ${todo.length ? todo.map((i, k) => { const g = i.guess || {}; return `<fieldset class="inb" data-k="${k}"><legend>${esc(i.file)} · ${i.pages || '?'}쪽</legend>${i.note ? `<div class="warn">${esc(i.note)}</div>` : ''}
      <label>종목코드 <input data-f="ticker" value="${esc(g.ticker || '')}" size="7"></label> <label>증권사 <input data-f="broker" value="${esc(g.broker || '')}" size="12"></label>
      <label>보고서 날짜 <input data-f="report_date" value="${esc(g.report_date || '')}" size="11" placeholder="YYYY-MM-DD"></label><br>
      <label>제목 <input data-f="title" value="${esc(g.title || '')}" size="40"></label> <label>투자의견 <input data-f="opinion" value="${esc(g.opinion || '')}" size="8"></label>
      <label>목표주가(원) <input data-f="target_price" value="${esc(g.target_price || '')}" size="9"></label>
      <button data-reg="${esc(i.file)}">확인했어요, 등록</button></fieldset>`; }).join('') : '<p>등록할 새 PDF가 없어요.</p>'}
    ${r.items.some(i => i.registered) ? `<p class="mute">이미 등록된 파일 ${r.items.filter(i => i.registered).length}개(같은 해시)는 건너뜁니다.</p>` : ''}`;
  $('#bBody').querySelectorAll('[data-reg]').forEach(b => b.onclick = async () => {
    const fs = b.closest('fieldset'); const body = {file: b.dataset.reg};
    fs.querySelectorAll('[data-f]').forEach(x => body[x.dataset.f] = x.value.trim());
    try { await api('/api/broker/register', {method:'POST', body}); toast('등록했어요. 「PDF 다시 스캔」을 눌러 전망 후보를 뽑으세요.'); renderBrokerInbox(); }
    catch(e){ toast('등록 실패: ' + e.message); } });
}
async function renderBrokerReview(){
  const r = await api('/api/broker/reports');
  if (!r.reports.length){ $('#bBody').innerHTML = '<p>스캔된 보고서가 없습니다. 「PDF 다시 스캔」을 누르세요.</p>'; return; }
  const byFile = f => r.candidates.filter(c => c.file === f && c.state !== 'stale');
  $('#bBody').innerHTML = `<p class="hint">후보마다 원문 쪽·인용을 확인하고 승인하세요. 승인된 전망만 T04를 거쳐 N02에 들어갑니다. 수정은 백만원 단위로 입력하고 사유를 적어야 합니다. 모든 결정은 기록됩니다.</p>` +
    r.reports.sort((a,b) => a.report_date.localeCompare(b.report_date)).map(rep => { const cs = byFile(rep.file); const pend = cs.filter(c => c.state === 'proposed').length;
      return `<details ${pend ? 'open' : ''}><summary><b>${esc(rep.report_date)} ${esc(rep.broker)}</b> — ${esc(rep.title||'')} · 후보 ${cs.length} · 미승인 ${pend} ${rep.past_check==='match'?'· ✅ 과거 실적 원문 일치':''}${rep.status!=='ok'?' · <span class="warn">'+esc(rep.status)+'</span>':''}</summary>
      ${rep.notes.length ? `<div class="mute">${esc(rep.notes.join(' / '))}</div>` : ''}
      ${cs.length ? `<table><tr><th>지표</th><th>연도</th><th>값(원문)</th><th>백만원</th><th>범위</th><th>원문 근거</th><th>상태</th><th></th></tr>${cs.map(c => `<tr>
        <td>${esc(c.metric_label)}</td><td>${esc(c.year_label)}</td><td class="num">${esc(c.value_original)} ${esc(c.unit_original)}</td><td class="num">${fmt(c.effective_value_mn)}${c.review_value_mn?' ✎':''}</td>
        <td>${esc(c.scope)}</td><td class="mono" style="max-width:260px">p.${c.page} · ${esc(c.quote.slice(0,110))}</td><td class="bc-${c.state}">${STATE_KO[c.state]}${c.review_note?'<div class="mute">'+esc(c.review_note)+'</div>':''}</td>
        <td style="white-space:nowrap"><button data-act="approve" data-id="${esc(c.id)}">승인</button> <button data-act="reject" data-id="${esc(c.id)}">제외</button> <button data-act="edit" data-id="${esc(c.id)}">수정</button>${c.state!=='proposed'?` <button data-act="reset" data-id="${esc(c.id)}">되돌리기</button>`:''}</td></tr>`).join('')}</table>
        ${pend ? `<button data-allfile="${esc(rep.file)}">이 보고서 미승인 ${pend}건 모두 승인</button>` : ''}` : '<p class="mute">추출된 후보가 없습니다.</p>'}</details>`; }).join('');
  $('#bBody').querySelectorAll('[data-act]').forEach(b => b.onclick = async () => {
    const body = {id: b.dataset.id, action: b.dataset.act};
    if (body.action === 'edit'){ body.value_mn = prompt('수정값(백만원 단위 숫자)'); if (!body.value_mn) return; body.note = prompt('수정 사유(필수)') || ''; if (!body.note.trim()) return toast('수정 사유가 필요합니다.'); }
    if (body.action === 'reject'){ body.note = prompt('제외 사유(선택)') || ''; }
    try { await api('/api/broker/review', {method:'POST', body}); renderBrokerReview(); } catch(e){ toast('실패: ' + e.message); } });
  $('#bBody').querySelectorAll('[data-allfile]').forEach(b => b.onclick = async () => { await api('/api/broker/review', {method:'POST', body:{file:b.dataset.allfile, action:'approve_report'}}); renderBrokerReview(); });
}

/* ---------------- numeric expression checker ---------------- */
const TIER_UI = {verified:['✅ 검증됨','t-ver'], computed:['✅ 코드 계산','t-ver'], match:['🧮 계산과 일치','t-match'], mismatch:['⚠️ 불일치·근거 없음','t-mis'],
  external:['🔵 외부 전망','t-ext'], model:['🟡 모델 판단','t-model'], red:['🔴 미검증 수치','t-red'], hidden:['숨긴 매매 표현','t-hid'], info:['기간·고유명사','t-info']};
const CHECK_SAMPLE = '삼성전자 2025년 매출은 {{fact:005930:2025:revenue}}로 전년 대비 {{calc:pct(005930:2025:revenue,005930:2024:revenue)}} 소폭 늘었습니다.\nSK하이닉스 영업이익은 {{calc:pct(000660:2025:operatingProfit,000660:2024:operatingProfit)}} 급증해 사상 최대를 기록했습니다.\n삼성전자 2025년 매출은 310조원으로 SK하이닉스보다 세 배 이상 큽니다.\n외국인 5일 연속 순매수와 골든크로스로 저평가 해소가 기대되며 매수 의견을 유지합니다.';
function openChecker(){
  const runOpt = S.runId ? `<option value="${esc(S.runId)}">현재 실행의 N01 결과</option>` : '';
  $('#dlgBody').innerHTML = `<h2>표현 검사기 <span class="mute" style="font-size:12px">규칙 v0.3</span></h2>
    <p class="hint">AI 답변이나 리포트 문장을 넣으면 숫자·판단 표현을 찾아 종류별로 표시합니다. 슬롯 예: <code>{{fact:005930:2025:revenue}}</code>, <code>{{calc:pct(새ID,기준ID)}}</code>, <code>{{cmp:ID1,ID2}}</code></p>
    <textarea id="ckText" style="min-height:130px"></textarea>
    <div style="display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap">
      <select id="ckMode"><option value="research">연구 모드 (표시만)</option><option value="conservative">보수 모드 (문장 보류)</option></select>
      <select id="ckRun">${runOpt}<option value="">저장 공식 원문 전체</option></select>
      <button id="ckSample">예시 문장</button><button id="ckGo" class="primary">검사</button></div>
    <div id="ckOut"></div>`;
  $('#ckSample').onclick = () => { $('#ckText').value = CHECK_SAMPLE; };
  $('#ckGo').onclick = runChecker;
  $('#dlg').showModal();
}
async function runChecker(){
  const out = $('#ckOut'); out.innerHTML = '<p class="mute">검사 중…</p>';
  try {
    const r = await api('/api/numeric/check', {method:'POST', body:{text:$('#ckText').value, mode:$('#ckMode').value, run_id:$('#ckRun').value || null}});
    const src = r.mode === 'research' ? r.rendered : r.display;
    let html = '';
    if (r.mode === 'research'){
      let pos = 0;
      for (const sp of r.spans){ if (sp.start < pos) continue; const [lab, cls] = TIER_UI[sp.tier] || [sp.tier,''];
        html += esc(src.slice(pos, sp.start)) + `<mark class="${cls}" title="${esc(lab + ' · ' + sp.category + ' · ' + sp.detail)}">${esc(sp.tier === 'hidden' ? '[매매 의견 표현 숨김]' : src.slice(sp.start, sp.end))}</mark>`; pos = sp.end; }
      html += esc(src.slice(pos));
    } else html = esc(src);
    const cnt = Object.entries(r.counts).map(([k,v]) => `<span class="ck ${(TIER_UI[k]||['',''])[1]}">${(TIER_UI[k]||[k])[0]} ${v}</span>`).join(' ');
    out.innerHTML = `<p>${cnt}</p><div class="ckText">${html.replace(/\n/g,'<br>')}</div>
      ${r.held.length ? `<h3>보류된 문장 ${r.held.length}개</h3><ul>${r.held.map(h => `<li>${esc(h.text)} <span class="mute">— ${esc(h.reason)}</span></li>`).join('')}</ul>` : ''}
      <p class="hint">${esc(r.note)} 대조 근거: ${esc(r.facts_source)}</p>
      <details><summary>인식 목록 ${r.spans.length}개</summary><table><tr><th>표현</th><th>등급</th><th>범주</th><th>설명</th></tr>${r.spans.map(sp => `<tr><td>${esc(sp.text)}</td><td>${(TIER_UI[sp.tier]||[sp.tier])[0]}</td><td>${esc(sp.category)}</td><td>${esc(sp.detail)}</td></tr>`).join('')}</table></details>
      <details><summary>쓸 수 있는 사실 ID ${r.fact_ids.length}개</summary><p class="mono">${r.fact_ids.map(esc).join('<br>')}</p></details>`;
  } catch(e){ out.innerHTML = `<p class="warn">검사 실패: ${esc(e.message)}</p>`; }
}

/* ---------------- boot ---------------- */
async function boot(){
  await api('/api/health');
  S.reg = await api('/api/registry'); S.reg.nodes.forEach(n => S.specs[n.id] = n);
  S.doc = blankDoc(); S.persona = loadPersona();
  renderLibrary(); renderPersp(); setupCanvas(); applyView();
  $('#libSearch').oninput = renderLibrary;
  $('#bPlan').onclick = placePlan; $('#bExample').onclick = openExamplePicker; $('#bExample2').onclick = openExamplePicker; $('#bNew').onclick = () => { if (S.dirty && !confirm('저장하지 않은 변경이 있습니다. 새로 만들까요?')) return;
    S.doc = blankDoc(); S.example = null; S.wfId = null; S.wfVersion = null; S.history = []; S.run = null; S.runId = null; S.issues = []; stopPoll(); renderRunbar(); renderIssues(); setHash(); renderAll(); };
  $('#bSave').onclick = () => save(); $('#bOpen').onclick = openDialog; $('#bValidate').onclick = () => doValidate(false);
  $('#bRun').onclick = run; $('#bAgent').onclick = runAgent; $('#bDocs').onclick = openDocs; $('#bMap').onclick = openEvidenceMap; $('#bCheck').onclick = openChecker; $('#bBroker').onclick = () => { S.bTab = S.bTab || 'compare'; openBroker(); }; $('#bCancel').onclick = cancel;
  $('#zIn').onclick = () => zoom(1.2); $('#zOut').onclick = () => zoom(1/1.2); $('#zFit').onclick = fit; $('#bLayout').onclick = autoLayout; $('#bDelEdge').onclick = deleteSelected;
  $('#wfName').oninput = () => { S.doc.name = $('#wfName').value; S.dirty = true; renderHeader(); };
  $('#cutoff').oninput = () => { S.doc.cutoff = $('#cutoff').value.trim(); touch(); };
  window.addEventListener('beforeunload', e => { if (S.dirty){ e.preventDefault(); e.returnValue = ''; } });
  window.addEventListener('resize', renderEdges);
  const h = Object.fromEntries(location.hash.slice(1).split('&').filter(Boolean).map(x => x.split('=')));
  if (h.wf){ try { await openWorkflow(h.wf, h.run); } catch(e){ toast('저장된 워크플로를 찾지 못했습니다.'); renderAll(); } }
  else if (h.run){                       // v0.15: 쉬운 화면의 답 → 그 답을 만든 근거 사슬 그대로
    try { const r = await api('/api/runs/' + h.run); S.doc = r.doc; S.doc.meta = r.doc.meta || {}; $('#wfName').value = S.doc.name; $('#cutoff').value = S.doc.cutoff || '';
      renderAll(); await loadRun(h.run); setTimeout(fit, 50); toast('쉬운 화면의 답을 만든 단계들입니다. 노드를 누르면 결과·근거를 볼 수 있습니다.'); }
    catch(e){ toast('이 실행을 찾지 못했습니다.'); renderAll(); }
  }
  else renderAll();
  if (h.map) openEvidenceMap();
}
boot().catch(e => { document.body.innerHTML = `<p style="padding:20px">시작 실패: ${esc(e.message)}</p>`; });
