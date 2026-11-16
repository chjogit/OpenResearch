import {readFileSync} from 'node:fs';import {hash} from '../store.mjs';import {htmlTableProofs,bindRawTable} from '../p02/source-proof.mjs';
export const PERIOD={start:'2025-01-01',end:'2025-12-31'};
export const HELD=['지표 변화와 공시 민감도는 관측 시점·대상·가정이 달라 곱하여 실제 실적 기여로 계산하지 않습니다.','한국 기준금리는 기업의 실제 차입금리와 다릅니다. 해외 금리·만기·헤지·금융자산을 함께 확인해야 합니다.','삼성 환율 가정은 5%, SK는 10%입니다. 민감도 금액의 단순 순위 및 유불리·인과·미래 실적은 보류합니다.','2025년 고정 사례입니다. 최신 공시·정정 자동 탐색과 현재 시황 갱신은 수행하지 않습니다.'];
const root=new URL('../../sources/',import.meta.url),load=p=>readFileSync(new URL(p,root));
export function loadMacroCorpus(){
 const m=JSON.parse(load('p01/manifest.json')),{digest,...body}=m;if(hash(JSON.stringify(body))!==digest)throw Error('P01 manifest hash');
 for(const d of m.definitions){const bytes=load('p01/'+d.file);if(hash(bytes)!==d.rawHash||!JSON.parse(bytes).markdown.includes('noon buying rates in New York'))throw Error('환율 공식 정의 무결성 오류');}
 const sources=m.sources.map(s=>{
  if(s.kind==='indicator'){const b=load('p01/'+s.file);if(hash(b)!==s.rawHash)throw Error('지표 원문 해시 오류');return {...s,raw:JSON.parse(b)};}
  if(!['005930','000660'].includes(s.id)||s.period!=='2025-12-31'||s.unit!=='백만원'||s.scope!=='CFS'||s.document.company!==s.id||!s.document.title.includes('2025'))throw Error('회사·기간·단위·범위 오류');
  let b;try{b=load('agent/'+s.rawHash+'.html');}catch{b=load('seven/'+s.rawHash+'.html');}if(hash(b)!==s.rawHash||s.document.rawHash!==s.rawHash)throw Error('공시 바이트 해시 오류');
  const proofs=htmlTableProofs(b);for(const t of s.tables){if(t.company!==s.id||t.documentId!==s.document.id)throw Error('공시 회사 오류');const bound=bindRawTable(t,proofs);if(JSON.stringify(bound.rawTableProof)!==JSON.stringify(t.rawTableProof))throw Error('표 해시 오류');}
  return s;
 });return {...m,sources};
}
export function readIndicator(s,period=PERIOD){
 if(JSON.stringify(period)!==JSON.stringify(PERIOD))return {id:s.id,status:'held',reason:'지원 기간은 2025-01-01~2025-12-31입니다. 해당 기간의 공식 원자료를 별도로 확보해야 합니다.'};
 const text=s.raw.markdown;if(s.id==='fx'){
  if(!text.includes('South Korean won per U.S. dollar'))throw Error('환율 단위 오류');const months=['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  const points=[],missing=[];for(const r of text.matchAll(/\| (\d{1,2})-([A-Z]{3})-25 \| ([\d.]+|ND) \|/g)){const date='2025-'+String(months.indexOf(r[2])+1).padStart(2,'0')+'-'+r[1].padStart(2,'0');if(r[3]==='ND')missing.push(date);else points.push({date,value:Number(r[3]),raw:r[0]});}
  if(points.length<240||points.some(p=>!Number.isFinite(p.value)||p.value<=0)||points[0].date>'2025-01-03'||points.at(-1).date<'2025-12-30'||new Set(points.map(p=>p.date)).size!==points.length)throw Error('환율 기간·관측 오류');
  const first=points[0],last=points.at(-1),delta=Number((last.value-first.value).toFixed(4));return {id:s.id,status:'calculation_confirmed',title:s.title,unit:'원/USD',frequency:'일별 · 뉴욕 정오 매입률 · 한국 종가 아님',first,last,delta,percent:Number((delta/first.value*100).toFixed(4)),average:Number((points.reduce((a,p)=>a+p.value,0)/points.length).toFixed(4)),count:points.length,missing,points,formula:'변화=마지막 유효관측−첫 유효관측; 변화율=변화/첫 관측×100; 평균=유효관측 합/개수. ND·주말 보간 없음',publishedAt:'2026-10-26 (확보한 H.10 판의 발표일; 개별 관측 발표일 아님)',observedPeriod:PERIOD,url:s.url,collectedAt:s.collectedAt,rawHash:s.rawHash};
 }
 if(s.id!=='rate'||!text.includes('(연 %)'))throw Error('한국은행 기준금리 단위 오류');
 const all=[...text.matchAll(/\| (\d{4}) \| (\d{2})월 (\d{2})일 \| ([\d.]+) \|/g)].map(r=>({date:`${r[1]}-${r[2]}-${r[3]}`,value:Number(r[4]),raw:r[0]})).sort((a,b)=>a.date.localeCompare(b.date));
 const prior=all.filter(p=>p.date<=period.start).at(-1),changes=all.filter(p=>p.date>period.start&&p.date<=period.end);if(!prior||!changes.length||all.filter(p=>p.date>period.end).length===0)throw Error('기준금리 유효기간 확인 불가');
 const first={...prior,effectiveOn:period.start},last={...changes.at(-1),effectiveOn:period.end};return {id:s.id,status:'calculation_confirmed',title:s.title,unit:'연 %',frequency:'변경일 기준 · 다음 변경일까지 유지',first,last,changes,delta:Number((last.value-first.value).toFixed(2)),deltaUnit:'%p',formula:'연말 유효금리−연초 유효금리. 전년도 마지막 변경을 이월; 일별 금리 평균 아님',publishedAt:'변경일별 공표 · 페이지 개별 갱신시각 미표시',observedPeriod:PERIOD,url:s.url,collectedAt:s.collectedAt,rawHash:s.rawHash};
}
export function companyEvidence(s){return {id:s.id,status:'source_confirmed',title:s.title,period:s.period,scope:s.scope,unit:s.unit,document:s.document,tables:s.tables,rawHash:s.rawHash,warning:'저장 HTML 셀·회사·기간·단위 대조. 위험과 민감도는 공시 가정에 한정; 실제 실적 영향 인증 아님'};}
export function validateMacroEvidence(e){
 if(e.tables){if(!['005930','000660'].includes(e.id)||e.period!=='2025-12-31'||e.scope!=='CFS'||e.unit!=='백만원'||e.document.company!==e.id)throw Error('공시 회사·기간·단위 불일치');for(const t of e.tables){if(t.company!==e.id||t.documentId!==e.document.id||hash(JSON.stringify(t.rows.map(r=>r.cells)))!==t.rawTableProof.matrixDigest)throw Error('표 셀 배열 무결성 오류');}}
 return true;
}
export function buildMacroAnswer(p){
 for(const e of p.evidence)validateMacroEvidence(e);
 const e=p.evidence,fx=e.find(x=>x.id==='fx'),rate=e.find(x=>x.id==='rate'),companies=e.filter(x=>x.tables);
 const indicators=[fx,rate].filter(Boolean),rows=[];
 for(const id of ['005930','000660']){const s=companies.find(x=>x.id===id),cell=(n,r,c)=>s?.tables.find(t=>t.locator.endsWith('표 '+n))?.rows[r]?.cells[c];
 rows.push({company:id,name:id==='005930'?'삼성전자':'SK하이닉스',status:s?'source_confirmed':'held',fx:s?(id==='005930'?cell(608,3,1):cell(80,16,5)):'관련 공시 미확보',rate:s?(id==='005930'?cell(608,3,2):cell(88,11,3)):'관련 공시 미확보',hedge:s?(id==='005930'?cell(608,4,1):cell(80,15,5)):'미확보',fxScenario:s?(id==='005930'?'환율 ±5%, USD 세전손익 ±435,059백만원':'환율 ±10%, USD 세전손익 ±1,210,371백만원'):'미확보',rateScenario:s?(id==='005930'?'금리 +1%p, 금융자산 +76,243 / 부채 −33,597 / 합계 +42,646백만원':'금리 +100bp, 향후 1년 세전순이익 −41,875백만원 (다른 변수 일정)'):'미확보'});
 }
 // Scenario descriptions are a narrow adapter, enabled only by exact original table cells.
 for(const row of rows)if(row.status==='source_confirmed'){const s=companies.find(e=>e.id===row.company),txt=JSON.stringify(s.tables);for(const token of row.company==='005930'?['435,059','76,243','33,597','42,646','5%','1%p']:['1,210,371','41,875','10%','100bp'])if(!txt.includes(token))throw Error('민감도 출력의 원문 수치·가정 불일치');if(!row.fx||!row.rate||!row.hedge)throw Error('기업 위험 원문 위치 오류');}
 const summary=[];if(fx?.first)summary.push(`2025년 원·달러는 ${fx.first.date} ${fx.first.value.toLocaleString('ko-KR')}원에서 ${fx.last.date} ${fx.last.value.toLocaleString('ko-KR')}원으로 ${Math.abs(fx.delta).toFixed(2)}원 ${fx.delta<0?'하락':'상승'}했습니다. 첫·마지막 유효 일별 관측 비교입니다.`);if(rate?.first)summary.push(`한국은행 기준금리는 연초 ${rate.first.value.toFixed(2)}%에서 연말 ${rate.last.value.toFixed(2)}%로 ${Math.abs(rate.delta).toFixed(2)}%p ${rate.delta<0?'하락':'상승'}했습니다.`);if(companies.length)summary.push('두 기업의 외화 금융자산·부채와 변동금리 노출은 위험관리·헤지 및 민감도 가정을 함께 읽어야 합니다. 위 지표 변화만으로 이익 증가나 감소를 확정할 수 없습니다.');
 return {version:'p01-macro-answer-1',summary,indicators,companies:rows,held:[...HELD,...p.gaps],ready:['fx','rate','005930','000660'].every(id=>e.some(s=>s.id===id&&s.status!=='held')),assurance:{scope:'원문·셀 일치와 코드 산식',meaningVerified:false,approved:false,perspectives:['P01','P02','P03','P04','P05','P06','P07'],adapter:'p01-fixed-2025-macro'}};
}
