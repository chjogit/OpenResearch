// Shared valuation-impact answer contract for P01-P07.
// It separates source facts, conditional interpretation and explicit assumptions.
const COMPANY_NAMES = {
  '005930': '삼성전자', '000660': 'SK하이닉스',
  samsung: '삼성전자', skhynix: 'SK하이닉스',
};

const GUIDANCE = {
  P01: {
    channel: '환율·금리 → 외화 표시 매출·원가, 순외화자산·부채, 이자비용 → 현금흐름·할인율',
    direction: '원화 약세가 헤지 후 순외화수입을 높이면 긍정 가능, 외화 비용·순부채가 더 크면 부정 가능. 금리 상승은 순변동금리 차입자에 불리하고 순금융자산에는 이자수익 증가가 될 수 있습니다.',
    conditions: ['통화별 매출·비용과 순노출', '헤지·결제 시점·해외생산 비중', '변동금리 부채와 재조달 조건'],
  },
  P02: {
    channel: '제품·사업부·지역별 매출과 비용 구조 → 성장·마진·재투자 → 미래 현금흐름',
    direction: '수요·가격·고마진 제품 비중의 지속 상승이 투자·운전자본 부담을 웃돌면 긍정 가능. 가격 압박·비용 상승·낮은 투자수익률은 부정 가능.',
    conditions: ['사업부별 영업이익·마진', '지역·제품 기준과 연결 범위 일치', '가격·물량·고객집중·지속성'],
  },
  P03: {
    channel: '기업·언론·투자자 감성의 지속적 변화 → 기대 성장·불확실성 인식 → 현금흐름 기대·요구수익률',
    direction: '긍정 신호가 지속 가능한 수요·실적으로 확인되면 긍정 가능. 일시적 관심에 그치면 EV 영향은 미확정이며 불확실성 확대는 요구수익률을 높일 수 있습니다.',
    conditions: ['대표성 있는 표본과 중복·출처 구분', '감성 변화가 실적·전망 변화와 연결되는지', '사건 시점·기간·반대 근거'],
  },
  P04: {
    channel: '가격·거래량 지표는 시장 가격과 기대의 움직임을 보여 주며, 그 자체로 기업의 내재가치를 정하지 않음',
    direction: '지표만으로 내재 기업가치의 상승·하락 방향을 판단하지 않습니다. 시장 가격 방향과 기업가치 방향을 별도로 둡니다.',
    conditions: ['가격 기준·기업행동·조정 여부', '공식 거래자료와 기간 확인', '내재가치 변화 주장은 실적·현금흐름 근거 별도 확보'],
  },
  P05: {
    channel: '지배구조·주주권·이사회 구조 → 자본배분·감독·위험통제 가능성 → 현금흐름 위험·요구수익률',
    direction: '실효성 있는 감독·자본배분이 위험을 낮추면 긍정 가능. 이해상충·통제 실패가 확인되면 부정 가능. 직함이나 명단만으로 어느 쪽도 확정하지 않습니다.',
    conditions: ['공식 역할·관계·의결권 범위', '실제 의사결정·성과 근거', '능력·의도·평판 추정 배제'],
  },
  P06: {
    channel: '전문영역별 확인 결과의 중복·불일치·기간 차이를 정리해 가치 판단의 근거와 공백을 드러냄',
    direction: '동일 기준으로 확인된 순현금흐름 효과의 방향을 조건별로 제시합니다. 상충 자료나 겹치는 효과가 남으면 순방향·총액은 미확정으로 둡니다.',
    conditions: ['같은 회사·기간·단위·연결 범위', '중복 근거의 한 번만 반영', '상충 자료는 결론 합산 대신 보류'],
  },
  P07: {
    channel: '정상화된 세후 자유현금흐름·성장·재투자·위험 → 할인 현금흐름과 기업가치',
    direction: '동일한 위험·할인율에서 지속 FCFF와 수익성 있는 성장이 커지면 EV에 긍정적. 현금흐름 악화·재투자 수익률 하락·위험/WACC 상승은 부정적입니다.',
    conditions: ['FCFF 계정 매핑·세율·운전자본·설비투자', 'WACC·장기성장률·예측기간', '순차입금·비영업자산·희석 주식수는 기업가치와 지분가치 구분 시 필요'],
  },
};

const numberText = (value) => value == null ? null : String(value);

function normalizeCompanies(question, companies = []) {
  const q = String(question || '');
  const mentioned = [];
  if (/삼성전자|Samsung Electronics/i.test(q)) mentioned.push({ id: '005930', name: '삼성전자' });
  if (/SK\s*하이닉스|SK\s*hynix/i.test(q)) mentioned.push({ id: '000660', name: 'SK하이닉스' });
  if (mentioned.length) return mentioned;
  return companies.map(c => ({ id: String(c.id || c.company || ''), name: c.name || COMPANY_NAMES[c.id] || COMPANY_NAMES[c.company] || '' }))
    .filter(c => c.name);
}

function p07MetricFacts(company) {
  const calc = company.calculation;
  if (!calc?.ready || !calc.years?.length) return [];
  const current = calc.years[0], prior = calc.years[1];
  const rows = [];
  if (current.cfo != null && prior?.cfo != null && calc.changes?.cfo != null) {
    rows.push({ label: '2024→2025 영업현금흐름 변화', value: numberText(calc.changes.cfo), unit: '백만원', status: 'fact', meaning: '원문 계정 연결을 검사한 과거 관측값이며 미래 현금흐름이나 기업가치 변화 자체는 아닙니다.' });
  }
  if (current.revenue != null) {
    const sensitivity = (BigInt(current.revenue) / 100n).toString();
    rows.push({ label: '2025 매출 기준 영업이익률 1%p 민감도', value: sensitivity, unit: '백만원/년, 세전 영업이익', status: 'assumption_calculation', meaning: '2025 매출이 같고 마진만 1%p 달라진다는 가정의 산술 민감도입니다. 실제 이익 변화나 기업가치가 아닙니다.' });
  }
  return rows;
}

function p01MetricFacts(company) {
  return [
    ['환율 민감도', company.fxScenario],
    ['금리 민감도', company.rateScenario],
  ].filter(([, value]) => value && value !== '미확보')
    .map(([label, value]) => ({ label, value: String(value), unit: '', status: 'disclosure_scenario', meaning: '기업 공시의 지정된 변동폭과 다른 변수 일정 가정에 따른 민감도입니다. 실현 이익·현금흐름이나 EV 변화가 아닙니다.' }));
}

export function buildEnterpriseValueImpact({ question, perspective = 'P02', kind = 'question', companies = [], facts = [] } = {}) {
  const targets = normalizeCompanies(question, companies);
  if (!targets.length) return { version: 'enterprise-value-impact-1', applicable: false, reason: '질문에 분석 대상 기업이 없어 기업별 가치 영향 섹션을 생략했습니다.' };
  const p = /^P0[1-7]$/.test(perspective) ? perspective : 'P02';
  const guide = GUIDANCE[p];
  const companyRows = targets.map(target => {
    const source = companies.find(c => String(c.id || c.company || '') === target.id || c.name === target.name) || {};
    const companyFacts = facts.filter(f => f.company === target.id || f.id === target.id || f.companyName === target.name)
      .map(f => ({ id: f.id, statement: f.statement || f.label || f.title || [f.fxScenario, f.rateScenario, f.hedge].filter(Boolean).join(' · '), status: f.status || 'source_fact' }))
      .filter(f => f.statement);
    const metricFacts = p === 'P07' ? p07MetricFacts(source) : p === 'P01' ? p01MetricFacts(source) : [];
    const cfoChange = source.calculation?.changes?.cfo;
    const direction = p === 'P04' ? '내재가치 방향 판단 불가'
      : p === 'P07' && cfoChange != null && BigInt(cfoChange) > 0n ? '현금흐름 경로상 잠재 긍정 · 기업가치 순효과 미확정'
      : p === 'P07' && cfoChange != null && BigInt(cfoChange) < 0n ? '현금흐름 경로상 잠재 부정 · 기업가치 순효과 미확정'
      : '조건부·순효과 미확정';
    return {
      company: target.id,
      name: target.name,
      direction,
      channel: guide.channel,
      directionConditions: guide.direction,
      interpretation: p === 'P04'
        ? '기술적 가격·거래량 신호는 시장 가격의 움직임을 설명할 수 있지만, 기업의 현금흐름 또는 내재 기업가치가 오르거나 내렸다는 근거로 단독 사용하지 않습니다.'
        : '질문에서 확인한 변화가 미래 현금흐름의 수준·성장·위험 또는 할인율에 지속적으로 전달되면 기업가치가 달라질 수 있습니다. 현재 근거만으로 상승·하락을 확정하지 않고 조건부 경로를 제시합니다.',
      conditions: guide.conditions,
      facts: companyFacts,
      impactScale: {
        status: metricFacts.length ? '관측·가정 민감도만 제시; 기업가치 금액 미산출' : '기업가치 규모 미산출',
        metrics: metricFacts,
        enterpriseValue: null,
        reason: '기업가치 금액을 계산할 정상화 FCFF, 예측기간, 할인율(WACC), 장기성장률의 검증된 입력이 한 세트로 확보되지 않았습니다. 이 값들을 임의로 채우지 않습니다.',
      },
      assumptions: ['미래에 지속될 효과를 말할 때는 전망기간·기준 시나리오·변수 범위·출처를 별도 표기합니다.', '가정 기반 계산은 확인된 과거 사실과 다른 색인/표로 구분하고, 가정값을 바꾸면 결과도 다시 계산합니다.'],
    };
  });
  return {
    version: 'enterprise-value-impact-1',
    applicable: true,
    perspective: p,
    kind,
    title: '기업가치에 미칠 수 있는 영향',
    classification: ['확인 사실', '해석', '가정·민감도 계산'],
    companies: companyRows,
    valuationRule: '기업가치(EV)는 영업자산 현금흐름의 가치이며, 주주가치(시가총액)는 순차입금 등 청구권을 반영한 값입니다. 주가의 단기 변동을 기업가치 변화와 동일시하지 않습니다.',
    missingInputs: ['정상화 FCFF와 예측기간', 'WACC와 장기성장률', 'EV에서 지분가치로 연결할 순차입금·비영업자산·희석주식수(질문 범위에 따라)'],
    meaningVerified: false,
  };
}

export const VALUE_GUIDANCE_BY_PERSPECTIVE = GUIDANCE;
