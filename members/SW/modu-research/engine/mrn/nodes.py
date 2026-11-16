"""Node handlers. Each returns Result(status, reason, payload|None).

Statuses: succeeded | partial | held | not_connected | failed (cancelled/interrupted are set by the engine).
Empty data is never turned into 0, neutral or "no issue".
"""
import re
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta as _td
from decimal import Decimal, localcontext
D = Decimal
from pydantic import ValidationError
from .specs import SPECS, COMPANIES, FACT_METRICS, KINDS
from .util import digest, instant, Integrity, KST
from .official import load_corpus, run_script
from . import valuation_core as vc

CORPUS_EARLIEST = '2026-11-02T00:00:00+09:00'


@dataclass
class Result:
    status: str
    reason: str = ''
    payload: dict | None = None
    error_code: str | None = None
    notes: list = field(default_factory=list)


def _one(inputs, port):
    items = inputs.get(port) or []
    return items[0] if items else None


def _check_packet(pkt, expected_type):
    if pkt['header']['type'] != expected_type:
        raise Integrity(f"입력 자료형이 {expected_type}이 아닙니다 ({pkt['header']['type']}).")
    if digest(pkt['payload']) != pkt['header']['payload_digest']:
        raise Integrity(f"{pkt['header']['produced_by']['node_id']} 출력의 해시가 저장 당시와 다릅니다. 변조 또는 손상 가능성이 있어 사용하지 않습니다.")


# ---------------------------------------------------------------- T01
def t01(node, inputs, ctx):
    cutoff = ctx.cutoff
    at = instant(cutoff)
    if at < instant(CORPUS_EARLIEST):
        return Result('held', '이 저장 자료판은 2026-11-02 이후 기준시점에서만 씁니다. 과거 시점 재생용 자료가 아닙니다.', error_code='cutoff_before_corpus')
    if at > datetime.now(timezone.utc):
        return Result('held', '미래 기준시점은 쓸 수 없습니다.', error_code='future_cutoff')
    corpus = load_corpus(ctx)
    docs = [d for c in corpus['companies'] for d in c['documents']]
    return Result('succeeded', f'공식 원문 {len(docs)}건 해시·표 대조 통과. 최신·정정 공시 자동 탐색은 하지 않았습니다.',
                  {**corpus, 'documents': docs, 'cutoff': cutoff,
                   'notice': '저장된 공식 원문을 실행마다 다시 대조한 결과입니다. 원문 이후의 정정·최신 공시는 반영하지 않습니다.'})


# ---------------------------------------------------------------- N01
def _fact(company, doc, year_row, metric):
    raw = year_row['inputs'].get(metric)
    if raw is None:
        return None
    proof = raw.get('rawTableProof') or {}
    return {
        'fact_id': f"{company['company']}:{raw['year']}:{metric}",
        'kind': 'fact_official', 'company': company['company'], 'company_name': company['name'],
        'metric': metric, 'metric_label': FACT_METRICS.get(metric, metric),
        'period': raw['year'], 'period_type': raw.get('periodType'),
        'period_start': raw.get('periodStart'), 'period_end': raw.get('periodEnd'),
        'value': raw['value'], 'source_value': raw.get('sourceValue'), 'unit': raw.get('unit'),
        'currency': raw.get('currency'), 'scope': raw.get('scope'), 'status': 'source_confirmed',
        'source': {'doc_id': doc['id'], 'rcept_no': doc['rcpNo'], 'title': doc['title'], 'url': doc['url'],
                   'landing_url': doc['landingUrl'], 'filed_at': doc['publishedDate'], 'doc_raw_hash': doc['rawHash'],
                   'table_id': raw.get('tableId'), 'row': raw.get('row'), 'column': raw.get('column'),
                   'row_label': raw.get('label'), 'table_raw_hash': proof.get('rawHash'), 'matrix_digest': proof.get('matrixDigest'),
                   'page': None},
    }


DERIVED = {
    'operatingMargin': ('영업이익률', '영업이익 / 매출 × 100', ['operatingProfit', 'revenue'], '%'),
    'cfoMargin': ('CFO/매출', 'CFO / 매출 × 100', ['cfo', 'revenue'], '%'),
    'cashRemainder': ('CFO − 유형·무형 취득 지출 (FCFF 아님)', 'CFO − 취득 지출', ['cfo', 'ppeAcquisition', 'intangibleAcquisition'], '백만원'),
}


def _mn(amount):
    try:
        with localcontext() as c:
            c.prec = 40
            v = Decimal(str(amount)) / Decimal(1000000)
        return format(v.normalize(), 'f') if v == v.to_integral_value() else format(v.quantize(Decimal('0.001')), 'f')
    except Exception:
        return None


def _api_facts(fp, years, metrics, facts, derived, missing):
    """T11(공시 API 재무)을 N01 사실 형식으로. kind는 공식 공시값이지만 원문 셀 대조가 아님을 status로 구분한다."""
    code, name = fp['company'], fp['name']
    by = {(f['year'], f['metric']): f for f in fp['facts']}
    have = sorted({f['year'] for f in fp['facts']})
    for y in years:
        if not any(k[0] == y for k in by):
            missing += [{'company': code, 'period': y, 'metric': m, 'reason': f'기준시점 전에 접수된 {y}년 사업보고서 재무가 사본에 없음' + (f' (있는 연도: {have})' if have else '')} for m in metrics]
            continue
        vals = {}
        for m in metrics:
            f = by.get((y, m))
            if f is None:
                missing.append({'company': code, 'period': y, 'metric': m, 'reason': '공시 재무에 이 계정이 없음(업종에 따라 매출·영업이익 계정이 없을 수 있음)'})
                continue
            v = _mn(f['amount'])
            vals[m] = v
            facts.append({'fact_id': f'{code}:{y}:{m}', 'kind': 'fact_official', 'company': code, 'company_name': name,
                          'metric': m, 'metric_label': FACT_METRICS.get(m, m), 'period': y, 'period_type': 'annual',
                          'period_start': None, 'period_end': f.get('period_end'), 'value': v, 'source_value': f['amount'], 'unit': '백만원',
                          'currency': f.get('currency'), 'scope': '연결' if f.get('fs_div') == 'CFS' else '별도', 'status': 'api_reported',
                          'source': {'doc_id': None, 'rcept_no': f['rcept_no'], 'title': f'{y}년 사업보고서 (DART 공시 API 값)',
                                     'url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={f['rcept_no']}", 'landing_url': None,
                                     'filed_at': f['filed_at'], 'account_id': f['account_id'], 'account_nm': f.get('account_nm'),
                                     'source_grade': 'official:dart_api', 'snapshot': fp['source']['financials']['snapshot'],
                                     'file_sha256': fp['source']['financials']['sha256'], 'page': None,
                                     'verification': '원문 표 셀 대조 아님 — 공시 API 값 (기준 기업 68/68 일치 확인)'}})
        for key, (label, formula, needs, unit) in DERIVED.items():
            if all(vals.get(n) is not None for n in needs):
                try:
                    a = [Decimal(vals[n]) for n in needs]
                    if key == 'cashRemainder':
                        v = a[0] - a[1] - a[2]
                    elif a[1] == 0:
                        continue
                    else:
                        v = a[0] / a[1] * 100
                    derived.append({'id': f'{code}:{y}:{key}', 'kind': 'derived', 'company': code, 'period': y, 'label': label,
                                    'value': format(v.quantize(Decimal('0.01')), 'f'), 'unit': unit, 'formula': formula,
                                    'inputs': [f'{code}:{y}:{n}' for n in needs]})
                except Exception:
                    pass


def n01(node, inputs, ctx):
    pkt = _one(inputs, 'corpus')
    fps = inputs.get('filings') or []
    if not pkt and not fps:
        return Result('held', '입력이 없습니다. 두 기준 기업은 T01(공식 원문), 다른 회사는 T11(회사 공시 재무)을 이어 주세요.', error_code='no_input')
    cfg = node['config']
    years = [int(y) for y in (cfg.get('years') or [2024, 2025])]
    metrics = cfg.get('metrics') or ['revenue', 'operatingProfit', 'cfo']
    facts, derived, missing = [], [], []
    api_cos = []
    for fpk in fps:
        _check_packet(fpk, 'CompanyFilings')
        fp = fpk['payload']
        api_cos.append(fp['company'])
        ctx.step(f"{fp['name']} 공시 재무 확인")
        _api_facts(fp, years, metrics, facts, derived, missing)
    if not pkt:
        status = 'partial' if missing and facts else ('held' if missing and not facts else 'succeeded')
        return Result(status, f'공시 API 재무 {len(facts)}건' + (f', 미확보 {len(missing)}건' if missing else '') +
                      '. 원문 표 셀 대조 값이 아니며(공시 API), 증감의 원인·지속성은 판단하지 않았습니다.',
                      {'facts': facts, 'derived': derived, 'missing': missing, 'corpus_digest': None, 'manifest_digest': None,
                       'formulas': [], 'limits': ['다른 회사 재무는 DART 공시 API 값입니다. 원문 표 셀과 직접 대조하지 않았습니다.']})
    _check_packet(pkt, 'OfficialCorpus')
    corpus = pkt['payload']
    companies = [c for c in (cfg.get('companies') or list(COMPANIES)) if c not in api_cos]
    ctx.step(f'{len(companies)}개 기업 × {len(years)}개 연도 × {len(metrics)}개 항목 셀 확인')
    for code in companies:
        comp = next((c for c in corpus['companies'] if c['company'] == code), None)
        if comp is None:
            missing += [{'company': code, 'period': y, 'metric': m, 'reason': '저장 원문에 해당 기업 없음'} for y in years for m in metrics]
            continue
        doc = comp['documents'][0]
        for y in years:
            row = next((r for r in comp['years'] if r['year'] == y), None)
            if row is None:
                missing += [{'company': code, 'period': y, 'metric': m, 'reason': '저장 원문에 해당 연도 없음'} for m in metrics]
                continue
            for m in metrics:
                f = _fact(comp, doc, row, m)
                if f is None:
                    missing.append({'company': code, 'period': y, 'metric': m, 'reason': '원문 표에서 해당 셀을 확인하지 못함'})
                else:
                    facts.append(f)
            for key, (label, formula, needs, unit) in DERIVED.items():
                if key in row:
                    derived.append({'id': f'{code}:{y}:{key}', 'kind': 'derived', 'company': code, 'period': y, 'label': label,
                                    'value': row[key], 'unit': unit, 'formula': formula,
                                    'inputs': [f'{code}:{y}:{n}' for n in needs]})
    status = 'partial' if missing and facts else ('held' if missing else 'succeeded')
    reason = (f'확인 {len(facts)}건' + (f', 미확보 {len(missing)}건' if missing else '') +
              '. 금액은 원문 셀 값 그대로이며' + (' (T11로 들어온 회사는 공시 API 값)' if api_cos else '') + ', 증감의 원인·지속성은 판단하지 않았습니다.')
    return Result(status, reason, {'facts': facts, 'derived': derived, 'missing': missing,
                                   'corpus_digest': pkt['header']['payload_digest'], 'manifest_digest': corpus['manifest_digest'],
                                   'formulas': corpus['companies'][0]['formulas'] if corpus['companies'] else [],
                                   'limits': corpus.get('limits', [])})


# ---------------------------------------------------------------- N05 / N06
def _exposure_from_filings(fp):
    """T11 공시 민감도 표(규칙 추출)를 N05 노출 형식으로. 가장 최근 사업연도, 미국 달러·금리만 계산용 구조로 만든다."""
    E = fp['exposures']
    if not E:
        return None
    y = max(int(e['fiscal_year']) for e in E)
    E = [e for e in E if int(e['fiscal_year']) == y]
    def pick(metric, cur=None):
        rs = [e for e in E if e['metric'] == metric and (cur is None or e.get('currency') == cur) and e.get('value') not in (None, '')]
        return max(rs, key=lambda e: abs(_f(e['value']) or 0)) if rs else None
    fxr = pick('fx_sens', 'USD') or pick('fx_sens')
    irr = pick('ir_sens') or pick('ir_sens_liab')
    out = {'company': fp['company'], 'name': fp['name'], 'status': 'api_extracted', 'fiscal_year': y, 'kind': 'fact_official',
           'hedge': '헤지회계 적용 표시 있음' if pick('fx_hedge_acct') else None, 'fx_struct': None, 'rate_struct': None,
           'currencies': sorted({e.get('currency') for e in E if e['metric'] == 'fx_sens' and e.get('currency')})}
    if fxr and _f(fxr.get('change_pct')):
        mn = _f(fxr['value']) / 1e6
        out['fx_struct'] = {'shock': _f(fxr['change_pct']), 'impact_mn': mn, 'currency': fxr.get('currency'), 'basis': fxr.get('basis'), 'rcept_no': fxr['rcept_no'],
                            'evidence': (fxr.get('evidence') or '')[:300], 'sign_note': '표의 값을 「외화 강세(원화 약세)일 때 영향」으로 가정 — 회사마다 표 형식이 달라 원문 확인 필요'}
        out['fx_scenario'] = f"{fxr.get('currency') or '외화'} {_f(fxr['change_pct']):g}% 변동 시 {fxr.get('basis') or '손익'} {mn:+,.0f}백만원 (사업보고서 {y}, 표 규칙 추출)"
    else:
        out['fx_scenario'] = '환율 민감도 숫자를 표에서 읽지 못함'
    if irr and _f(irr.get('change_pct')):
        sh = _f(irr['change_pct'])
        sh = sh / 100 if sh >= 10 else sh                # 100bp 형식이면 %p로
        mn = _f(irr['value']) / 1e6
        out['rate_struct'] = {'shock': sh, 'impact_mn': mn, 'basis': irr.get('basis'), 'rcept_no': irr['rcept_no'], 'evidence': (irr.get('evidence') or '')[:300],
                              'sign_note': '표의 값을 「금리 상승일 때 영향」으로 가정 — 원문 확인 필요'}
        out['rate_scenario'] = f"금리 {sh:g}%p 변동 시 {irr.get('basis') or '손익'} {mn:+,.0f}백만원 (사업보고서 {y}, 표 규칙 추출)"
    else:
        out['rate_scenario'] = '금리 민감도 숫자를 표에서 읽지 못함'
    sh = pick('export_share')
    if sh:
        out['export_share'] = f"{_f(sh['value']):.1f}%"
    return out


# ---------------------------------------------------------------- v0.37.7 N05 노출 등급 (철현 N05 이식, 규칙 grade-v1)
GRADE_RULE = 'exposure-grade-v1'
FX_HIGH, FX_MID = 10.0, 3.0            # 환율 10% 변동 시 손익 ÷ 영업이익(%)
EXP_HIGH, EXP_MID = 60.0, 30.0         # 수출 비중(%)
DEBT_UP, DEBT_DOWN = 200.0, 50.0       # 부채비율(%): 금리 노출을 한 단계 높여/낮춰 볼 조건
_FIN_SECTORS = ('은행', '보험', '증권')
_FIN_NAME = re.compile(r'금융|카드|캐피탈|뱅크|페이|생명|화재|손해보험|증권|^신한지주$')     # PM 판단: 기타금융 중 금융회사만(일반 지주사는 포함하지 않음)


def _grade3(x, hi, mid):
    return '높음' if x >= hi else '중간' if x >= mid else '낮음'


def _is_financial(fp):
    s = fp.get('krx_sector') or ''
    return s in _FIN_SECTORS or (s == '기타금융' and bool(_FIN_NAME.search(fp.get('name') or '')))


def _exposure_grade(fp):
    """T11 → (findings, held, table). 회사가 공시한 숫자만 쓴다. 등급 이름은 규칙에 따른 분류이며 평가가 아니다."""
    F, H, rows = [], [], []
    E = fp.get('exposures') or []
    name = fp['name']
    if _is_financial(fp):
        H.append(f'{name}: 금융업은 환율·수출·금리 노출 등급 규칙을 쓰지 않습니다(민감도 표의 성격이 일반 기업과 달라 같은 기준으로 나누지 않음)'); return F, H, None
    if not E:
        H.append(f'{name} 노출 등급: 사업보고서 민감도 표를 사본에서 찾지 못해 보류'); return F, H, None
    y = max(int(e['fiscal_year']) for e in E)
    E = [e for e in E if int(e['fiscal_year']) == y]
    rcept = next((e['rcept_no'] for e in E if e.get('rcept_no')), None)
    url = f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept}' if rcept else None
    src = {'title': f'사업보고서 ({y}.12)', 'url': url, 'rcept_no': rcept} if url else None
    facts = {(f['year'], f['metric']): _f(f['amount']) for f in fp.get('facts') or []}
    curs = {f.get('currency') for f in fp.get('facts') or [] if f['year'] == y and f['metric'] in ('operatingProfit', 'liabilities', 'equity')}
    if curs - {'KRW', None}:
        H.append(f"{name} 노출 등급: {y}년 재무 숫자가 원화가 아니어서({', '.join(sorted(c for c in curs if c))}) 원화 민감도와 나눌 수 없어 보류"); return F, H, None
    op = facts.get((y, 'operatingProfit'))
    # 최근 4개 분기 영업이익(기준시점까지 공시된 단독 분기, 연속일 때만)
    qa = sorted(((q['fiscal_year'], q['quarter']), _f(q['value_mn'])) for q in fp.get('quarter_actuals') or [] if q['metric'] == 'operatingProfit')
    ttm, ttm_lab = None, ''
    if len(qa) >= 4:
        last4 = qa[-4:]; idx = [a * 4 + b for (a, b), _ in last4]
        if idx == list(range(idx[0], idx[0] + 4)) and all(v is not None for _, v in last4):
            ttm = sum(v for _, v in last4) * 1e6
            ttm_lab = f"{last4[0][0][0]}년 {last4[0][0][1]}분기~{last4[-1][0][0]}년 {last4[-1][0][1]}분기"
    # ① 환율: 통화별 한 줄(손익 기준 우선) → 10% 변동으로 환산
    by_cur = {}
    for e in E:
        if e['metric'] != 'fx_sens' or _f(e.get('value')) is None or not _f(e.get('change_pct')):
            continue
        c = e.get('currency') or '외화'
        k = (0 if '손익' in (e.get('basis') or '') else 1, -abs(_f(e['value'])))
        if c not in by_cur or k < by_cur[c][0]:
            by_cur[c] = (k, e)
    if not by_cur:
        H.append(f'{name} 환율 노출 등급: 환율 민감도 숫자를 표에서 읽지 못해 보류')
    elif op is None or op <= 0:
        H.append(f"{name} 환율 노출 등급: {y}년 영업이익이 {'없어' if op is None else '0 이하라'} 비율을 내지 않음 — 보류")
    else:
        ten = {c: _f(e['value']) * 10 / _f(e['change_pct']) for c, (_, e) in by_cur.items()}
        base_c = 'USD' if 'USD' in ten else max(ten, key=lambda c: abs(ten[c]))
        ratio = abs(ten[base_c]) / op * 100
        g = _grade3(ratio, FX_HIGH, FX_MID)
        e0 = by_cur[base_c][1]
        F.append({'name': f'환율 10% 변동 시 손익 ÷ 영업이익 ({base_c}, {y}년)', 'claim': f"{ratio:.2f}% — {_eok(abs(ten[base_c]))} ÷ 영업이익 {_eok(op)}",
                  'value': round(ratio, 4), 'unit': '%', 'kind': 'derived',
                  'formula': f"공시 「{base_c} {_f(e0['change_pct']):g}% 변동 시 {e0.get('basis') or '손익'} {_f(e0['value']) / 1e8:,.2f}억원」 × (10 ÷ {_f(e0['change_pct']):g}) ÷ {y}년 연결 영업이익 × 100. 부호(이익·손실 방향)는 빼고 크기만", 'source': src})
        if ttm and ttm > 0:
            F.append({'name': f'같은 값 ÷ 최근 4개 분기 영업이익 ({base_c})', 'claim': f"{abs(ten[base_c]) / ttm * 100:.2f}% — 최근 4개 분기({ttm_lab}) 영업이익 {_eok(ttm)}",
                      'value': round(abs(ten[base_c]) / ttm * 100, 4), 'unit': '%', 'kind': 'derived', 'formula': '환율 10% 변동 시 손익 ÷ 기준시점까지 공시된 연속 4개 분기 단독 영업이익 합 × 100 (참고값, 등급에는 쓰지 않음)'})
        F.append({'name': '환율 노출 (규칙 분류)', 'claim': f"「{g}」 — 영업이익 대비 {ratio:.2f}% (기준: {FX_HIGH:g}% 이상 높음 · {FX_MID:g}% 이상 중간 · 그 아래 낮음)",
                  'kind': 'rule_derived', 'formula': f'{GRADE_RULE}: 사업보고서의 환율 민감도를 10% 변동으로 환산해 같은 해 영업이익으로 나눈 비율로 나눔. 회사에 대한 평가가 아님'})
        rows.append(['환율', f'{ratio:.2f}% (영업이익 대비)', f'{FX_HIGH:g}% 이상 높음 · {FX_MID:g}% 이상 중간', g])
        if len(ten) > 1:
            tot = abs(sum(ten.values())) / op * 100; tg = _grade3(tot, FX_HIGH, FX_MID)
            rows.append(['환율 · 참고', f"{tot:.2f}% (모든 통화 합: {', '.join(sorted(ten))})", '모든 외화가 원화 대비 같은 방향·같은 폭으로 움직인다는 가정', f"등급에 쓰지 않음 (이 가정이면 「{tg}」)"])
    # ② 수출·경기: 공시 수출 비중
    xs = [e for e in E if e['metric'] == 'export_share' and _f(e.get('value')) is not None]
    if xs:
        v = _f(xs[0]['value']); g = _grade3(v, EXP_HIGH, EXP_MID)
        F.append({'name': '수출·경기 노출 (규칙 분류)', 'claim': f"「{g}」 — 공시 수출 비중 {v:.2f}% (기준: {EXP_HIGH:g}% 이상 높음 · {EXP_MID:g}% 이상 중간 · 그 아래 낮음)",
                  'value': round(v, 4), 'unit': '%', 'kind': 'rule_derived', 'formula': f'{GRADE_RULE}: 사업보고서 매출 표에서 규칙으로 읽은 수출(해외) 비중', 'source': src})
        rows.append(['수출·경기', f'수출 비중 {v:.2f}%', f'{EXP_HIGH:g}% 이상 높음 · {EXP_MID:g}% 이상 중간', g])
    else:
        H.append(f'{name} 수출·경기 노출 등급: 공시 수출 비중을 표에서 읽지 못해 보류')
    # ③ 금리: 부채비율은 「한 단계 높여/낮춰 볼 조건」만 — 출발점(업종 기본값)이 가정이라 등급 자체는 내지 않음
    li, eq = facts.get((y, 'liabilities')), facts.get((y, 'equity'))
    if li is not None and eq and eq > 0:
        d = li / eq * 100
        cond = '한 단계 높여 볼 조건' if d >= DEBT_UP else '한 단계 낮춰 볼 조건' if d <= DEBT_DOWN else '조정 없음'
        F.append({'name': f'부채비율 ({y}년 말)', 'claim': f"{d:.2f}% → 금리 노출 「{cond}」 (기준: {DEBT_UP:g}% 이상 높여 봄 · {DEBT_DOWN:g}% 이하 낮춰 봄)", 'value': round(d, 4), 'unit': '%',
                  'kind': 'rule_derived', 'formula': f'{GRADE_RULE}: 연결 부채총계 ÷ 자본총계 × 100. 금리 노출의 출발점(업종 기본값)은 가정이라 쓰지 않고 조정 방향만 보임', 'source': src})
        rows.append(['금리', f'부채비율 {d:.2f}%', f'{DEBT_UP:g}% 이상 높여 봄 · {DEBT_DOWN:g}% 이하 낮춰 봄', cond])
    else:
        H.append(f'{name} 금리 노출: {y}년 부채·자본을 읽지 못해 보류')
    H.append('업종 기본값(예: 반도체는 환율 높음)은 가정이라 등급에 쓰지 않음 · 주가와의 상관으로 등급을 올리는 규칙도 쓰지 않습니다')
    tab = {'title': f'{name} 거시 노출 — 규칙 분류 ({y}년 사업보고서 기준)', 'cols': ['변수', '근거 값', '기준', '규칙 분류'], 'rows': rows,
           'hint': '등급 이름은 정해 둔 기준값으로 나눈 분류일 뿐, 회사가 좋다 나쁘다는 뜻이 아니에요. 업종 기본값 같은 가정은 쓰지 않았어요.'} if rows else None
    return F, H, tab


def n05(node, inputs, ctx):
    pkt = _one(inputs, 'corpus')
    fps = inputs.get('filings') or []
    if not pkt and not fps:
        return Result('held', '입력이 없습니다. 두 기준 기업은 T01, 다른 회사는 T11을 이어 주세요.', error_code='no_input')
    extra, held_api = [], []
    gF, gH, gT = [], [], []                                  # v0.37.7 노출 등급
    for fpk in fps:
        _check_packet(fpk, 'CompanyFilings')
        a, b, c = _exposure_grade(fpk['payload']); gF += a; gH += b; gT += [c] if c else []
        x = _exposure_from_filings(fpk['payload'])
        if x:
            extra.append(x)
        else:
            held_api.append(f"{fpk['payload']['name']}: 공시 민감도 표를 사본에서 찾지 못함")
    if not pkt:
        if not extra:
            return Result('held', '; '.join(held_api) or '공시 민감도 없음', error_code='no_rows')
        return Result('succeeded', f"{len(extra)}개 회사가 사업보고서에 공시한 환율·금리 민감도(표 규칙 추출)를 정리했습니다. 영향 크기는 추정하지 않았습니다.",
                      {'indicators': [], 'exposures': extra, 'findings': [{'kind': 'fact_official', 'claim': f"{e['name']} — 환율: {e['fx_scenario']} / 금리: {e['rate_scenario']}"} for e in extra] + gF,
                       'summary': ['거시 지표 변화는 N06에 T10을 이어 보세요.'], 'held': held_api + gH, 'tables': gT, 'grade_rule': GRADE_RULE})
    _check_packet(pkt, 'OfficialCorpus')
    macro = pkt['payload']['macro']
    findings = []
    for ind in macro.get('indicators', []):
        findings.append({'kind': 'fact_official', 'claim': f"{ind['title']}: {ind['first']['date']} {ind['first']['value']} → {ind['last']['date']} {ind['last']['value']} ({ind['unit']})",
                         'evidence': {'first_raw': ind['first'].get('raw'), 'last_raw': ind['last'].get('raw'), 'frequency': ind.get('frequency')}})
        findings.append({'kind': 'derived', 'claim': f"{ind['title']} 변화 {ind.get('delta')}{ind.get('deltaUnit', '')}",
                         'formula': ind.get('formula') or '마지막 관측 − 첫 관측'})
    in_corpus = {c['company'] for c in macro.get('companies', [])}    # v0.37.7: 기준 기업은 T01 노출을 쓰고, T11은 등급 계산에만
    extra = [e for e in extra if e['company'] not in in_corpus]
    exposures = [{'company': c['company'], 'name': c['name'], 'status': c.get('status'), 'fx': c.get('fx'), 'rate': c.get('rate'),
                  'hedge': c.get('hedge'), 'fx_scenario': c.get('fxScenario'), 'rate_scenario': c.get('rateScenario'), 'kind': 'fact_official'}
                 for c in macro.get('companies', [])] + extra
    return Result('succeeded', '2025 지표 관측과 각 기업의 공시 노출 문장을 나란히 보였습니다. 지표 변화가 실적에 준 영향은 추정하지 않았습니다.',
                  {'indicators': macro.get('indicators', []), 'exposures': exposures, 'findings': findings + gF,
                   'summary': macro.get('summary', []), 'held': macro.get('held', []) + held_api + gH, 'tables': gT, 'grade_rule': GRADE_RULE})


# (n06 moved below — v0.12)

# ---------------------------------------------------------------- T03 assumptions
METHOD_MODELS = {'dcf': vc.DCF, 'ddm': vc.DDM, 'rim': vc.RIM, 'nav': vc.NAV}
UNITS = {'growth': '%', 'margin': '%', 'tax': '%', 'rate': '%', 'terminal_growth': '%'}


def check_assumptions(cfg, n02_cfg=None):
    """Return an error string or None. Used by pre-run validation and by T03."""
    method = cfg.get('method', 'dcf')
    model = dict(cfg.get('model') or {})
    if not model:
        return '방법별 가정(model)이 비어 있습니다.'
    model['method'] = method
    try:
        METHOD_MODELS[method].model_validate(model)
    except KeyError:
        return f'지원하지 않는 방법 {method}'
    except ValidationError as e:
        first = e.errors()[0]
        return f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}"
    for k, n in (('label', 1), ('share_basis', 10), ('assumptions_note', 10)):
        if len(str(cfg.get(k, '')).strip()) < n:
            return f'{k} 항목을 {n}자 이상 적어 주세요.'
    try:
        vc.positive(str(cfg.get('shares', '')), '희석 보통주 수', False)
        Decimal(str(cfg.get('shares')))
    except Exception:
        return '희석 보통주 수(shares)를 0보다 큰 숫자로 적어 주세요.'
    return None


def _flatten(prefix, obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f'{prefix}.{k}' if prefix else k, v, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj, 1):
            _flatten(f'{prefix}[{i}]', v, out)
    else:
        out.append((prefix, obj))


def t03(node, inputs, ctx):
    cfg = node['config']
    err = check_assumptions(cfg)
    if err:
        return Result('failed', err, error_code='assumption_invalid')
    kind = 'assumption_illustrative' if cfg.get('input_kind') == 'illustrative_assumptions' else 'assumption_user'
    model = dict(cfg['model'])
    model['method'] = cfg['method']
    flat = []
    _flatten('', {k: v for k, v in model.items() if k != 'method'}, flat)
    items = [{'key': k, 'value': v, 'unit': UNITS.get(k.split('.')[-1].split('[')[0], ''), 'kind': kind, 'origin_ref': f"{node['id']}:{k}"}
             for k, v in flat]
    items.append({'key': 'shares', 'value': str(cfg['shares']), 'unit': '주', 'kind': kind, 'origin_ref': f"{node['id']}:shares",
                  'rationale': cfg['share_basis']})
    return Result('succeeded', ('학습용 예시 가정입니다. 실제 기업가치 추정에 쓰지 마세요.' if kind == 'assumption_illustrative'
                                else '사람이 입력한 가정입니다. 타당성은 검증하지 않았습니다.'),
                  {'method': cfg['method'], 'label': cfg['label'], 'shares': str(cfg['shares']), 'share_basis': cfg['share_basis'],
                   'assumptions_note': cfg['assumptions_note'], 'input_kind': cfg.get('input_kind', 'user_assumptions'),
                   'model': model, 'items': items})


# ---------------------------------------------------------------- N02
REQUIRED_FACTS = {'dcf': ['revenue'], 'nav': ['assets', 'liabilities'], 'ddm': ['revenue'], 'rim': ['revenue']}
COMPARE = ('value', 'tableId', 'row', 'column')


def fresh_pack(company, year, ctx):
    """Re-run the source verifier now (not the T01 cache) and build the 4373 source pack."""
    ctx.step('N01 사실을 원문 검증기로 다시 대조 중')
    data = run_script('valuation.mjs', ctx)
    ctx.tool_call()
    source = next((c for c in data['companies'] if c['company'] == company), None)
    y = source and next((r for r in source['calculation']['years'] if r['year'] == year), None)
    if y is None:
        raise Integrity('원문 검증기에서 해당 기업·연도를 찾지 못했습니다.')
    doc = source['documents'][0]
    facts = {k: {**v, 'source_url': doc['url'], 'document_hash': doc['rawHash'], 'document_id': doc['id']} for k, v in y['inputs'].items()}
    pack = {'company': company, 'name': source['name'], 'base_year': year, 'facts': facts,
            'historical': {k: v for k, v in y.items() if k != 'inputs'},
            'document': {k: v for k, v in doc.items() if k not in ('tables', 'paragraphs', 'rawResponse')},
            'formulas': source['calculation']['formulas'], 'correction_status': '저장된 공시 판. 최신·정정 탐색 미실시',
            'scope': '연결 / KRW / 백만원', 'source_type': 'stored_official', 'earliest_supported_date': '2026-11-02'}
    return {**pack, 'digest': digest(pack)}


def reverify(facts_payload, company, year, pack):
    """Compare every N01 fact for (company, year) with the freshly verified source."""
    problems = []
    mine = [f for f in facts_payload['facts'] if f['company'] == company and f['period'] == year]
    for f in mine:
        src = pack['facts'].get(f['metric'])
        if src is None:
            problems.append(f"{f['fact_id']}: 원문 검증기에 해당 항목 없음")
            continue
        ours = {'value': f['value'], 'tableId': f['source']['table_id'], 'row': f['source']['row'], 'column': f['source']['column']}
        for k in COMPARE:
            if ours[k] != src.get(k):
                problems.append(f"{f['fact_id']}: {k} 불일치 (N01 {ours[k]} / 원문 {src.get(k)})")
        if f['source']['doc_raw_hash'] != src['document_hash']:
            problems.append(f"{f['fact_id']}: 문서 해시 불일치")
        if (src.get('rawTableProof') or {}).get('rawHash') != f['source']['table_raw_hash']:
            problems.append(f"{f['fact_id']}: 표 해시 불일치")
        if f['unit'] != src.get('unit') or f['scope'] != src.get('scope'):
            problems.append(f"{f['fact_id']}: 단위·범위 불일치")
    return mine, problems


def sensitivity(req, pack):
    m = req.model
    if m.method == 'nav':
        return [], 'NAV는 할인율·성장률 민감도가 없습니다.'
    cells = []
    steps = ['-1', '-0.5', '0', '0.5', '1']
    g_steps = ['0'] if (m.method == 'rim' and m.terminal_mode == 'zero') else steps
    for dr in steps:
        for dg in g_steps:
            r = vc.number(m.rate) + vc.number(dr)
            g = vc.number(m.terminal_growth) + vc.number(dg)
            cell = {'rate': vc.out(r), 'growth': vc.out(g), 'd_rate': dr, 'd_growth': dg}
            try:
                raw = req.model_dump()
                raw['model'].update(rate=vc.out(r), terminal_growth=vc.out(g))
                other = vc.ValuationRequest.model_validate(raw)
                cell['input_digest'] = digest(other.model_dump())
                v = vc.evaluate(other, pack)
                cell.update(status='calculated', per_share=v['per_share'], terminal_weight_pct=v['terminal_weight_pct'])
                if r - g < Decimal('2'):
                    cell['warning'] = '할인율−성장률 2%p 미만'
            except ValueError as e:
                cell.update(status='held', reason='허용범위 밖: ' + str(e).splitlines()[0][:120])
            cells.append(cell)
    note = '할인율 ±1%p·장기성장률 ±1%p (0.5%p 간격)의 조건부 계산입니다. 확률이나 신뢰구간이 아닙니다.'
    if m.method == 'dcf':
        note += ' 정상화 N+1년 FCFF는 고정합니다.'
    return cells, note


def n02(node, inputs, ctx):
    cfg = node['config']
    company = cfg.get('company', '005930')
    year = int(cfg.get('base_year', 2025))
    fp, ap = _one(inputs, 'facts'), _one(inputs, 'assumptions')
    _check_packet(fp, 'FactPackage')
    _check_packet(ap, 'AssumptionSet')
    a = ap['payload']
    method = a['method']
    have = {f['metric'] for f in fp['payload']['facts'] if f['company'] == company and f['period'] == year}
    lacking = [m for m in REQUIRED_FACTS[method] if m not in have]
    if lacking:
        return Result('held', f"N01 출력에 {company} {year} {', '.join(FACT_METRICS[m] for m in lacking)} 사실이 없습니다. N01 항목 설정에 추가하세요.",
                      error_code='facts_missing')
    forecasts = _one(inputs, 'forecasts')
    forecast_note = '외부 전망 입력 미연결'
    fc_list = []
    if forecasts is not None:
        _check_packet(forecasts, 'BrokerForecastPackage')
        fc_list = forecasts['payload'].get('forecasts', [])
        bad = [f for f in fc_list if (f.get('review') or {}).get('state') != 'approved']
        if bad:
            return Result('held', f'승인되지 않은 외부 전망 {len(bad)}건이 들어왔습니다. 사람이 승인한 전망만 쓸 수 있습니다.', error_code='unapproved_forecast')
        if len({(f['broker'], f['report_date'], f['source']['sha256']) for f in fc_list}) > 1:
            return Result('held', '여러 보고서의 전망이 섞여 들어왔습니다. 한 보고서만 고르세요(전망을 조용히 합치지 않습니다).', error_code='mixed_reports')
        forecast_note = '승인된 외부 전망을 표시합니다.'
    pack = fresh_pack(company, year, ctx)
    used, problems = reverify(fp['payload'], company, year, pack)
    applied = []
    model_in = json.loads(json.dumps(a['model']))
    if fc_list and cfg.get('apply_forecast', 'yes') == 'yes':
        if method != 'dcf':
            forecast_note = f'{method.upper()}는 매출·영업이익 전망을 직접 쓰지 않아 표시만 합니다.'
        elif company != '005930' or any(f['scope'] not in ('연결', '연결(추정)') for f in fc_list):
            return Result('held', '외부 전망의 기업 또는 연결 범위가 N02와 맞지 않습니다.', error_code='forecast_scope')
        else:
            by = {(f['fiscal_year'], f['metric']): f for f in fc_list if f.get('unit') == '백만원'}
            prev_rev = D(pack['facts']['revenue']['value'])
            for i, row in enumerate(model_in.get('years', [])):
                fy = year + 1 + i
                rv, op = by.get((fy, 'revenue')), by.get((fy, 'operatingProfit'))
                if not (rv and op):
                    break
                r, o = D(rv['value']), D(op['value'])
                g = (r / prev_rev - 1) * 100
                mgn = o / r * 100
                row['growth'] = vc.out(g)
                row['margin'] = vc.out(mgn)
                applied.append({'fiscal_year': fy, 'growth': row['growth'], 'margin': row['margin'], 'revenue_id': rv['id'], 'op_id': op['id'],
                                'revenue': rv['value'], 'op': op['value'], 'base_revenue': str(prev_rev)})
                prev_rev = r
            if applied:
                forecast_note = (f"{fc_list[0]['broker']}({fc_list[0]['report_date']}) 승인 전망으로 {len(applied)}개 연도의 성장률·영업이익률을 채웠습니다. "
                                 '세율·감가상각·투자·운전자본·할인율·장기성장률·주식 수는 사용자 가정입니다.')
            else:
                forecast_note = f'승인 전망에 {year + 1}년 매출·영업이익 쌍이 없어 적용하지 못했습니다.'
    if problems:
        return Result('held', 'N01 사실이 원문 재대조와 맞지 않아 계산하지 않았습니다: ' + '; '.join(problems[:6]),
                      {'reverification': {'checked': len(used), 'problems': problems}}, error_code='reverify_mismatch')
    ctx.step(f'{method.upper()} 계산 및 민감도 표 작성')
    cut = instant(ctx.cutoff).astimezone(KST).date().isoformat()
    try:
        req = vc.ValuationRequest.model_validate({
            'company': company, 'base_year': year, 'evidence_digest': pack['digest'], 'valuation_date': cut,
            'label': a['label'], 'assumptions_note': a['assumptions_note'], 'share_basis': a['share_basis'],
            'shares': a['shares'], 'input_kind': a['input_kind'], 'acknowledged': True, 'model': model_in})
    except ValidationError as e:
        first = e.errors()[0]
        return Result('failed', f"가정 검증 실패 {'.'.join(str(x) for x in first['loc'])}: {first['msg']}", error_code='assumption_invalid')
    with localcontext() as lc:
        lc.prec = 40
        result = vc.evaluate(req, pack)
        cells, note = sensitivity(req, pack)
    warnings = list(result['warnings'])
    m = req.model
    if hasattr(m, 'rate'):
        gap = vc.number(m.rate) - vc.number(m.terminal_growth)
        if gap < Decimal('2'):
            warnings.insert(0, f'할인율−장기성장률 차이가 {vc.out(gap)}%p로 좁습니다 (2%p 미만). 말기가치가 결과를 크게 좌우합니다. 민감도 표를 함께 보세요.')
    dynamic = ('70%를 넘', '1%p 미만', '0 이하', '2%p 미만', '좁습니다')
    alerts = [w for w in warnings if any(k in w for k in dynamic)]
    caveats = [w for w in warnings if w not in alerts]
    needs = {'dcf': ['revenue'], 'nav': ['assets', 'liabilities']}.get(method, [])
    inputs_list = [{'key': f['metric'], 'label': f['metric_label'], 'value': f['value'], 'unit': f['unit'], 'kind': 'fact_official',
                    'origin_ref': f['fact_id'], 'approved': True, 'source': f['source'], 'used_in_formula': f['metric'] in needs}
                   for f in used]
    overridden = {f'years[{i + 1}].{k}' for i in range(len(applied)) for k in ('growth', 'margin')}
    inputs_list += [{**i, 'approved': True, 'used_in_formula': i['key'] not in overridden,
                     **({'label': i['key'] + ' (외부 전망으로 대체됨)'} if i['key'] in overridden else {})} for i in a['items']]
    for i, ap in enumerate(applied):
        src = {f['id']: f for f in fc_list}
        for key, fid in (('revenue', ap['revenue_id']), ('op', ap['op_id'])):
            f = src[fid]
            inputs_list.append({'key': f"forecast.{ap['fiscal_year']}.{f['metric']}", 'label': f"{f['broker']} {ap['fiscal_year']}E {f['metric_label']}",
                                'value': f['value'], 'unit': '백만원', 'kind': 'forecast_external', 'origin_ref': fid, 'approved': True,
                                'used_in_formula': True, 'source': f['source']})
        inputs_list.append({'key': f'years[{i + 1}].growth', 'label': f"{ap['fiscal_year']} 매출 성장률 (외부 전망에서 계산)", 'value': ap['growth'], 'unit': '%',
                            'kind': 'derived', 'origin_ref': f"({ap['revenue_id']} / 직전 매출 − 1) × 100", 'approved': None, 'used_in_formula': True})
        inputs_list.append({'key': f'years[{i + 1}].margin', 'label': f"{ap['fiscal_year']} 영업이익률 (외부 전망에서 계산)", 'value': ap['margin'], 'unit': '%',
                            'kind': 'derived', 'origin_ref': f"{ap['op_id']} / {ap['revenue_id']} × 100", 'approved': None, 'used_in_formula': True})
    inputs_list.append({'key': 'per_share', 'label': '주당가치 (계산 결과)', 'value': result['per_share'], 'unit': '원', 'kind': 'derived',
                        'origin_ref': f"{node['id']}:per_share", 'approved': None})
    illustrative = a['input_kind'] == 'illustrative_assumptions'
    return Result('succeeded',
                  (('성장률·이익률은 승인된 증권사 전망, 나머지는 학습용 예시 가정입니다. 실제 기업가치 추정이 아닙니다.' if applied else
                    '학습용 예시 가정으로 계산했습니다. 실제 기업가치 추정이 아닙니다.') if illustrative else
                   ('승인된 증권사 전망과 사용자 가정에서 계산한 주당가치입니다. 목표주가·매매 의견이 아닙니다.' if applied else
                    '사용자 가정에서 계산한 주당가치입니다. 목표주가·매매 의견이 아닙니다.')) + f' ({forecast_note})',
                  {'method': method, 'company': company, 'company_name': COMPANIES[company], 'base_year': year, 'valuation_date': cut,
                   'illustrative': illustrative, 'inputs': inputs_list, 'kinds': KINDS,
                   'rows': result['rows'], 'bridge': result['bridge'], 'enterprise_value': result['enterprise_value'],
                   'equity_value': result['equity_value'], 'per_share': result['per_share'], 'shares': a['shares'],
                   'share_basis': a['share_basis'], 'terminal_value': result['terminal_value'], 'terminal_pv': result['terminal_pv'],
                   'terminal_weight_pct': result['terminal_weight_pct'], 'formulas': result['formulas'], 'warnings': warnings, 'alerts': alerts, 'caveats': caveats,
                   'sensitivity': cells, 'sensitivity_note': note, 'request_digest': digest(req.model_dump()),
                   'evidence_digest': pack['digest'], 'reverification': {'checked': len(used), 'problems': []},
                   'forecast_note': forecast_note, 'forecast_applied': applied,
                   'uses_external_forecast': bool(applied)})


# ---------------------------------------------------------------- T04 broker forecasts
def t04(node, inputs, ctx):
    import hashlib
    from .broker import broker_dir, current_name
    rep_file = (node['config'].get('report') or '').strip()
    if not rep_file:
        return Result('held', 'T04 설정에서 적용할 보고서를 하나 고르세요.', error_code='report_not_selected')
    rep_file = current_name(rep_file)          # v0.22: 회사명 넣기 전의 옛 파일 이름도 받는다
    reports, cands = ctx.store.broker_reports()
    rep = next((r for r in reports if r['file'] == rep_file), None)
    if rep is None:
        return Result('held', f'보고서 {rep_file}가 스캔 목록에 없습니다. 「증권사 전망」 화면에서 스캔하세요.', error_code='report_unknown')
    pdf = broker_dir() / rep_file
    ctx.step('보고서 PDF 해시 재확인')
    if not pdf.exists() or hashlib.sha256(pdf.read_bytes()).hexdigest() != rep['sha256']:
        return Result('held', 'PDF 파일이 없거나 스캔 당시와 해시가 다릅니다. 다시 스캔하고 다시 승인하세요.', error_code='pdf_changed')
    mine = [c for c in cands if c['file'] == rep_file and c['state'] == 'approved' and c['sha256'] == rep['sha256']]
    pending = [c for c in cands if c['file'] == rep_file and c['state'] == 'proposed']
    if not mine:
        return Result('held', f"{rep['broker']} {rep['report_date']} 보고서에 승인된 전망이 없습니다 (미승인 {len(pending)}건).", error_code='no_approved')
    forecasts = [{'id': c['id'], 'broker': c['broker'], 'report_date': c['report_date'], 'report_title': rep.get('title', ''),
                  'analyst': rep.get('analyst', ''), 'fiscal_year': c['fiscal_year'], 'metric': c['metric'], 'metric_label': c['metric_label'],
                  'value': c['effective_value_mn'], 'unit': '백만원', 'value_original': c['value_original'], 'unit_original': c['unit_original'],
                  'scope': c['scope'], 'source': {'file': rep_file, 'sha256': rep['sha256'], 'page': c['page'], 'quote': c['quote'], 'url': rep.get('source_url')},
                  'extraction_confidence': c.get('confidence'), 'review': {'state': 'approved', 'edited': bool(c.get('review_value_mn')),
                  'note': c.get('review_note'), 'at': c.get('reviewed_at')}, 'kind': 'forecast_external'} for c in mine]
    return Result('succeeded' if not pending else 'partial',
                  f"{rep['broker']} {rep['report_date']} 승인 전망 {len(mine)}건" + (f", 미승인 {len(pending)}건은 제외" if pending else '') +
                  '. 외부 전망이며 확인된 사실이 아닙니다.',
                  {'report': {k: rep.get(k) for k in ('file', 'sha256', 'broker', 'analyst', 'report_date', 'title', 'opinion', 'target_price', 'past_check', 'unit', 'scope')},
                   'forecasts': forecasts, 'kind': 'forecast_external'})


# ---------------------------------------------------------------- T05 report
def t05(node, inputs, ctx):
    entries = []
    for up in ctx.upstream(node['id']):
        spec = SPECS[up['node_type']]
        entries.append({'node_id': up['node_id'], 'type': up['node_type'], 'name': spec['display_name'],
                        'perspective': spec['perspective'], 'tier': spec['tier'], 'status': up['status'],
                        'reason': up.get('reason'), 'packet': up.get('output_packet')})
    counts = {}
    for e in entries:
        counts[e['status']] = counts.get(e['status'], 0) + 1
    return Result('succeeded', '연결된 결과를 상태 그대로 취합했습니다. 새 판단·결론을 만들지 않았습니다.',
                  {'entries': entries, 'counts': counts,
                   'notice': '연결선은 데이터 전달 관계일 뿐 승인·정답 확인을 뜻하지 않습니다. 보류·미연결 항목은 결론에서 빠져 있습니다.'})


# ---------------------------------------------------------------- T06 / N09 / N10 price & volume
def t06(node, inputs, ctx):
    from .market import price_series, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다. 기업 칸에서 이름으로 골라 주세요.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        ps = price_series(company, ctx.cutoff, cfg.get('snapshot') or '', int(cfg.get('lookback') or 260))
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    n = len(ps['rows'])
    if n == 0:
        return Result('held', f"기준시점({ps['last_usable_date']}) 이전 가격 자료가 사본에 없습니다.", error_code='no_rows')
    status = 'succeeded' if n >= 252 and not ps['gaps'] and not ps['limit_breaks'] else 'partial'
    why = f"{ps['name']} 일별 가격 {n}거래일 ({ps['rows'][0]['trade_date']} ~ {ps['rows'][-1]['trade_date']}), 사본 {ps['source']['snapshot']} 해시 대조 통과."
    if n < 252:
        why += ' 1년(252거래일) 미만이라 일부 계산은 보류됩니다.'
    if ps['gaps']:
        why += f" 6일 넘는 공백 {len(ps['gaps'])}곳이 있습니다."
    if ps['limit_breaks']:
        why += f" 하루 변동이 가격제한폭(±30%)을 넘은 날 {len(ps['limit_breaks'])}일 — 액면분할·병합 가능성이 있어 수익률·낙폭 해석에 주의하세요(수정주가 아님)."
    q = ps.get('quality') or {}
    for k, lab in (('duplicate_dates', '날짜 중복'), ('bad_close', '종가 없음·0 이하'), ('ohlc_errors', '시가·고가·저가·종가 관계가 맞지 않음'), ('zero_volume', '거래량 0(거래정지 가능성)')):
        if q.get(k):
            why += f" 자료 점검 — {lab} {len(q[k])}일({', '.join(q[k][:3])}{' 등' if len(q[k]) > 3 else ''}): 고치지 않고 표시만 했습니다."
    return Result(status, why, {**ps, 'kind': 'fact_official'})


def _f(x):
    return float(x) if x not in (None, '') else None


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def _price_inputs(inputs, node_type):
    pkt = _one(inputs, 'prices')
    _check_packet(pkt, 'PriceSeries')
    if pkt['header']['produced_by']['node_type'] != 'T06':
        raise Integrity(f'{node_type}은 T06 결과만 받을 수 있습니다.')
    p = pkt['payload']
    rows = [r for r in p['rows'] if _f(r['close'])]
    return p, rows, pkt['header']['payload_digest']


def _ma(vals, n):
    return sum(vals[-n:]) / n if len(vals) >= n else None


def _rsi14(c, n=14):
    """v0.36.1 (P04 이식): Wilder RSI. 첫 n일 단순평균으로 시작해 이후 (앞 평균×(n−1)+오늘)/n."""
    if len(c) < n + 1:
        return None
    ch = [c[i] - c[i - 1] for i in range(1, len(c))]
    up = sum(max(x, 0) for x in ch[:n]) / n; dn = sum(max(-x, 0) for x in ch[:n]) / n
    for x in ch[n:]:
        up = (up * (n - 1) + max(x, 0)) / n; dn = (dn * (n - 1) + max(-x, 0)) / n
    if up == 0 and dn == 0:
        return None
    return 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)


def _median(x):
    s = sorted(x); m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _mad_candidates(rows, recent=60, base=120, thr=4.0):
    """v0.36.1 (P04 이식, 검출기 mad-z-1): 일 로그수익률·로그 거래량·고저폭의 robust z. 기준 분포는 직전 base거래일(오늘 제외),
    하루 ±30% 초과·거래량 0인 날은 기준과 판정에서 뺀다. 「드문 패턴」 후보일 뿐 이상매매·급락 판정이 아니다."""
    import math
    c = [_f(r['close']) for r in rows]
    feats = []
    for i, r in enumerate(rows):
        v, h, l = _f(r.get('volume')), _f(r.get('high')), _f(r.get('low'))
        ret = (c[i] / c[i - 1] - 1) if i else None
        ok = i > 0 and abs(ret) <= 0.3001 and v not in (None, 0)
        feats.append({'ok': ok, '일 로그수익률': math.log(c[i] / c[i - 1]) if i else None, '로그 거래량': math.log(v) if v and v > 0 else None,
                      '고저폭': math.log(h / l) if h and l and h > 0 and l > 0 and h >= l else None})
    out = []
    for i in range(max(base + 1, len(rows) - recent), len(rows)):
        if not feats[i]['ok']:
            continue
        for k in ('일 로그수익률', '로그 거래량', '고저폭'):
            x = feats[i][k]
            b = [feats[j][k] for j in range(i - base, i) if feats[j]['ok'] and feats[j][k] is not None]
            if x is None or len(b) < base // 2:
                continue
            med = _median(b); mad = _median([abs(v - med) for v in b])
            if mad <= 0:
                continue
            z = (x - med) / (1.4826 * mad)
            if abs(z) >= thr:
                out.append({'date': rows[i]['trade_date'], 'feature': k, 'z': round(z, 2)})
    return out


def _pctl(x, q):
    s = sorted(x); k = (len(s) - 1) * q; lo = int(k); hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def _liquidity(pr, shares, d_flow):
    """v0.36.1 (CH N07 이식): 거래대금 배율·회전율·Amihud·유동성 충격 z·이상일·경험적 범위. 과거 분포의 사실이며 예측이 아니다."""
    import math
    rows = [r for r in pr['rows'] if _f(r.get('close')) and _f(r.get('trade_value'))]
    F, held = [], []
    if len(rows) < 21:
        return F, ['유동성(거래대금·회전율·Amihud): 가격 자료 21거래일 미만']
    d = rows[-1]['trade_date']
    tv = [_f(r['trade_value']) for r in rows]; v = [_f(r.get('volume')) or 0.0 for r in rows]; c = [_f(r['close']) for r in rows]
    if d != d_flow:
        held.append(f'기준일 차이: 가격 {d} · 수급 {d_flow} (각자 마지막 확정 거래일)')
    avg = {n: sum(tv[-n:]) / n for n in (5, 20, 60) if len(tv) >= n}
    F.append({'name': '거래대금 평균', 'claim': ' · '.join(f'{n}일 {a / 1e8:,.0f}억원' for n, a in avg.items()), 'kind': 'derived', 'as_of': d,
              'formula': '최근 N거래일 거래대금의 평균 (금융위 시세)'})
    if len(tv) >= 65:
        m = (sum(tv[-5:]) / 5) / (sum(tv[-65:-5]) / 60)
        lab = '급증' if m >= 2.0 else '급감' if m <= 0.5 else '기준 안'
        F.append({'name': '거래대금 배율 (최근 5일 ÷ 직전 60일)', 'claim': f'{m:.2f}배 — 규칙 기준(2.0배 이상 급증 · 0.5배 이하 급감)으로는 「{lab}」', 'value': round(m, 2), 'unit': '배',
                  'kind': 'rule_derived', 'as_of': d, 'formula': '최근 5거래일 평균 거래대금 / 그 직전 60거래일 평균 거래대금. 이름은 규칙에 따른 분류이며 판단이 아님'})
    else:
        held.append('거래대금 배율: 자료 65거래일 미만')
    sh = _f(shares)
    if sh:
        F.append({'name': '회전율', 'claim': ' · '.join(f'{n}일 평균 {sum(v[-n:]) / n / sh * 100:.3f}%' for n in (1, 5, 20) if len(v) >= n), 'kind': 'derived', 'as_of': d,
                  'formula': '평균 거래량 / 상장주식수 × 100 (상장주식수는 사본의 최근 값)'})
    else:
        held.append('회전율: 상장주식수가 사본에 없음')
    am = []          # (index, |수익률%| / 거래대금(조원))
    for i in range(1, len(rows)):
        r = c[i] / c[i - 1] - 1
        if abs(r) <= 0.35:
            am.append((i, abs(r) * 100 / (tv[i] / 1e12)))
    a = [x for _, x in am]
    if len(a) >= 20:
        a5, a20 = sum(a[-5:]) / 5, sum(a[-20:]) / 20
        F.append({'name': 'Amihud 비유동성', 'claim': f'최근 5일 {a5:.3g} · 20일 {a20:.3g} (클수록 같은 거래대금에 가격이 더 크게 움직임)', 'value': round(a5, 6), 'kind': 'derived', 'as_of': d,
                  'formula': '평균(|일 수익률 %| / 거래대금 조원). 하루 변동 35% 초과(분할 의심)일 제외'})
        if len(a) >= 65:
            b = a[-65:-5]; mu = sum(b) / 60; sd = math.sqrt(sum((x - mu) ** 2 for x in b) / 59)
            if sd > 0:
                z = (a5 - mu) / (sd / math.sqrt(5))
                F.append({'name': '유동성 충격 점수', 'claim': f'{z:+.2f} — 규칙 기준(+2.0 이상)으로는 「{"기준 넘음" if z >= 2.0 else "기준 안"}」', 'value': round(z, 2), 'kind': 'rule_derived', 'as_of': d,
                          'formula': '(최근 5일 Amihud 평균 − 직전 60일 평균) / (직전 60일 표준편차 / √5). 규칙 값이며 앞으로의 유동성 판단이 아님'})
        else:
            held.append('유동성 충격 점수: 자료 65거래일 미만')
    else:
        held.append('Amihud 비유동성: 자료 부족')
    if len(tv) >= 40:
        odd = []
        for i in range(len(tv) - 20, len(tv)):
            m = tv[i] / (sum(tv[i - 20:i]) / 20)
            if m >= 2.0 or m <= 0.5:
                odd.append(f"{rows[i]['trade_date']}({m:.2f}배)")
        F.append({'name': '거래대금이 평소와 달랐던 날 (최근 20거래일)', 'claim': f'{len(odd)}일' + (': ' + ', '.join(odd[-6:]) if odd else ''), 'value': len(odd), 'unit': '일',
                  'kind': 'derived', 'as_of': d, 'formula': '그날 거래대금 / 직전 20거래일 평균이 2배 이상이거나 0.5배 이하인 날'})
    if len(tv) >= 60:
        F.append({'name': '최근 60거래일 거래대금 범위', 'claim': f'{_pctl(tv[-60:], 0.1) / 1e8:,.0f}억원 ~ {_pctl(tv[-60:], 0.9) / 1e8:,.0f}억원 (10~90 백분위)', 'kind': 'derived', 'as_of': d,
                  'formula': '최근 60거래일 일 거래대금의 10·90 백분위. 지나간 기간의 범위이며 예측이 아님'})
    return F, held


PRED_HOLD = ('예측: 보류 — 이 카드는 관측값만 계산합니다. 수정주가 기준·거래 상태·연구 이용 범위를 사람이 확인한 기록이 없어 '
             '과거 평가와 앞으로의 예측은 하지 않습니다')           # v0.37.9 P04-10: 3단계 판정(관측·과거 평가·예측) 중 관측만 허용 — 항상 표시
PIT_HOLD = ('거시 지표의 발표·수정 이력(PIT): 보관하지 않음 — 공개 시차는 반영했지만, 나중에 고쳐진 값이 사본에 덮어써졌다면 '
            '기준 날짜 당시 발표된 값과 다를 수 있습니다')           # v0.37.9 CH-N05-7: 항상 표시


def n09(node, inputs, ctx):
    p, rows, dig = _price_inputs(inputs, 'N09')
    if len(rows) < 21:
        return Result('held', '가격 자료가 21거래일 미만이라 계산하지 않습니다.', error_code='too_short')
    c = [_f(r['close']) for r in rows]; v = [_f(r['volume']) or 0.0 for r in rows]; tv = [_f(r['trade_value']) or 0.0 for r in rows]
    last = rows[-1]; d = last['trade_date']; F = []; held = []
    src = {'packet_digest': dig, 'snapshot': p['source']['snapshot'], 'table_sha256': p['source']['sha256']}
    F.append({'name': '기준 종가', 'claim': f"{d} 종가 {c[-1]:,.0f}원 (거래량 {v[-1]:,.0f}주)", 'value': last['close'], 'unit': '원',
              'kind': 'fact_official', 'as_of': d, 'source': src})
    for n, lab in ((5, '1주'), (21, '1개월'), (63, '3개월'), (126, '6개월'), (252, '1년')):
        if len(c) > n:
            r = (c[-1] / c[-1 - n] - 1) * 100
            F.append({'name': f'{lab} 수익률', 'claim': f"{rows[-1-n]['trade_date']} 대비 {r:+.2f}%", 'value': _r(r), 'unit': '%', 'kind': 'derived',
                      'formula': f'종가(t) / 종가(t−{n}거래일) − 1', 'window': n, 'as_of': d})
        else:
            held.append(f'{lab} 수익률: 자료 {len(c)}거래일로 부족')
    for n in (20, 60, 120):
        m = _ma(c, n)
        if m:
            gap = (c[-1] / m - 1) * 100
            F.append({'name': f'{n}일 이동평균', 'claim': f"{m:,.0f}원, 종가와의 차이 {gap:+.2f}%", 'value': _r(m, 0), 'unit': '원', 'kind': 'derived',
                      'formula': f'최근 {n}거래일 종가 평균; 차이 = 종가 / 평균 − 1', 'window': n, 'as_of': d, 'gap_pct': _r(gap)})
        else:
            held.append(f'{n}일 이동평균: 자료 부족')
    rsi = _rsi14(c)
    if rsi is not None:
        F.append({'name': 'RSI(14)', 'claim': f'{rsi:.1f} (0~100, 최근 상승폭과 하락폭의 비율)', 'value': _r(rsi, 1), 'kind': 'derived', 'window': 14, 'as_of': d,
                  'formula': f'Wilder 방식: 100 − 100 / (1 + 평균 상승폭 / 평균 하락폭), 불러온 {len(c)}거래일로 계산. 지나간 가격의 요약이며 매매 판단이 아님'})
    else:
        held.append('RSI(14): 자료 부족')
    w = min(252, len(c)); hi = max(c[-w:]); lo = min(c[-w:])
    hid = rows[-w:][c[-w:].index(hi)]['trade_date']; lod = rows[-w:][c[-w:].index(lo)]['trade_date']
    F.append({'name': f'{w}거래일 최고·최저 (종가)', 'claim': f"최고 {hi:,.0f}원({hid}), 최저 {lo:,.0f}원({lod}); 현재는 최고 대비 {(c[-1]/hi-1)*100:+.2f}%, 최저 대비 {(c[-1]/lo-1)*100:+.2f}%",
              'value': {'high': hi, 'low': lo}, 'unit': '원', 'kind': 'derived', 'formula': '기간 내 종가의 최댓값·최솟값', 'window': w, 'as_of': d})
    v20, v120 = _ma(v, 20), _ma(v, 120)
    if v20 and v120:
        F.append({'name': '거래량 20일/120일', 'claim': f"20일 평균 {v20:,.0f}주, 120일 평균 {v120:,.0f}주, 비율 {v20/v120:.2f}배", 'value': _r(v20 / v120), 'unit': '배',
                  'kind': 'derived', 'formula': '최근 20거래일 평균 거래량 / 최근 120거래일 평균 거래량', 'as_of': d})
    else:
        held.append('거래량 20일/120일 비교: 자료 부족')
    t20 = _ma(tv, 20)
    if t20:
        F.append({'name': '거래대금 20일 평균', 'claim': f"{t20/1e8:,.0f}억원", 'value': _r(t20, 0), 'unit': '원', 'kind': 'derived',
                  'formula': '최근 20거래일 평균 거래대금', 'as_of': d})
    # 기본 상충: 가격 방향과 거래량 방향이 다른가 (판단·신호 아님)
    contrast = []
    m60 = _ma(c, 60)
    if m60 and v20 and v120:
        pu, vu = c[-1] > m60, v20 > v120
        if pu != vu:
            contrast.append(f"종가는 60일 평균보다 {'위' if pu else '아래'}이고, 최근 거래량은 120일 평균보다 {'많습니다' if vu else '적습니다'}. 가격과 거래량의 방향이 서로 다릅니다.")
    r21 = (c[-1] / c[-22] - 1) if len(c) > 21 else None
    r252 = (c[-1] / c[-253] - 1) if len(c) > 252 else None
    if r21 is not None and r252 is not None and (r21 > 0) != (r252 > 0):
        contrast.append(f"1개월 수익률({r21*100:+.2f}%)과 1년 수익률({r252*100:+.2f}%)의 부호가 다릅니다.")
    for t in contrast:
        F.append({'name': '방향이 다른 지표', 'claim': t, 'kind': 'derived', 'formula': '두 지표의 방향 비교 (해석·매매 판단 아님)', 'as_of': d})
    status = 'succeeded' if not held else 'partial'      # 고정 문구(PRED_HOLD)는 상태를 바꾸지 않는다
    return Result(status, f"{p['name']} {d} 기준 가격·추세·거래량 기본 지표 {len(F)}건. 과거 가격의 요약이며 앞으로의 방향을 뜻하지 않습니다.",
                  {'company': p['company'], 'name': p['name'], 'as_of': d, 'findings': F, 'contrasts': contrast, 'held': held + [PRED_HOLD],
                   'price_source': p['source'], 'adjusted': p.get('adjusted', False),
                   'notice': '과거 가격·거래량을 계산한 값입니다. 매수·매도 판단이나 목표가가 아닙니다.'})


def n10(node, inputs, ctx):
    import math
    p, rows, dig = _price_inputs(inputs, 'N10')
    if len(rows) < 61:
        return Result('held', '가격 자료가 61거래일 미만이라 계산하지 않습니다.', error_code='too_short')
    c = [_f(r['close']) for r in rows]; v = [_f(r['volume']) or 0.0 for r in rows]; d = rows[-1]['trade_date']
    lr = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    F = []; held = ['국면(상승·하락·횡보) 분류: 기준이 합의되지 않아 미구현', '이상 변화의 원인 해석: 하지 않음 — 그 시기 공시·뉴스는 「주요 사건·감성 현황」에서 함께 보세요']
    def sd(x):
        m = sum(x) / len(x); return math.sqrt(sum((a - m) ** 2 for a in x) / (len(x) - 1))
    for n in (20, 60, 252):
        if len(lr) >= n:
            vol = sd(lr[-n:]) * math.sqrt(252) * 100
            F.append({'name': f'{n}일 실현 변동성(연율)', 'claim': f'{vol:.1f}%', 'value': _r(vol, 1), 'unit': '%', 'kind': 'derived',
                      'formula': f'최근 {n}거래일 일간 로그수익률 표준편차 × √252', 'window': n, 'as_of': d})
    for n in (5, 20):
        if len(lr) >= n:
            pv = math.sqrt(sum(x * x for x in lr[-n:])) * 100
            F.append({'name': f'{n}거래일 기간 변동성(연율 아님)', 'claim': f'{pv:.2f}%', 'value': _r(pv), 'unit': '%', 'kind': 'derived',
                      'formula': f'√(최근 {n}거래일 일간 로그수익률 제곱의 합). 위의 「실현 변동성(연율)」과 정의가 다른 값', 'window': n, 'as_of': d})
    w = min(252, len(c)); seg = c[-w:]; peak = seg[0]; pk_i = 0; mdd = 0.0; mdd_rng = (0, 0)
    for i, x in enumerate(seg):
        if x > peak: peak, pk_i = x, i
        dd = x / peak - 1
        if dd < mdd: mdd, mdd_rng = dd, (pk_i, i)
    rw = rows[-w:]
    F.append({'name': f'{w}거래일 최대 낙폭', 'claim': f"{mdd*100:.2f}% ({rw[mdd_rng[0]]['trade_date']} 고점 → {rw[mdd_rng[1]]['trade_date']} 저점)",
              'value': _r(mdd * 100), 'unit': '%', 'kind': 'derived', 'formula': '기간 내 고점 대비 종가 하락률의 최솟값', 'window': w, 'as_of': d})
    spikes = []
    for i in range(max(120, len(v) - 60), len(v)):
        base = v[i - 120:i]; m = sum(base) / 120; s = sd(base)
        if s > 0 and (v[i] - m) / s >= 3:
            spikes.append({'date': rows[i]['trade_date'], 'volume': v[i], 'z': _r((v[i] - m) / s), 'close_change_pct': _r((c[i] / c[i - 1] - 1) * 100)})
    if len(v) >= 121:
        F.append({'name': '거래량 급증일 (최근 60거래일)', 'claim': f"{len(spikes)}일" + (': ' + ', '.join(f"{x['date']}(z={x['z']})" for x in spikes[:6]) if spikes else ''),
                  'value': len(spikes), 'unit': '일', 'kind': 'derived', 'formula': '직전 120거래일 평균보다 표준편차 3배 이상 많은 날', 'as_of': d, 'days': spikes})
    else:
        held.append('거래량 급증일: 자료 120거래일 미만')
    if len(rows) >= 121:
        cand = _mad_candidates(rows)
        F.append({'name': '드문 패턴 후보 (최근 60거래일)', 'claim': f"{len(cand)}건" + (': ' + ', '.join(f"{x['date']} {x['feature']}(z={x['z']:+})" for x in cand[-6:]) if cand else ''),
                  'value': len(cand), 'unit': '건', 'kind': 'rule_derived', 'as_of': d, 'days': cand,
                  'formula': '검출기 mad-z-1: (값 − 직전 120거래일 중앙값) / (1.4826 × MAD)의 절댓값이 4 이상인 날. 수익률·거래량·고저폭 각각. 드문 값이라는 뜻일 뿐 이상매매·급락 판정이 아님'})
    else:
        held.append('드문 패턴 후보: 자료 121거래일 미만')
    if len(c) >= 180:
        above = sum(1 for i in range(len(c) - 120, len(c)) if c[i] > sum(c[i - 59:i + 1]) / 60)
        F.append({'name': '60일 평균 위 머문 비율 (최근 120거래일)', 'claim': f'{above}/120일 ({above/120*100:.0f}%)', 'value': _r(above / 120 * 100, 0), 'unit': '%',
                  'kind': 'derived', 'formula': '각 날의 종가 > 그날까지 60거래일 평균 인 날의 비율', 'as_of': d})
    else:
        held.append('추세 지속 비율: 자료 180거래일 미만')
    rg = regime(rows)
    if rg:
        cur = rg[-1][1]; since = rg[-1][0]
        for t, g, *_ in reversed(rg):
            if g != cur:
                break
            since = t
        last120 = rg[-120:]; cnt = {k: sum(1 for x in last120 if x[1] == k) for k in ('상승', '하락', '전환·횡보')}
        _, _, m20, m60, m60p = rg[-1]
        F.append({'name': '국면 (이동평균 배열 규칙)', 'claim': f"{cur} — {since}부터 이어짐 (20일선 {m20:,.0f} · 60일선 {m60:,.0f} · 20거래일 전 60일선 {m60p:,.0f})",
                  'value': cur, 'kind': 'rule_derived', 'as_of': d,
                  'formula': '상승: 종가>60일선, 20일선>60일선, 60일선이 20거래일 전보다 높음 / 하락: 셋 다 반대 / 그 밖: 전환·횡보. 규칙에 따른 분류이며 앞으로의 방향 판단이 아님'})
        F.append({'name': f'최근 {len(last120)}거래일 국면 분포', 'claim': ' · '.join(f'{k} {v}일' for k, v in cnt.items()), 'kind': 'rule_derived', 'as_of': d,
                  'formula': '같은 규칙을 날마다 적용한 결과의 개수'})
        held = [h for h in held if not h.startswith('국면')]
    else:
        held.append('국면 분류: 자료 80거래일 미만')
    return Result('succeeded', f"{p['name']} {d} 기준 변동성·낙폭·거래량 급증·추세 지속·국면 {len(F)}건. 국면은 이동평균 배열 규칙에 따른 분류이며 판단이 아닙니다.",
                  {'company': p['company'], 'name': p['name'], 'as_of': d, 'findings': F, 'held': held, 'price_source': p['source'],
                   'notice': '과거 가격·거래량을 계산한 값입니다. 앞으로의 위험이나 방향을 예측하지 않습니다.'})


# ---------------------------------------------------------------- T07 / N07 / N08 flows
WHO = (('foreign_net_qty', '외국인'), ('institution_net_qty', '기관'), ('individual_net_qty', '개인'))


def t07(node, inputs, ctx):
    from .market import flow_series, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다. 기업 칸에서 이름으로 골라 주세요.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        fs = flow_series(company, ctx.cutoff, cfg.get('snapshot') or '', int(cfg.get('lookback') or 260))
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    n = len(fs['rows'])
    if n == 0:
        return Result('held', f"기준시점({fs['last_usable_date']}) 이전 수급 자료가 사본에 없습니다.", error_code='no_rows')
    why = (f"{fs['name']} 투자자별 순매수 {n}거래일 ({fs['rows'][0]['trade_date']} ~ {fs['rows'][-1]['trade_date']}), 대차잔고 {len(fs['lending'])}일. "
           '순매수는 포털 수집값(공식 대조 전)입니다.')
    return Result('succeeded' if n >= 60 else 'partial', why, {**fs, 'kind': 'fact_portal'})


def _flow_inputs(inputs, node_type):
    pkt = _one(inputs, 'flows')
    _check_packet(pkt, 'FlowSeries')
    if pkt['header']['produced_by']['node_type'] != 'T07':
        raise Integrity(f'{node_type}은 T07 결과만 받을 수 있습니다.')
    return pkt['payload'], pkt['header']['payload_digest']


def _n(x):
    return float(x) if x not in (None, '') else 0.0


def n07(node, inputs, ctx):
    p, dig = _flow_inputs(inputs, 'N07')
    rows = p['rows']
    if len(rows) < 5:
        return Result('held', '수급 자료가 5거래일 미만이라 계산하지 않습니다.', error_code='too_short')
    d = rows[-1]['trade_date']; F = []; held = ['금액 기준 순매수: 포털 자료가 수량만 제공', '거래소(KRX) 공식 자료와의 대조: 미실시']
    last = rows[-1]
    F.append({'name': '기준일 주체별 순매수', 'claim': f"{d} 외국인 {_n(last['foreign_net_qty']):+,.0f}주 · 기관 {_n(last['institution_net_qty']):+,.0f}주 · 개인 {_n(last['individual_net_qty']):+,.0f}주",
              'kind': 'fact_portal', 'as_of': d})
    for w in (5, 20, 60):
        if len(rows) < w:
            held.append(f'{w}일 누적: 자료 부족'); continue
        seg = rows[-w:]; vol = sum(_n(r['volume']) for r in seg)
        parts = []
        for k, lab in WHO:
            s = sum(_n(r[k]) for r in seg)
            parts.append(f"{lab} {s:+,.0f}주" + (f"(거래량의 {s / vol * 100:+.1f}%)" if vol else ''))
        F.append({'name': f'{w}거래일 누적 순매수', 'claim': ' · '.join(parts), 'kind': 'derived', 'window': w, 'as_of': d,
                  'formula': f'최근 {w}거래일 순매수 합계; 비중 = 합계 / 같은 기간 거래량 합계'})
    for k, lab in WHO[:2]:
        sign = 1 if _n(rows[-1][k]) > 0 else -1 if _n(rows[-1][k]) < 0 else 0
        run = 0
        for r in reversed(rows):
            v = _n(r[k])
            if sign and ((v > 0) if sign > 0 else (v < 0)):
                run += 1
            else:
                break
        if sign:
            F.append({'name': f'{lab} 연속 순{"매수" if sign > 0 else "매도"}', 'claim': f'{run}거래일째', 'kind': 'derived', 'as_of': d,
                      'formula': '기준일부터 거꾸로 같은 부호가 이어진 거래일 수'})
    hp = [(r['trade_date'], _n(r['foreign_hold_pct'])) for r in rows if r.get('foreign_hold_pct') not in (None, '')]
    if hp:
        txt = f"{hp[-1][1]:.2f}%"
        for w in (20, 60):
            if len(hp) > w:
                txt += f", {w}거래일 전({hp[-1 - w][0]}) 대비 {hp[-1][1] - hp[-1 - w][1]:+.2f}%p"
        if hp[-1][0] != d:   # v0.39.5 보유율이 빈 날(외국인 한도 종목의 KIS 보충분)이 있으면 값의 실제 날짜를 밝힘
            txt = f'{hp[-1][0]} 기준 ' + txt
        F.append({'name': '외국인 보유율', 'claim': txt, 'kind': 'derived', 'as_of': hp[-1][0], 'formula': '보유율(포털 수집값)의 차이'})
    L = p.get('lending') or []
    if L:
        b = _n(L[-1]['balance_qty']); amt = _n(L[-1]['balance_amt'])
        txt = f"{L[-1]['trade_date']} 잔고 {b:,.0f}주 ({amt / 1e8:,.0f}억원)"
        if len(L) > 20 and _n(L[-21]['balance_qty']):
            txt += f", 20거래일 전 대비 {(b / _n(L[-21]['balance_qty']) - 1) * 100:+.1f}%"
        sh = _n(p.get('shares_outstanding'))
        if sh:
            txt += f", 발행주식의 {b / sh * 100:.2f}%"
        F.append({'name': '대차잔고 (금융위)', 'claim': txt, 'kind': 'derived', 'as_of': L[-1]['trade_date'],
                  'formula': '대차 잔고 주수; 비율 = 잔고 / 발행주식수. 대차잔고는 공매도 가능 물량의 참고치이며 공매도 자체가 아님'})
    else:
        held.append('대차잔고: 사본에 없음')
    pk = _one(inputs, 'prices')
    if pk:
        _check_packet(pk, 'PriceSeries')
        if pk['header']['produced_by']['node_type'] != 'T06':
            raise Integrity('N07의 가격 입력은 T06 결과만 받을 수 있습니다.')
        if pk['payload']['company'] != p['company']:
            held.append(f"유동성: 가격({pk['payload']['company']})과 수급({p['company']})의 기업이 달라 보류")
        else:
            lf, lh = _liquidity(pk['payload'], p.get('shares_outstanding'), d)
            F += lf; held += lh
    else:
        held.append('유동성(거래대금 배율·회전율·Amihud): 가격 자료(T06) 미연결')
    return Result('succeeded', f"{p['name']} {d} 기준 수급·유동성 {len(F)}건. 순매수는 포털 수집값이며 매매 판단이 아닙니다.",
                  {'company': p['company'], 'name': p['name'], 'as_of': d, 'findings': F, 'held': held, 'flow_source': p['source'],
                   'notice': '누가 얼마나 사고팔았는지의 기록입니다. 앞으로의 주가 방향이나 매수·매도 판단이 아닙니다.'})


def n08(node, inputs, ctx):
    import math
    p, dig = _flow_inputs(inputs, 'N08')
    pk = _one(inputs, 'prices')
    _check_packet(pk, 'PriceSeries')
    if pk['header']['produced_by']['node_type'] != 'T06':
        raise Integrity('N08의 가격 입력은 T06 결과만 받을 수 있습니다.')
    pr = pk['payload']
    if pr['company'] != p['company']:
        return Result('held', f"가격({pr['company']})과 수급({p['company']})의 기업이 다릅니다. 같은 기업으로 맞춰 주세요.", error_code='company_mismatch')
    close = {r['trade_date']: _f(r['close']) for r in pr['rows'] if _f(r['close'])}
    days = sorted(close)
    ret = {days[i]: close[days[i]] / close[days[i - 1]] - 1 for i in range(1, len(days))}
    fl = [r for r in p['rows'] if r['trade_date'] in ret]
    if len(fl) < 40:
        return Result('held', f'가격과 수급이 함께 있는 거래일이 {len(fl)}일로 부족합니다(40일 이상 필요).', error_code='too_short')
    d = fl[-1]['trade_date']; F = []; held = ['원인 해석(왜 엇갈렸는지): 하지 않음 — 그 시기 공시·뉴스는 「주요 사건·감성 현황」에서 함께 보세요', '앞으로의 방향 판단: 하지 않음']
    for k, lab in WHO[:2]:
        sw = []
        cum = [sum(_n(x[k]) for x in fl[max(0, i - 19):i + 1]) for i in range(len(fl))]
        for i in range(max(20, len(fl) - 120), len(fl)):
            if (cum[i] > 0) != (cum[i - 1] > 0) and cum[i] != 0 and cum[i - 1] != 0:
                sw.append(f"{fl[i]['trade_date']}({'순매수' if cum[i] > 0 else '순매도'}로)")
        F.append({'name': f'{lab} 20일 누적 방향 전환 (최근 120거래일)', 'claim': f'{len(sw)}회' + (': ' + ', '.join(sw[-5:]) if sw else ''),
                  'kind': 'derived', 'as_of': d, 'formula': '20거래일 누적 순매수의 부호가 바뀐 날'})
    seg = fl[-60:]
    a = sum(1 for r in seg if _n(r['foreign_net_qty']) > 0 and ret[r['trade_date']] < 0)
    b = sum(1 for r in seg if _n(r['foreign_net_qty']) < 0 and ret[r['trade_date']] > 0)
    F.append({'name': '외국인 매매와 주가가 엇갈린 날 (최근 60거래일)', 'claim': f'순매수인데 하락 {a}일 · 순매도인데 상승 {b}일 (전체 {len(seg)}일)',
              'kind': 'derived', 'as_of': d, 'formula': '외국인 순매수 부호와 당일 종가 변화 부호가 반대인 날 수'})
    c20 = sum(_n(r['foreign_net_qty']) for r in fl[-20:]); r20 = close[d] / close[fl[-21]['trade_date']] - 1 if len(fl) > 20 else None
    if r20 is not None:
        same = (c20 > 0) == (r20 > 0)
        F.append({'name': '최근 20거래일: 외국인 누적과 주가', 'claim': f"외국인 {c20:+,.0f}주, 주가 {r20 * 100:+.2f}% → " + ('같은 방향' if same else '서로 다른 방향'),
                  'kind': 'derived', 'as_of': d, 'formula': '20거래일 누적 순매수 부호와 20거래일 수익률 부호 비교 (판단 아님)'})
    x = [_n(r['foreign_net_qty']) / _n(r['volume']) for r in fl[-120:] if _n(r['volume'])]
    y = [ret[r['trade_date']] for r in fl[-120:] if _n(r['volume'])]
    if len(x) >= 30:
        mx, my = sum(x) / len(x), sum(y) / len(y)
        sx = math.sqrt(sum((v - mx) ** 2 for v in x)); sy = math.sqrt(sum((v - my) ** 2 for v in y))
        if sx and sy:
            cor = sum((u - mx) * (v - my) for u, v in zip(x, y)) / (sx * sy)
            F.append({'name': '외국인 순매수 비중과 당일 수익률의 상관 (최근 120거래일)', 'claim': f'{cor:+.2f} ({len(x)}일)', 'value': round(cor, 3),
                      'kind': 'derived', 'as_of': d, 'formula': '피어슨 상관: (외국인 순매수 / 거래량) vs 당일 수익률. 같은 날 함께 움직인 정도이며 인과가 아님'})
    tvm = {r['trade_date']: _f(r.get('trade_value')) or 0.0 for r in pr['rows']}
    if len(fl) >= 20:
        s20 = fl[-20:]; tv20 = sum(tvm.get(r['trade_date'], 0.0) for r in s20)
        if tv20:
            amt = {lab: sum(_n(r[k]) * close[r['trade_date']] for r in s20) for k, lab in WHO}
            F.append({'name': '20거래일 순매수 강도 (금액은 근사)', 'claim': ' · '.join(f"{lab} 약 {a / 1e8:+,.0f}억원(거래대금의 {a / tv20 * 100:+.2f}%)" for lab, a in amt.items()),
                      'value': {lab: round(a / tv20 * 100, 2) for lab, a in amt.items()}, 'unit': '%', 'kind': 'derived', 'as_of': d,
                      'formula': 'Σ(일 순매수 수량 × 그날 종가) / 같은 기간 거래대금 × 100. 포털은 수량만 주므로 금액은 종가로 어림한 계산값(실제 체결 금액 아님)'})
        else:
            held.append('순매수 강도: 거래대금 자료 없음')
        ci = sum(_n(r['institution_net_qty']) for r in s20)
        if r20 is not None and ci:
            F.append({'name': '최근 20거래일: 기관 누적과 주가', 'claim': f"기관 {ci:+,.0f}주, 주가 {r20 * 100:+.2f}% → " + ('같은 방향' if (ci > 0) == (r20 > 0) else '서로 다른 방향'),
                      'kind': 'derived', 'as_of': d, 'formula': '20거래일 누적 순매수 부호와 20거래일 수익률 부호 비교 (판단 아님). 외국인과 평균 내지 않고 따로 보임'})
        ind, fi = sum(_n(r['individual_net_qty']) for r in s20), sum(_n(r['foreign_net_qty']) + _n(r['institution_net_qty']) for r in s20)
        if ind and fi and (ind > 0) != (fi > 0):
            F.append({'name': '개인과 외국인·기관의 방향 (최근 20거래일)', 'claim': f"개인 {ind:+,.0f}주 · 외국인+기관 {fi:+,.0f}주 → 서로 반대 방향", 'kind': 'derived', 'as_of': d,
                      'formula': '20거래일 누적 순매수 부호 비교. 매매 방향의 기록이며 의도를 뜻하지 않음'})
    if len(fl) >= 25:
        for k, lab in WHO[:2]:
            a5, b20 = sum(_n(r[k]) for r in fl[-5:]), sum(_n(r[k]) for r in fl[-25:-5])
            if a5 and b20 and (a5 > 0) != (b20 > 0):
                F.append({'name': f'{lab} 매매 방향 바뀜', 'claim': f"그 직전 20거래일 {b20:+,.0f}주 → 최근 5거래일 {a5:+,.0f}주", 'kind': 'derived', 'as_of': d,
                          'formula': '최근 5거래일 합계의 부호가 그 직전 20거래일 합계와 반대. 매매 방향의 기록이며 의도를 뜻하지 않음'})
    return Result('succeeded', f"{p['name']} {d} 기준 수급 전환·가격 불일치 {len(F)}건. 원인 해석과 방향 판단은 하지 않았습니다.",
                  {'company': p['company'], 'name': p['name'], 'as_of': d, 'findings': F, 'held': held, 'flow_source': p['source'], 'price_source': pr['source'],
                   'notice': '수급과 가격이 같은 방향이었는지의 기록입니다. 매매 신호가 아닙니다.'})


def regime(rows):
    """N10 국면 규칙(이동평균 배열). 상승: 종가>60일선, 20일선>60일선, 60일선이 20거래일 전보다 높음. 하락: 셋 다 반대. 그 밖: 전환·횡보."""
    c = [_f(r['close']) for r in rows]
    out = []
    for i in range(79, len(c)):
        m20 = sum(c[i - 19:i + 1]) / 20; m60 = sum(c[i - 59:i + 1]) / 60; m60p = sum(c[i - 79:i - 19]) / 60
        if c[i] > m60 and m20 > m60 and m60 > m60p:
            g = '상승'
        elif c[i] < m60 and m20 < m60 and m60 < m60p:
            g = '하락'
        else:
            g = '전환·횡보'
        out.append((rows[i]['trade_date'], g, m20, m60, m60p))
    return out


# ---------------------------------------------------------------- T09 / N03 비교기업
def t09(node, inputs, ctx):
    from .market import peer_package, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if company not in COMPANIES:
        return Result('held', f'{company}는 지원 기업이 아닙니다.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        pk = peer_package(company, ctx.cutoff, cfg.get('snapshot') or '')
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    roles = {}
    for m in pk['members']:
        roles[m['role']] = roles.get(m['role'], 0) + 1
    from .market import ROLE_LABEL
    why = f"{pk['name']} 비교군 「{pk['group']['method']}」 {len(pk['members'])}곳 (" + ', '.join(f'{ROLE_LABEL[k]} {v}' for k, v in roles.items()) + '), 사본 해시 대조 통과.'
    return Result('succeeded', why, {**pk, 'kind': 'fact_official'})


def _ttm(rows):
    """분기 행 → 최근 4분기 합(TTM)과 그 전 4분기 합, 최근 재무상태. 분기가 이어지지 않으면 None."""
    from datetime import date
    by = {}
    for r in rows:
        by.setdefault(str(r['period_end']), {})[r['metric']] = _f(r['amount'])
    ends = sorted(by)
    if len(ends) < 4:
        return None
    def contiguous(seq):
        ds = [date.fromisoformat(x) for x in seq]
        return all(60 <= (b - a).days <= 120 for a, b in zip(ds, ds[1:]))
    last4 = ends[-4:]
    if not contiguous(last4):
        return None
    def s(seq, m):
        vals = [by[e].get(m) for e in seq]
        return None if any(v is None for v in vals) else sum(vals)
    prev4 = ends[-8:-4] if len(ends) >= 8 and contiguous(ends[-8:]) else None
    bal = by[ends[-1]]
    return {'end': ends[-1], 'rev': s(last4, 'revenue'), 'op': s(last4, 'operating_income'), 'ni': s(last4, 'net_income'),
            'rev_prev': s(prev4, 'revenue') if prev4 else None, 'assets': bal.get('assets'), 'liab': bal.get('liabilities'), 'equity': bal.get('equity'),
            'currency': next((r.get('currency') for r in rows if r.get('currency')), None), 'source': next((r.get('source') for r in rows), None)}


def _ratios(t):
    if not t:
        return {}
    g = lambda a, b: (a / b) if (a is not None and b not in (None, 0)) else None
    return {'growth': g(t['rev'], t['rev_prev']) - 1 if g(t['rev'], t['rev_prev']) is not None else None,
            'op_margin': g(t['op'], t['rev']), 'net_margin': g(t['ni'], t['rev']),
            'roe': g(t['ni'], t['equity']), 'debt_ratio': g(t['liab'], t['equity'])}


RATIO_LABEL = [('growth', '매출 성장률(최근 4분기, 전년 대비)', '%'), ('op_margin', '영업이익률(최근 4분기)', '%'),
               ('net_margin', '순이익률(최근 4분기)', '%'), ('roe', 'ROE(최근 4분기 순이익 / 자본)', '%'), ('debt_ratio', '부채비율(부채 / 자본)', '%')]


def n03(node, inputs, ctx):
    from datetime import date
    from .market import ROLE_LABEL, STALE_DAYS
    pkt = _one(inputs, 'peers')
    _check_packet(pkt, 'IndustryPeers')
    if pkt['header']['produced_by']['node_type'] != 'T09':
        raise Integrity('N03은 T09 결과만 받을 수 있습니다.')
    p = pkt['payload']
    base = p['company']; cut = date.fromisoformat(p['last_usable_date'])
    stats, stale = {}, []
    for t, rows in p['financials'].items():
        tt = _ttm(rows)
        if not tt:
            continue
        if (cut - date.fromisoformat(tt['end'])).days > STALE_DAYS:
            stale.append(f"{t}({tt['end']})"); continue
        stats[t] = {**_ratios(tt), 'end': tt['end'], 'currency': tt['currency'], 'source': tt['source']}
    if base not in stats:
        return Result('held', f'{base}의 최근 4분기 재무를 만들 수 없습니다.', error_code='base_missing')
    role = {m['ticker']: m['role'] for m in p['members']}; role[base] = 'chip'
    name = {m['ticker']: m['name'] for m in p['members']}; name[base] = p['name']
    chip = [t for t in stats if role.get(t) == 'chip']
    F, held = [], []
    F.append({'name': '비교군', 'claim': f"「{p['group']['method']}」에서 {ROLE_LABEL['chip']} {len(chip) - 1}곳과 비교 (장비·소재·부품은 사업 구조가 달라 순위에서 제외, 목록만 표시)",
              'kind': 'fact_official', 'formula': '팀이 고른 묶음 + 산업분류 코드로 역할 구분(국내 KSIC 2611·2612, 미국 SIC 3674·3663 = 반도체 제조·설계)'})
    for key, label, unit in RATIO_LABEL:
        vals = sorted(((stats[t][key], t) for t in chip if stats[t].get(key) is not None), reverse=(key != 'debt_ratio'))
        bv = stats[base].get(key)
        if bv is None or len(vals) < 3:
            held.append(f'{label}: 계산할 자료 부족'); continue
        rank = 1 + sum(1 for v, t in vals if (v > bv if key != 'debt_ratio' else v < bv))
        med = sorted(v for v, _ in vals)[len(vals) // 2]
        top = ', '.join(f"{name.get(t, t)} {v * 100:.1f}%" for v, t in vals[:3])
        F.append({'name': label, 'claim': f"{p['name']} {bv * 100:.1f}% — {len(vals)}곳 중 {rank}위{'(낮을수록 위)' if key == 'debt_ratio' else ''}, 중앙값 {med * 100:.1f}%. 상위: {top}",
                  'value': round(bv * 100, 2), 'rank': rank, 'of': len(vals), 'median': round(med * 100, 2), 'unit': unit, 'kind': 'derived',
                  'formula': '분기 재무(DART·SEC)로 직접 계산. 해외는 통화가 달라 비율만 비교', 'as_of': stats[base]['end']})
    bs = stats[base]
    if bs.get('net_margin') is not None and bs.get('op_margin') is not None and bs['net_margin'] > bs['op_margin']:
        F.append({'name': '참고: 순이익률 > 영업이익률', 'claim': f"순이익률({bs['net_margin'] * 100:.1f}%)이 영업이익률({bs['op_margin'] * 100:.1f}%)보다 높습니다. 최근 4분기 순이익에 영업 밖 이익(투자 처분·평가 등)이 크게 들어 있을 수 있어, 순이익 기준 순위(순이익률·ROE)는 일회성 영향을 받을 수 있습니다.",
                  'kind': 'derived', 'formula': '두 비율의 크기 비교 (원인 확인은 사업보고서·분기보고서 주석 필요)'})
    caps = sorted(((_f(v['market_cap']), t) for t, v in p['market_cap'].items() if _f(v['market_cap'])), reverse=True)
    if base in dict((t, c) for c, t in caps):
        r = 1 + sum(1 for c, t in caps if c > _f(p['market_cap'][base]['market_cap']))
        F.append({'name': '시가총액 순위 (국내 비교기업)', 'claim': f"{len(caps)}곳 중 {r}위 — " + ', '.join(f"{name.get(t, t)} {c / 1e12:,.0f}조원" for c, t in caps[:4]),
                  'kind': 'derived', 'formula': '금융위 시세의 시가총액, 기준시점 확정 거래일', 'as_of': p['market_cap'][base]['date']})
    others = {}
    for m in p['members']:
        if m['role'] != 'chip':
            others.setdefault(ROLE_LABEL[m['role']], []).append(m['name'])
    if others:
        F.append({'name': '순위에서 뺀 비교기업', 'claim': ' / '.join(f"{k}: {', '.join(v)}" for k, v in others.items()), 'kind': 'fact_official',
                  'formula': '같은 반도체 산업이지만 장비·소재·부품은 이익 구조가 달라 같은 줄에 세우지 않음'})
    if stale:
        held.append('최근 분기 재무가 오래된 기업 제외: ' + ', '.join(stale))
    held.append('경쟁력·점유율 해석: N04(사업보고서 문장 검색)에서 다룰 예정')
    table = [{'ticker': t, 'name': name.get(t, t), 'role': ROLE_LABEL[role.get(t, 'other')], 'end': s['end'], 'currency': s['currency'], 'source': s['source'],
              **{k: (round(s[k] * 100, 2) if s.get(k) is not None else None) for k, _, _ in RATIO_LABEL}} for t, s in stats.items()]
    return Result('succeeded', f"{p['name']} 반도체 비교군 {len(chip) - 1}곳 대비 위치 {len(F)}건. 순위는 과거 재무의 비교이며 우열 판단이 아닙니다.",
                  {'company': base, 'name': p['name'], 'as_of': stats[base]['end'], 'findings': F, 'held': held, 'peer_table': table,
                   'peer_source': p['source'], 'notice': '과거 재무 비율의 비교입니다. 「경쟁력이 높다·낮다」나 매매 판단이 아닙니다.'})


# ---------------------------------------------------------------- T10 거시 시계열 / N06 완성
def t10(node, inputs, ctx):
    from .market import macro_series, SnapshotError
    ctx.step('Neon 사본 해시 재대조')
    try:
        ms = macro_series(ctx.cutoff, node['config'].get('snapshot') or '')
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    n = sum(1 for s in ms['series'].values() if s['obs'])
    return Result('succeeded', f'거시 지표 {n}종 (FRED·한국은행·관세청), 공개 시차를 반영해 기준시점에 공개된 관측만 썼습니다.', {**ms, 'kind': 'fact_official'})


def _scen(txt):
    """「환율 ±5%, USD 세전손익 ±435,059백만원」 / 「금리 +1%p … 합계 +42,646백만원」 / 「금리 +100bp, … −41,875백만원」 → (충격, 영향)."""
    import re
    t = (txt or '').replace('−', '-').replace(',', '')
    m = re.search(r'([±+\-]?\d+(?:\.\d+)?)\s*(%p|%|bp)', t)
    if not m:
        return None
    shock = float(m.group(1).replace('±', '')); unit = m.group(2)
    if unit == 'bp':
        shock, unit = shock / 100, '%p'
    vals = re.findall(r'([±+\-]?\d+(?:\.\d+)?)\s*백만원', t)
    if not vals:
        return None
    v = vals[-1]
    imp = float(v.replace('±', ''))
    if v.startswith('-'):
        imp = -abs(imp)
    return {'shock': abs(shock), 'unit': unit, 'impact_mn': imp, 'symmetric': '±' in v}


def _at(obs, d):
    """d 이하의 마지막 관측."""
    prev = None
    for od, v in obs:
        if od <= d:
            prev = (od, _f(v))
        else:
            break
    return prev


def _fx_note(e, s):
    """v0.36.3: 환율 계산에 어느 통화의 공시 민감도를 썼는지. 원/달러 가정에는 미국 달러 민감도만 쓴다(PM 결정)."""
    cur = (s or {}).get('currency') or ('USD' if 'USD' in str(e.get('fx_scenario') or '') else None)
    if cur == 'USD':
        return ' 미국 달러(USD) 민감도만 썼고, 유로 등 다른 통화의 공시 민감도는 넣지 않음'
    return f' 공시된 {cur} 민감도를 씀(미국 달러 줄을 찾지 못함 — 원/달러 가정과 통화가 다름)' if cur else ' 공시 문장에서 통화를 읽지 못함'


def _my_scenario(txt, exposures):
    """v0.36.2 (CH N06 이식): 사용자가 적은 가정(「환율 5% 상승, 금리 50bp 인하」)을 공시 민감도로 환산. 선형 비례,
    가정 변화가 공시 충격폭보다 크면 계산하지 않는다(외삽 금지). 반대 조건도 함께. 예측·확률 아님."""
    import re
    t = (txt or '').replace('−', '-').replace(',', ' ')
    F, held, asm = [], [], {}
    for key, pat in (('fx', r'(환율|원\s*/\s*달러|달러)'), ('rate', r'(금리)')):
        m = re.search(pat + r'[^0-9+\-]*([+\-]?\d+(?:\.\d+)?)\s*(%p|%포인트|bp|%)?\s*(상승|인상|올|하락|인하|내)?', t)
        if not m:
            continue
        v, unit, word = float(m.group(2)), m.group(3) or '', m.group(4) or ''
        if word in ('하락', '인하', '내'):
            v = -abs(v)
        if key == 'fx' and unit != '%':
            held.append(f'내 가정(환율): 단위를 %로 적어 주세요 — 「{m.group(0).strip()}」은 보류'); continue
        if key == 'rate':
            if unit == 'bp':
                v = v / 100
            elif unit not in ('%p', '%포인트'):
                held.append(f'내 가정(금리): 단위를 %p 또는 bp로 적어 주세요 — 「{m.group(0).strip()}」은 보류'); continue
        asm[key] = v
    if not asm and not held:
        return F, ['내 가정: 환율(%)·금리(%p, bp) 가정을 읽지 못함'] if (txt or '').strip() else []
    for key, lab, u, sk in (('fx', '환율', '%', 'fx'), ('rate', '금리', '%p', 'rate')):
        if key not in asm:
            continue
        a = asm[key]
        for e in exposures:
            s = e.get(sk + '_struct') or _scen(e.get(sk + '_scenario'))
            if not s:
                held.append(f"{e['name']} 내 가정({lab}): 공시 민감도 숫자가 없어 보류"); continue
            shock = abs(s['shock'])
            if abs(a) > shock + 1e-9:
                held.append(f"{e['name']} 내 가정({lab} {a:+g}{u}): 회사가 공시한 충격폭({shock:g}{u})보다 커서 보류(공시 범위 밖으로 늘리지 않음)"); continue
            imp = s['impact_mn'] * a / shock
            F.append({'name': f"{e['name']} {lab} 영향 (내 가정이라면)", 'claim': f"{lab} {a:+g}{u} → 세전손익 약 {imp:+,.0f}백만원 · 반대 조건({-a:+g}{u}) → 약 {-imp:+,.0f}백만원",
                      'value': round(imp), 'unit': '백만원', 'kind': 'derived',
                      'formula': f"사용자 가정 × 공시 민감도({shock:g}{u} 변동 시 {s['impact_mn']:+,.0f}백만원) / {shock:g}{u}. 선형 비례·다른 변수 일정 가정. 가정은 사용자가 적은 값이며 예측·확률·실현손익이 아님." + (_fx_note(e, s) if key == 'fx' else '')})
    return F, held


def _bigrams(t):
    import re
    s = re.sub(r'[^0-9A-Za-z가-힣]', '', t or '')
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _title_groups(news, last, days=30, sim=0.6, gap=3):
    """v0.36.2 (CH N11 이식): 제목 2글자 묶음의 Jaccard ≥ 0.6 이고 3일 이내인 기사를 한 묶음으로. 내용·사실 여부는 보지 않는다."""
    from datetime import date, timedelta
    lo = (date.fromisoformat(last) - timedelta(days=days)).isoformat()
    G = []
    for n in sorted((x for x in news if x['date'][:10] >= lo), key=lambda x: x['date']):
        b = _bigrams(n['title']); d = date.fromisoformat(n['date'][:10])
        if len(b) < 4:
            continue
        for g in reversed(G):
            if (d - g['last']).days > gap:
                continue
            u = len(b | g['b'])
            if u and len(b & g['b']) / u >= sim:
                g['n'] += 1; g['last'] = d; break
        else:
            G.append({'b': b, 'title': n['title'], 'first': n['date'][:10], 'last': d, 'n': 1})
    return sorted((g for g in G if g['n'] >= 3), key=lambda g: (-g['n'], g['first']))


def n06(node, inputs, ctx):
    pkt = _one(inputs, 'exposure')
    _check_packet(pkt, 'MacroExposure')
    if pkt['header']['produced_by']['node_type'] != 'N05':
        raise Integrity('N06은 N05 결과만 받을 수 있습니다.')
    rows = [{'company': e['company'], 'name': e['name'], 'fx_scenario': e['fx_scenario'], 'rate_scenario': e['rate_scenario'],
             'kind': 'fact_official', 'scope': '기업이 공시한 충격 조건의 민감도. 새 예측·실현손익 아님'}
            for e in pkt['payload']['exposures']]
    mf, mh = _my_scenario((node.get('config') or {}).get('scenario'), pkt['payload']['exposures'])
    mp = _one(inputs, 'macro')
    if not mp:
        return Result('partial', '공시된 민감도 비교만 했습니다. T10(거시 시계열)을 연결하면 실제 지표 변화를 넣은 「이 가정이라면」 계산을 함께 보여 드려요.',
                      {'findings': rows + mf, 'held': ['실제 지표 변화에 따른 계산: T10 미연결', '거시 시나리오 예측'] + mh})
    _check_packet(mp, 'MacroSeries')
    if mp['header']['produced_by']['node_type'] != 'T10':
        raise Integrity('N06의 거시 입력은 T10 결과만 받을 수 있습니다.')
    S = mp['payload']['series']; base_d = '2025-12-31'; F = list(rows); held = [PIT_HOLD, '미래 지표 예측: 하지 않음', '회귀·인과 추정: 하지 않음']
    fx, br = S.get('ECOS_USDKRW', {}).get('obs') or [], S.get('ECOS_BASE_RATE', {}).get('obs') or []
    f0, f1 = _at(fx, base_d), (fx[-1][0], _f(fx[-1][1])) if fx else None
    r0, r1 = _at(br, base_d), (br[-1][0], _f(br[-1][1])) if br else None
    if f0 and f1:
        F.append({'name': '원/달러 환율 관측 변화', 'claim': f"{f0[0]} {f0[1]:,.1f}원 → {f1[0]} {f1[1]:,.1f}원 ({(f1[1] / f0[1] - 1) * 100:+.2f}%)", 'kind': 'fact_official',
                  'formula': '한국은행 ECOS 원/달러 종가, 사업보고서 기준일(2025-12-31) 이후 변화'})
    if r0 and r1:
        F.append({'name': '한국은행 기준금리 관측 변화', 'claim': f"{r0[0][:7]} {r0[1]:.2f}% → {r1[0][:7]} {r1[1]:.2f}% ({r1[1] - r0[1]:+.2f}%p)", 'kind': 'fact_official',
                  'formula': '한국은행 ECOS 기준금리(월), 공개 시차 반영'})
    for e in pkt['payload']['exposures']:
        fs = e.get('fx_struct') or _scen(e.get('fx_scenario'))
        rs = e.get('rate_struct') or _scen(e.get('rate_scenario'))
        if fs and f0 and f1 and abs((f1[1] / f0[1] - 1) * 100) > abs(fs['shock']) + 1e-9:
            held.append(f"{e['name']} 환율 영향: 관측 변화({(f1[1] / f0[1] - 1) * 100:+.2f}%)가 회사가 공시한 충격폭({abs(fs['shock']):g}%)을 넘어 보류(공시 범위 밖으로 늘리지 않음)")
        elif fs and f0 and f1:
            ch = (f1[1] / f0[1] - 1) * 100
            imp = fs['impact_mn'] * ch / fs['shock']
            warn = ' 관측 변화가 공시 충격의 2배를 넘어 비례 가정의 설명력이 약합니다.' if abs(ch) > 2 * fs['shock'] else ''
            F.append({'name': f"{e['name']} 환율 영향 (이 가정이라면)", 'claim': f"원/달러 {ch:+.2f}% → 세전손익 약 {imp:+,.0f}백만원.{warn}", 'value': round(imp),
                      'unit': '백만원', 'kind': 'derived',
                      'formula': f"공시 민감도({fs['shock']:g}% 변동 시 ±{abs(fs['impact_mn']):,.0f}백만원) × 관측 변화 / {fs['shock']:g}%. 다른 변수 일정·선형 비례 가정, 부호는 공시의 ± 대응(원화 약세 = +)을 따름. 실현손익 아님" + (f". {fs['sign_note']}" if fs.get('sign_note') else '') + '.' + _fx_note(e, fs)})
        elif not fs:
            held.append(f"{e['name']} 환율 민감도 숫자를 공시 문장에서 읽지 못함")
        if rs and r0 and r1 and abs(r1[1] - r0[1]) > abs(rs['shock']) + 1e-9:
            held.append(f"{e['name']} 금리 영향: 관측 변화({r1[1] - r0[1]:+.2f}%p)가 회사가 공시한 충격폭({abs(rs['shock']):g}%p)을 넘어 보류(공시 범위 밖으로 늘리지 않음)")
        elif rs and r0 and r1:
            ch = r1[1] - r0[1]
            imp = rs['impact_mn'] * ch / rs['shock']
            F.append({'name': f"{e['name']} 금리 영향 (이 가정이라면)", 'claim': f"기준금리 {ch:+.2f}%p → 세전손익 약 {imp:+,.0f}백만원" + (' (변화 없음)' if ch == 0 else ''),
                      'value': round(imp), 'unit': '백만원', 'kind': 'derived',
                      'formula': f"공시 민감도({rs['shock']:g}%p 변동 시 {rs['impact_mn']:+,.0f}백만원) × 관측 변화 / {rs['shock']:g}%p. 기준금리를 시장금리 변화의 대리값으로 씀, 다른 변수 일정" + (f". {rs['sign_note']}" if rs.get('sign_note') else '')})
        elif not rs:
            held.append(f"{e['name']} 금리 민감도 숫자를 공시 문장에서 읽지 못함")
    return Result('succeeded', '공시된 민감도에 실제 환율·금리 변화를 비례로 넣은 「이 가정이라면」 계산입니다. 예측이나 실현손익이 아닙니다.',
                  {'findings': F + mf, 'held': held + mh, 'base_date': base_d, 'macro_source': mp['payload']['source'],
                   'notice': '회사가 공시한 민감도를 실제 지표 변화에 비례해 늘리거나 줄인 계산입니다. 헤지·다른 변수 변화는 반영하지 않았습니다.'})


def t11(node, inputs, ctx):
    from .market import company_filings, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다. 기업 칸에서 이름으로 골라 주세요.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        fp = company_filings(company, ctx.cutoff, cfg.get('snapshot') or '')
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    years = sorted({f['year'] for f in fp['facts']})
    if not fp['facts'] and not fp['exposures']:
        return Result('held', f"{fp['name']}: 기준시점({fp['last_usable_date']}) 전에 접수된 사업보고서 재무·민감도가 사본에 없습니다.", error_code='no_rows')
    why = (f"{fp['name']} 사업보고서 재무 {len(fp['facts'])}건 ({years[0]}~{years[-1]}년)" if years else f"{fp['name']} 재무 없음") + \
          f", 공시 민감도 {len(fp['exposures'])}건. 공시 API 값(원문 셀 대조 아님)."
    return Result('succeeded' if fp['facts'] else 'partial', why, fp)


# ---------------------------------------------------------------- T08 / N11 / N12 사건·뉴스 (v0.14)
def t08(node, inputs, ctx):
    from .market import news_events, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다. 기업 칸에서 이름으로 골라 주세요.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        ev = news_events(company, ctx.cutoff, cfg.get('snapshot') or '', int(cfg.get('lookback_days') or 180))
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    if not ev['disclosures'] and not ev['news']:
        return Result('held', f"{ev['name']}: {ev['window'][0]}~{ev['window'][1]} 사이 공시·뉴스가 사본에 없습니다.", error_code='no_rows')
    why = (f"{ev['name']} {ev['window'][0]}~{ev['window'][1]}: 공시 {len(ev['disclosures'])}건(공식), 뉴스 제목 {len(ev['news'])}건(포털, 중복 {ev['news_duplicates_removed']}건 합침). "
           '뉴스 본문은 쓰지 않았습니다.')
    return Result('succeeded' if ev['disclosures'] else 'partial', why, ev)


def _events_in(inputs, node_type):
    pkt = _one(inputs, 'events')
    _check_packet(pkt, 'NewsEvents')
    if pkt['header']['produced_by']['node_type'] != 'T08':
        raise Integrity(f'{node_type}은 T08 결과만 받을 수 있습니다.')
    return pkt['payload']


def n11(node, inputs, ctx):
    from collections import Counter
    from .market import EVENT_LABEL
    ev = _events_in(inputs, 'N11')
    F, held, T = [], [], []
    D = ev['disclosures']
    a, b = ev['window']
    cnt = Counter(d['category'] for d in D)
    if D:
        F.append({'name': '공시 건수 (공식)', 'claim': f"{a}~{b} {len(D)}건 — " + ', '.join(f"{EVENT_LABEL[k]} {n}" for k, n in cnt.most_common()),
                  'kind': 'fact_official', 'formula': '접수일 기준 개수, 분류는 보고서명 규칙'})
        key = [d for d in D if not d['routine']]
        T.append({'title': f'주요 공시 {len(key)}건 (반복 공시 {len(D) - len(key)}건 제외: 임원·주요주주 거래, 정기보고서)',
                  'cols': ['날짜', '분류', '보고서명', ''], 'rows': [[d['date'], d['category_label'], d['title'], {'url': d['url'], 'text': '원문'}] for d in reversed(key[-40:])]})
        rec = [d for d in key if d['date'] >= (datetime.fromisoformat(b) - _td(days=30)).date().isoformat()]
        F.append({'name': '최근 30일 주요 공시', 'claim': f"{len(rec)}건" + (': ' + ' / '.join(f"{d['date']} {d['title']}" for d in rec[-5:]) if rec else ''),
                  'kind': 'fact_official', 'formula': '반복 공시 제외'})
    else:
        held.append('공시: 기간 안에 없음')
    N = ev['news']
    if N:
        wk = Counter()
        for n in N:
            d = datetime.fromisoformat(n['date']).date()
            wk[(d - _td(days=d.weekday())).isoformat()] += 1
        weeks = sorted(wk.items())
        last4 = weeks[-4:]
        base = [c for _, c in weeks[:-4]] or [0]
        avg = sum(base) / len(base)
        F.append({'name': '뉴스 제목 건수 (포털)', 'claim': f"{len(N)}건(중복 {ev['news_duplicates_removed']}건 합침). 최근 4주: " + ', '.join(f'{w} 주 {c}건' for w, c in last4) +
                  (f" · 그 이전 주 평균 {avg:.1f}건" if len(weeks) > 4 else ''), 'kind': 'fact_portal', 'formula': '발행일 기준 주(월요일 시작)별 개수'})
        T.append({'title': '최근 뉴스 제목 (최대 15건)', 'cols': ['날짜', '제목', ''], 'rows': [[n['date'], n['title'], {'url': n['url'], 'text': '기사'}] for n in reversed(N[-15:])],
                  'hint': '제목만 보여 줍니다. 기사 내용·사실 여부는 확인하지 않았습니다.'})
    else:
        held.append('뉴스 제목: 기간 안에 없음')
    S = ev['sentiment_daily']
    if S:
        n_sc = sum(int(x['n_scored'] or 0) for x in S)
        tot = sum(float(x['score_sum'] or 0) for x in S)
        half = sorted(S, key=lambda x: x['d'])
        mid = half[len(half) // 2]['d'] if half else b
        def avg_of(rows):
            n_ = sum(int(x['n_scored'] or 0) for x in rows)
            return (sum(float(x['score_sum'] or 0) for x in rows) / n_) if n_ else None
        e1, e2 = avg_of([x for x in S if x['d'] < mid]), avg_of([x for x in S if x['d'] >= mid])
        F.append({'name': '감성 점수 (사전 기반 규칙)', 'claim': f"점수 붙은 글 {n_sc}건, 평균 {tot / n_sc:+.3f}" + (f" · 전반 {e1:+.3f} → 후반 {e2:+.3f} (기준일 {mid})" if e1 is not None and e2 is not None else ''),
                  'kind': 'rule_derived', 'formula': '단어 사전으로 매긴 점수(−1~+1)의 평균. 문맥·반어를 모르는 규칙 값이며 기대·우려의 판단이 아님'} if n_sc else
                 {'name': '감성 점수', 'claim': '점수 붙은 글 없음', 'kind': 'rule_derived'})
    else:
        held.append('감성 점수: 사본에 없음(규칙 점수는 일부 기업·기간만 있음)')
    M = ev['mentions']
    if M:
        q = Counter((m['source'], m['query']) for m in M).most_common(1)[0][0]
        ser = sorted((m['trade_date'], int(m['total'] or 0)) for m in M if (m['source'], m['query']) == q)
        from .attention import mention_line      # v0.27: 누적값 % 대신 하루 새 글(2차 가공)
        ml = mention_line(M)
        if ml:
            F.append(ml)
        elif len(ser) >= 2:
            F.append({'name': f'검색 결과 건수 「{q[1]}」 ({q[0]})', 'claim': f"{ser[0][0]} {ser[0][1]:,} → {ser[-1][0]} {ser[-1][1]:,} (누적값 — 하루 증가량을 만들 기록 부족)",
                      'kind': 'fact_portal', 'formula': '포털 검색 결과 누적 건수(수년 치가 쌓인 값이라 변화율은 관심의 크기를 뜻하지 않음)'})
    if ev['comment_count']:
        F.append({'name': '영상 댓글 수', 'claim': f"{ev['comment_count']:,}건 (내용은 쓰지 않음)", 'kind': 'fact_portal', 'formula': '개수만'})
    if S:
        b0 = datetime.fromisoformat(b).date()
        def _win(lo, hi):
            rs = [x for x in S if lo <= (b0 - datetime.fromisoformat(str(x['d'])[:10]).date()).days <= hi and int(x['n_scored'] or 0)]
            n_ = sum(int(x['n_scored']) for x in rs)
            return n_, len({str(x['d'])[:10] for x in rs}), (sum(float(x['score_sum'] or 0) for x in rs) / n_ if n_ else None)
        (n1, _d1, a1), (n0, d0, a0) = _win(0, 6), _win(7, 13)
        if n1 >= 5 and n0 >= 20 and d0 >= 5:
            F.append({'name': '감성 점수: 최근 7일과 그 직전 7일', 'claim': f"최근 7일 {a1:+.3f}({n1}건) · 직전 7일 {a0:+.3f}({n0}건) · 차이 {a1 - a0:+.3f}", 'value': round(a1 - a0, 3), 'kind': 'rule_derived',
                      'formula': '사전 기반 점수(−1~+1)의 기간 평균과 그 차이. 최근 7일 5건 이상·직전 7일 20건 이상(5일 이상)일 때만 계산. 이 사전 점수는 사람이 읽고 붙인 라벨 440건과 견주어 56.6%만 맞았음(팀 검증값, 긍정을 덜 잡고 중간으로 치우침) — 기대·우려의 판단이 아님'})
        else:
            held.append(f'감성 점수 7일 비교: 점수 붙은 글이 모자람(최근 7일 {n1}건 · 직전 7일 {n0}건/{d0}일 — 5건·20건·5일 이상 필요)')
    if N:
        G = _title_groups(N, b)
        F.append({'name': '비슷한 제목 묶음 (최근 30일)', 'claim': f"3건 이상 묶인 것 {len(G)}개" + (': ' + ' / '.join(f"{g['first']} 「{g['title'][:40]}」 등 {g['n']}건" for g in G[:3]) if G else ''),
                  'value': len(G), 'unit': '개', 'kind': 'derived', 'formula': '제목을 2글자씩 잘라 겹치는 비율(Jaccard)이 0.6 이상이고 3일 안에 나온 기사를 한 묶음으로. 기사 내용·사실 여부는 확인하지 않음'})
        if G:
            T.append({'title': '비슷한 제목 묶음 (최근 30일, 많은 순)', 'cols': ['처음 나온 날', '대표 제목', '건수'], 'rows': [[g['first'], g['title'], g['n']] for g in G[:15]],
                      'hint': '같은 일을 다룬 것으로 보이는 제목을 묶은 것입니다. 건수는 포털 수집 범위 안의 값입니다.'})
    return Result('succeeded' if D and N else 'partial', f"{ev['name']} 사건·관심 현황 {len(F)}건. 공시는 공식, 뉴스·검색은 포털, 감성은 규칙 값입니다. 기대·우려를 판단하지 않습니다.",
                  {'company': ev['company'], 'name': ev['name'], 'as_of': b, 'findings': F, 'held': held, 'tables': T, 'event_source': ev['source'],
                   'notice': '무슨 일이 있었고 얼마나 이야기됐는지의 기록입니다. 좋은 소식·나쁜 소식이나 주가 방향의 판단이 아닙니다.'})


def n12(node, inputs, ctx):
    from statistics import median
    from .market import EVENT_LABEL, index_series, SnapshotError
    ev = _events_in(inputs, 'N12')
    px, rows, _ = _price_inputs(inputs, 'N12')
    if px['company'] != ev['company']:
        return Result('held', f"사건({ev['name']})과 가격({px['name']})의 회사가 다릅니다.", error_code='company_mismatch')
    dates = [r['trade_date'] for r in rows]
    close = [_f(r['close']) for r in rows]
    vol = [_f(r['volume']) for r in rows]
    from .reaction import equal_weight_ex
    mret, blabel = None, None
    try:                                                 # v0.28.2: 기본 비교 기준 = 국내 회사 동일 가중(자기 제외)
        mret, blabel = equal_weight_ex(ctx.cutoff, node['config'].get('snapshot') or '', px['company'])
    except SnapshotError:
        mret = None
    try:
        idx, isrc = index_series(ctx.cutoff, node['config'].get('snapshot') or '', '^KS11')
        idx = dict(idx)
    except SnapshotError:
        idx, isrc = {}, None
    if mret is None:
        blabel = '코스피(비공식 지수)'
    def mkt_cum(i, j):                                   # dates[i]..dates[j] 의 시장 누적 수익률
        if mret is not None:
            acc = 1.0
            for k in range(i, j + 1):
                if dates[k] not in mret:
                    return None
                acc *= 1 + mret[dates[k]]
            return acc - 1
        if idx.get(dates[j]) and idx.get(dates[i - 1]):
            return _f(idx[dates[j]]) / _f(idx[dates[i - 1]]) - 1
        return None
    import bisect
    cats = set(node['config'].get('categories') or ['earnings', 'capital', 'buyback', 'dividend', 'holder', 'deal', 'rumor', 'risk', 'ir'])
    T, per = [], {}
    for d in ev['disclosures']:
        if d['category'] not in cats:
            continue
        i = bisect.bisect_left(dates, d['date'])      # 접수일(장중·장후 미상) 또는 그 다음 거래일 = 0일
        if i >= len(dates) or i == 0:
            continue
        rec = {'date': d['date'], 't0': dates[i], 'cat': d['category'], 'title': d['title']}
        for h in (1, 5, 20):
            j = i + h - 1
            if j < len(dates):
                r = close[j] / close[i - 1] - 1
                m = mkt_cum(i, j)
                ex = None if m is None else r - m
                rec[f'r{h}'], rec[f'x{h}'] = r * 100, (ex * 100 if ex is not None else None)
        base = vol[max(0, i - 20):i]
        rec['vr'] = vol[i] / (sum(base) / len(base)) if base and sum(base) else None
        T.append(rec)
        per.setdefault(d['category'], []).append(rec)
    F, held = [], ['원인 해석·일반화: 하지 않음 (같은 날 다른 사건·시장 변화가 섞임)']
    if not T:
        return Result('partial', '기간 안에 반응을 잴 수 있는 주요 공시가 없습니다.', {'company': ev['company'], 'name': ev['name'], 'findings': [], 'held': held + ['반응 계산: 대상 공시 없음'],
                                                                         'tables': [], 'event_source': ev['source'], 'price_source': px['source']})
    i0 = min(bisect.bisect_left(dates, r['t0']) for r in T)        # 같은 기간 아무 날이나 고른 5거래일 (하락장·상승장 기저)
    b5 = [close[i + 4] / close[i - 1] * 100 - 100 for i in range(max(i0, 1), len(dates) - 4)]
    bx5 = [x for x in ((close[i + 4] / close[i - 1] - 1 - m) * 100 for i in range(max(i0, 1), len(dates) - 4) for m in [mkt_cum(i, i + 4)] if m is not None)]
    base5 = median(b5) if len(b5) >= 20 else None
    if base5 is not None:
        F.append({'name': '기준선: 같은 기간 아무 날이나 고른 5거래일 수익률', 'kind': 'derived',
                  'claim': f"중앙값 {base5:+.2f}% ({len(b5)}개 날짜, {dates[max(i0, 1)]}부터)" + (f", {blabel} 대비 {median(bx5):+.2f}%p" if bx5 else '')
                           + ' — 공시 뒤 반응은 이 기준선과 견주어 보세요. 이 기간 전체가 오르거나 내린 영향이 섞여 있어요',
                  'formula': '기간 첫 공시일부터 마지막까지 모든 거래일을 0일로 두고 잰 5거래일 수익률의 중앙값'})
    else:
        held.append('기준선(같은 기간 아무 날 5거래일 수익률): 날짜가 20개 미만이라 계산하지 않음')
    for k, rs in sorted(per.items(), key=lambda x: -len(x[1])):
        r5 = [r['r5'] for r in rs if r.get('r5') is not None]
        x5 = [r['x5'] for r in rs if r.get('x5') is not None]
        txt = f"{len(rs)}건, 5거래일 수익률 중앙값 {median(r5):+.2f}%" if r5 else f"{len(rs)}건"
        if r5 and base5 is not None:
            txt += f" (기준선보다 {median(r5) - base5:+.2f}%p)"
        if x5:
            txt += f", {blabel} 대비 {median(x5):+.2f}%p"
        if len(rs) < 5:
            txt += ' — 표본 5건 미만이라 경향으로 보지 마세요'
        F.append({'name': f'{EVENT_LABEL[k]} 공시 뒤 반응', 'claim': txt, 'kind': 'derived',
                  'formula': f'0일 = 접수일(장 마감 뒤 접수면 실제 반응은 다음 날). 수익률 = h거래일째 종가 / 0일 전날 종가 − 1. 시장 대비 = 같은 날들의 {blabel} 누적 수익률과의 차이'})
    big = [r for r in T if r.get('vr') and r['vr'] >= 2]
    F.append({'name': '거래량이 20일 평균의 2배 이상이던 공시일', 'claim': f"{len(big)}건 / {len(T)}건" + (': ' + ', '.join(f"{r['t0']} {r['title'][:18]}" for r in big[-4:]) if big else ''),
              'kind': 'derived', 'formula': '0일 거래량 / 직전 20거래일 평균'})
    fm = lambda v: '-' if v is None else f'{v:+.2f}'
    tab = {'title': f'공시별 주가 반응 ({len(T)}건, 수정주가 아님)', 'cols': ['접수일', '0일', '분류', '보고서명', '1일 %', '5일 %', '20일 %', '5일 시장 대비 %p', '거래량 배수'],
           'rows': [[r['date'], r['t0'], EVENT_LABEL[r['cat']], r['title'], fm(r.get('r1')), fm(r.get('r5')), fm(r.get('r20')), fm(r.get('x5')), '-' if r.get('vr') is None else f"{r['vr']:.1f}"] for r in reversed(T)],
           'hint': f'같은 기간 다른 사건이 겹칠 수 있어 공시 때문에 움직였다고 볼 수 없습니다. 같은 날 나온 공시는 따로 세지만 서로 독립된 표본이 아닙니다. 시장 = {blabel}.'}
    if mret is None and not isrc:
        held.append('시장 대비: 비교 기준을 만들 자료 없음')
    return Result('succeeded', f"{ev['name']} 주요 공시 {len(T)}건 뒤 1·5·20거래일 주가·거래량 반응. 원인·일반화 판단이 아닙니다.",
                  {'company': ev['company'], 'name': ev['name'], 'findings': F, 'held': held, 'tables': [tab], 'event_source': ev['source'],
                   'price_source': px['source'], 'index_source': isrc, 'benchmark_label': blabel,
                   'notice': '공시 뒤 주가가 어떻게 움직였는지의 기록입니다. 공시가 원인이라는 뜻도, 다음에도 그렇다는 뜻도 아닙니다.'})


# ---------------------------------------------------------------- N14 수출 통계로 실적 조기 확인 (v0.14)
def _qkey(d):
    y, m = int(d[:4]), int(d[5:7])
    return y, (m - 1) // 3 + 1


def n14(node, inputs, ctx):
    from statistics import median
    fpk = _one(inputs, 'filings'); _check_packet(fpk, 'CompanyFilings')
    mpk = _one(inputs, 'macro'); _check_packet(mpk, 'MacroSeries')
    if mpk['header']['produced_by']['node_type'] != 'T10':
        raise Integrity('N14의 거시 입력은 T10 결과만 받을 수 있습니다.')
    fp, S = fpk['payload'], mpk['payload']['series']
    sid = node['config'].get('export_series') or 'KCS_EXP_854232_USD'
    ex, fx = S.get(sid, {}).get('obs') or [], S.get('ECOS_USDKRW', {}).get('obs') or []
    rev = {(int(q['fiscal_year']), int(q['fiscal_q'])): _f(q['amount']) for q in fp.get('quarters', []) if q['metric'] == 'revenue' and q.get('fiscal_q')}
    if len(rev) < 8 or not ex or not fx:
        return Result('held', f"{fp['name']}: 분기 매출 {len(rev)}개·수출 {len(ex)}개월·환율 {len(fx)}일 — 계산에 필요한 자료(분기 매출 8개 이상)가 부족합니다.",
                      error_code='no_rows')
    exq, n_m = {}, {}
    for d, v in ex:
        k = _qkey(d); exq[k] = exq.get(k, 0) + _f(v); n_m[k] = n_m.get(k, 0) + 1
    fxq = {}
    for d, v in fx:
        fxq.setdefault(_qkey(d), []).append(_f(v))
    full = sorted(k for k in exq if n_m[k] == 3 and k in fxq)
    krw = {k: exq[k] * (sum(fxq[k]) / len(fxq[k])) for k in full}
    ratio = {k: rev[k] / krw[k] for k in full if k in rev and krw[k]}
    ks = sorted(ratio)
    errs = []
    for i in range(4, len(ks)):                      # 과거만으로 다음 분기 맞히기
        w = [ratio[k] for k in ks[i - 4:i]]
        est = median(w) * krw[ks[i]]
        errs.append((ks[i], est / rev[ks[i]] - 1))
    med_err = median(abs(e) for _, e in errs) if errs else None
    target = next((k for k in reversed(full) if k not in rev), None)
    F, held = [], []
    lab = S.get(sid, {}).get('name', sid)
    F.append({'name': '관계 확인에 쓴 자료', 'claim': f"{lab} 분기 합 × 분기 평균 원/달러 vs {fp['name']} 분기 매출 — 겹치는 분기 {len(ks)}개 ({ks[0][0]}Q{ks[0][1]}~{ks[-1][0]}Q{ks[-1][1]})" if ks else '겹치는 분기 없음',
              'kind': 'fact_official', 'formula': '관세청 월간 수출(공개: 다음 달 1일), 한국은행 환율, DART 분기 매출(분기 말+45일 지난 것만)'})
    if med_err is not None:
        F.append({'name': '과거 맞히기 시험 (직전 4분기 비율 유지 가정)', 'claim': f"{len(errs)}회, 오차 중앙값 {med_err * 100:.1f}%, 최대 {max(abs(e) for _, e in errs) * 100:.1f}%. 최근: " +
                  ', '.join(f"{k[0]}Q{k[1]} {e * 100:+.1f}%" for k, e in errs[-4:]), 'kind': 'derived', 'formula': '추정 = 직전 4분기 (매출 ÷ 원화 환산 수출) 중앙값 × 그 분기 원화 수출; 오차 = 추정 / 실제 − 1'})
    ok = med_err is not None and med_err <= 0.15
    if not ok:
        held.append(f"조기 확인 계산: 과거 오차 중앙값 {med_err * 100:.1f}%로 15%를 넘어 이 회사에는 이 방식이 맞지 않습니다(수출 품목 외 사업 비중이 큰 경우)." if med_err is not None else '조기 확인 계산: 과거 시험 불가')
    elif target is None:
        held.append('조기 확인 계산: 수출 3개월이 다 나왔고 매출은 아직 공개 전인 분기가 없습니다(이미 실적이 나온 상태).')
    else:
        w = [ratio[k] for k in ks[-4:]]
        lo, mid, hi = min(w) * krw[target], median(w) * krw[target], max(w) * krw[target]
        F.append({'name': f'{target[0]}년 {target[1]}분기 매출 조기 확인 (이 비율이 유지된다면)', 'value': round(mid),
                  'claim': f"약 {lo / 1e12:,.1f}조 ~ {hi / 1e12:,.1f}조 원 (중앙 {mid / 1e12:,.1f}조). 수출 {exq[target] / 1e8:,.0f}억 달러 × 평균 {sum(fxq[target]) / len(fxq[target]):,.1f}원",
                  'kind': 'forecast_model', 'unit': '원',
                  'formula': '직전 4분기 (매출 ÷ 원화 수출) 비율의 최소·중앙·최대 × 이번 분기 원화 수출. 범위는 「과거 4분기 비율 범위」일 뿐 확률 구간이 아님'})
        qend = f'{target[0]}-{target[1] * 3:02d}-' + ('31' if target[1] in (1, 4) else '30')
        if (datetime.fromisoformat(fp['last_usable_date']) - datetime.fromisoformat(qend)).days > 25:
            held.append('이 분기는 분기 말 뒤 25일이 넘어 잠정실적이 이미 공시됐을 수 있습니다 — 공시가 있으면 공시 값이 우선입니다(T08로 확인).')
    held.append('원인 관계·다음 분기 예측: 하지 않음 (같은 분기 자료의 조기 확인)')
    return Result('succeeded' if ok and target else 'partial',
                  f"{fp['name']} 수출 통계 기반 조기 확인: " + ('계산함' if ok and target else '보류 사유 있음') + '. 모델 추정값이며 실적 공시가 아닙니다.',
                  {'company': fp['company'], 'name': fp['name'], 'findings': F, 'held': held, 'macro_source': mpk['payload']['source'],
                   'backtest': [{'q': f'{k[0]}Q{k[1]}', 'error_pct': round(e * 100, 2)} for k, e in errs],
                   'notice': '수출 통계와 과거 비율로 계산한 모델 추정입니다. 실제 실적 공시가 나오면 그 값이 우선합니다.'})


# ---------------------------------------------------------------- T02 문서 검색 / N04 경쟁력 발췌 / T12·N13 지분 (v0.14)
import hashlib as _hl

T02_PRESETS = {
    'competition': '시장점유율 점유율 경쟁 경쟁요소 업계 현황 시장 규모 경쟁사',
    'holders': '최대주주 특수관계인 지분 소유주식 주주에 관한 사항',
    'risk': '위험 요인 리스크 불확실성 위험관리',
}


def t02(node, inputs, ctx):
    from .rag.shared import get_index, RagUnavailable
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if company not in COMPANIES:
        return Result('held', f'사업보고서 원문은 지금 {", ".join(COMPANIES.values())}만 있습니다.', error_code='company_unknown')
    query = (cfg.get('query') or '').strip() or T02_PRESETS.get(cfg.get('preset') or 'competition', '')
    try:
        idx = get_index(ctx.store.dir)
    except RagUnavailable as e:
        return Result('held', str(e), error_code='no_corpus')
    ctx.step(f'원문 색인 검색: {query[:40]}')
    r = idx.search(query, company=company, k=int(cfg.get('k') or 10) * 2, mode='bm25', synonyms=True)
    last = ctx.cutoff[:10]
    hits, later = [], 0
    for h in r['hits']:
        rc = str(h['source'].get('rcpNo') or h.get('rcpNo') or '')
        c = next((x for x in idx.chunks if x['id'] == h['id']), {})
        rc = rc or str(c.get('rcpNo') or '')
        fd = f'{rc[:4]}-{rc[4:6]}-{rc[6:8]}' if len(rc) >= 8 else None
        if fd and fd > last:
            later += 1
            continue
        hits.append({'rank': len(hits) + 1, 'chunk_id': h['id'], 'chunk_sha256': _hl.sha256(h['text'].encode('utf-8')).hexdigest(),
                     'company': h['company'], 'section': h['section'], 'path': h['path'], 'kind': h['kind'], 'text': h['text'],
                     'rcept_no': rc, 'filed_at': fd, 'year': c.get('year'), 'doc_sha256': h['source'].get('file'), 'url': h['source'].get('url'),
                     'score': h['bm25']})
        if len(hits) >= int(cfg.get('k') or 10):
            break
    if not hits:
        return Result('held', f'「{query}」에 맞는 문단을 찾지 못했습니다' + (f' (기준시점 뒤 보고서 {later}건 제외)' if later else '') + '.', error_code='no_rows')
    return Result('succeeded', f"{COMPANIES[company]} 사업보고서에서 「{query[:30]}」 문단 {len(hits)}개 (BM25, 원문 해시 포함). 검색 순위는 관련도 추정일 뿐입니다.",
                  {'company': company, 'name': COMPANIES[company], 'query': query, 'hits': hits, 'excluded_after_cutoff': later,
                   'index': r['index'], 'kind': 'fact_official',
                   'notes': ['문단 원문 그대로입니다(요약·해석 없음). 각 문단에 원문 파일 해시와 문단 해시를 붙였습니다.']})


_SHARE_RE = re.compile(r'[^.。\n]*?(점유율|시장\s*점유|경쟁사|경쟁\s*업체|경쟁\s*요소|경쟁력|[0-9]+\s*위|선두|1위|시장\s*규모)[^.。\n]*[.。]?')
_NUM_RE = re.compile(r'(\$?\s?[0-9][0-9,.]*\s*(%|억|조|달러|위|백만|천))')


def n04(node, inputs, ctx):
    pkt = _one(inputs, 'docs'); _check_packet(pkt, 'DocPassages')
    d = pkt['payload']
    F, held, rows = [], [], []
    seen = set()
    for h in d['hits']:
        if h['kind'] == 'table' and ('점유율' in h['text'] or '점유율' in ' '.join(h['path'])):
            for line in h['text'].splitlines():          # 점유율 표: 숫자(%) 있는 줄을 그대로
                line = line.strip()
                if '%' in line and line not in seen and len(rows) < 60:
                    seen.add(line)
                    rows.append([h['section'] + ' › ' + ' › '.join(h['path'][1:3]) + ' (표)', line[:400], ', '.join(x[0].strip() for x in _NUM_RE.findall(line)[:6]),
                                 f"{h['chunk_id']} · {h['chunk_sha256'][:10]}"])
            continue
        for m in _SHARE_RE.finditer(h['text']):
            sent = m.group(0).strip()
            if len(sent) < 20 or sent in seen or re.search(r'\d\.$', sent):
                continue
            seen.add(sent)
            nums = [x[0].strip() for x in _NUM_RE.findall(sent)][:6]
            rows.append([h['section'] + ' › ' + ' › '.join(h['path'][1:3]), sent[:400], ', '.join(nums), f"{h['chunk_id']} · {h['chunk_sha256'][:10]}"])
    rows.sort(key=lambda r: 0 if r[2] else 1)            # 숫자가 있는 문장·표 줄 먼저
    pp = _one(inputs, 'peers')
    if pp:
        _check_packet(pp, 'IndustryPeers')
        P = pp['payload']
        chips = [m['name'] for m in P['members'] if m['role'] == 'chip']
        F.append({'name': '함께 볼 비교군 (팀 선정)', 'claim': f"반도체 제조·설계 {len(chips)}곳: {', '.join(chips[:8])}{' 등' if len(chips) > 8 else ''}",
                  'kind': 'fact_official', 'formula': 'T09 비교군 중 역할 규칙상 제조·설계'})
    if rows:
        F.insert(0, {'name': '사업보고서의 경쟁·점유율 관련 문장', 'claim': f"{len(rows)}개 문장 발췌 (숫자 표현 {sum(1 for r in rows if r[2])}개 문장)",
                     'kind': 'fact_official', 'formula': '「점유율·경쟁·순위·시장 규모」가 들어간 문장을 원문 그대로 발췌. 회사가 인용한 외부 조사기관 수치는 회사 공시 속 인용임'})
    else:
        held.append('경쟁·점유율 문장: 검색된 문단에서 찾지 못함 (T02 검색어를 바꿔 보세요)')
    held.append('경쟁력 우열·점유율 전망 판단: 하지 않음')
    return Result('succeeded' if rows else 'partial', f"{d['name']} 사업보고서에서 경쟁·점유율 문장 {len(rows)}개를 원문 그대로 발췌했습니다. 우열을 판단하지 않습니다.",
                  {'company': d['company'], 'name': d['name'], 'findings': F, 'held': held, 'doc_source': {'query': d['query'], 'index': d['index']},
                   'tables': [{'title': '발췌 문장 (원문 그대로)', 'cols': ['위치', '문장', '숫자 표현', '문단 ID · 해시'], 'rows': rows[:40],
                               'hint': '회사 사업보고서 안의 문장입니다. 외부 조사기관 숫자는 회사가 인용한 값입니다.'}],
                   'notice': '경쟁·점유율에 관해 회사가 공시한 문장을 모은 것입니다. 경쟁력이 높다·낮다는 판단이 아닙니다.'})


def t12(node, inputs, ctx):
    from .market import ownership_data, SnapshotError
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다.', error_code='company_unknown')
    ctx.step('Neon 사본 해시 재대조')
    try:
        od = ownership_data(company, ctx.cutoff, cfg.get('snapshot') or '')
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    from . import promise as _PR, dartdocs as _DD
    try:
        _man = _DD.load_manifest()
        if company in (_man.get('listed') or {}):
            od['promise'] = _PR.build(company, ctx.cutoff)
            from . import capital as _CAP                    # v0.37.8 기업가치제고계획 · 자본배분 연표
            from .market import resolve as _rs, load_manifest as _lm, read_rows as _rr
            _root = _rs(cfg.get('snapshot') or ''); _dis, _ = _rr(_root, _lm(_root), 'disclosure', company)
            od['valueup'] = _CAP.valueup(company, ctx.cutoff, od['promise']['retires'])
            od['capalloc'] = _CAP.timeline(company, ctx.cutoff, od['promise'], _dis)
            od['promise']['docs'] = od['promise']['docs'] + od['valueup'].pop('docs') + od['capalloc'].pop('docs')
            od['source']['dart_docs'] = {'origin': 'DART 공시 원문(자기주식 취득 결정·결과보고서·주식 소각 결정·처분·신탁·기업가치제고계획) — OpenDART document.xml, 받은 그대로', 'snapshot': None,
                                         'sha256': _docs_digest(od['promise']['docs']), 'source_grade': 'official', 'file': f"manifest.json 중 이 회사 공시 {len(od['promise']['docs'])}건"}
        else:
            od['promise'] = None; od['promise_held'] = '약속–실행(자사주 취득 이행률·소각 연결): 이 회사의 DART 원문을 아직 받지 않음'
            od['capital_held'] = '기업가치제고계획·자본배분 연표: 이 회사의 DART 원문을 아직 받지 않음'
    except _DD.DartDocsError as e:
        od['promise'] = None; od['promise_held'] = '약속–실행(자사주 취득 이행률·소각 연결): ' + ('DART 원문 사본이 이 PC에 없음' if e.code == 'no_docs' else f'DART 원문 사본을 쓸 수 없음 — {e}')
    if not od['holders'] and not od['reports'] and not (od.get('promise') or {}).get('rows'):
        return Result('held', f"{od['name']}: 최대주주·대량보유 자료가 사본에 없습니다.", error_code='no_rows')
    return Result('succeeded', f"{od['name']} 최대주주 현황 {len(od['holders'])}행, 대량보유 보고 {len(od['reports'])}건, 임원·주요주주 보고 {len(od['insider_dates'])}건 (공시 API).", od)


def _eok(v):
    return f'{v / 1e8:,.0f}억원' if v is not None else '-'



from .capital import VALUEUP_RULE, CAPALLOC_RULE


def _capital_findings(o, F, held, T):
    """v0.37.8 (전태 축, 규칙 valueup-v1 · capalloc-v1): 기업가치제고계획 목표 문장 · 소각 목표 대조 · 자본배분 연표."""
    v, c = o.get('valueup'), o.get('capalloc')
    if v is None and c is None:
        if o.get('capital_held'):
            held.append(o['capital_held'])
        return
    link = lambda u, text='원문': {'url': u, 'text': text} if u else ''
    if v:
        held += v.get('held') or []
        L = v.get('latest')
        if not L:
            F.append({'name': '기업가치제고계획', 'claim': '없음 — 받은 DART 원문에 이 회사의 기업가치제고계획 공시가 없습니다', 'kind': 'fact_official'})
        else:
            tg = [i for i in L['items'] if i['mode'] == 'target']; sf = [i for i in L['items'] if i['mode'] == 'self']
            when = f" · 이 회사 계획 공시 {len(v['plans'])}건 중 가장 최근" if L['date'] == L.get('newest_date') else f" · 가장 최근 공시({L['newest_date']}) 본문에는 숫자 목표가 없어 이 공시의 문장"
            F.append({'name': f"기업가치제고계획 ({L['date']})", 'claim': f"숫자가 있는 목표·계획 문장 {len(tg)}개" + (f", 회사가 적은 이행·성과 문장 {len(sf)}개(검증 전)" if sf else '') + when,
                      'value': len(tg), 'unit': '개', 'kind': 'fact_official', 'formula': '기업가치제고계획(자율공시) 원문 「주요 내용」에서 숫자와 단위(%·억원·조원·만주 등)가 있는 문장만 옮김(160자 이내). 첨부 발표 자료는 읽지 않음',
                      'source': {'title': L['report_nm'], 'url': L['url'], 'rcept_no': L['rcept_no']}})
            for it in tg[:3]:
                F.append({'name': f"계획 문장 · {it['category']}", 'claim': it['text'], 'kind': 'fact_official', 'formula': '원문 문장 그대로(회사가 세운 목표이며, 앱의 전망이 아님)',
                          'source': {'title': L['report_nm'], 'url': L['url'], 'rcept_no': L['rcept_no']}})
            for t in L['retire_targets']:
                F.append({'name': '소각 목표와 그 뒤 소각 결정', 'claim': f"목표 {t['qty']:,}주 · 계획 공시 뒤 소각 결정 {len(t['retires'])}건 합 {t['retired_qty']:,}주 ({t['pct']}%)",
                          'value': t['pct'], 'unit': '%', 'kind': 'derived',
                          'formula': f"{VALUEUP_RULE}: 계획 공시일({L['date']}) 이후 기준시점까지 이 회사가 낸 주식 소각 결정 수량 합 ÷ 계획 문장의 소각 목표 주식 수 × 100. 목표 기간과 그 전 소각분은 따지지 않음(대조만, 판정하지 않음)"})
            if L['items'] and not L['retire_targets']:
                held.append('기업가치제고계획: 주식 수로 적힌 소각 목표 말고는 대조할 공시 자료가 없어 목표 문장만 보이고 판정은 보류')
            T.append({'title': f"기업가치제고계획 — 숫자가 있는 문장 ({L['date']}, 원문 그대로)", 'cols': ['구분', '분류', '문장'],
                      'rows': [[{'target': '목표·계획', 'self': '회사 자체 보고(검증 전)'}.get(i['mode'], '목표·이행 섞임(원문 확인)'), i['category'], i['text']] for i in L['items']] or [['-', '-', '숫자가 있는 문장이 없음(세부는 첨부 자료)']],
                      'hint': '분류(환원·수익성·성장·기타)는 낱말 규칙으로 붙였어요. 회사가 세운 목표를 옮긴 것이고, 앱이 전망하거나 평가한 것이 아니에요.'})
    if c:
        held += c.get('held') or []
        rows = c['rows']
        if rows:
            from collections import Counter
            g = Counter(r['group'] for r in rows)
            F.append({'name': f"자본배분 공시 ({rows[0]['date'][:7]} ~ {rows[-1]['date'][:7]})", 'claim': f"{len(rows)}건 — " + ' · '.join(f'{k} {g[k]}건' for k in ('환원', '보상', '투자', '재편', '조달') if g.get(k)),
                      'value': len(rows), 'unit': '건', 'kind': 'rule_derived',
                      'formula': f"{CAPALLOC_RULE}: 자기주식 취득·처분·신탁·소각은 원문의 목적 문구로 「보상」(임직원·성과급·RSU·주식매수선택권 등)과 그 밖을 나누고, 배당은 환원 · 시설투자·지분 취득은 투자 · 지분 처분·합병·분할·양수도는 재편 · 증자는 조달로 분류. 분류는 규칙이며 평가가 아님"})
            T.append({'title': '자본배분 연표 (최근 순, 2023년 이후)', 'cols': ['날짜', '종류', '분류(규칙)', '내용', '목적(원문)', '원문'],
                      'rows': [[r['date'], r['kind'] + (' · 정정 있음' if r['corrected'] else ''), r['group'], r['content'], (r['purpose'] or '')[:40], link(r['url'])] for r in reversed(rows[-40:])],
                      'hint': (f"배당·투자·재편 공시는 사본 공시 목록에 {c['list_from']} 이후만 있어 그 앞은 비어 있어요. " if c.get('list_from') else '') + '정정 공시는 따로 줄을 만들지 않고 원 공시에 「정정 있음」으로 표시했어요.'})
        else:
            F.append({'name': '자본배분 공시 (2023년 이후)', 'claim': '없음 — 받은 원문과 사본 공시 목록에 자기주식·배당·투자·재편 공시가 없습니다', 'kind': 'fact_official'})

def _promise_findings(o, F, held, T):
    """v0.36.4 (전태 축, 규칙 promise-v1): 자기주식 취득 결정 ↔ 결과보고서 ↔ 소각 결정. 숫자는 DART 원문 칸 값, 이행률·판정 이름은 규칙 산출값."""
    from .promise import OK_RATE, PART_RATE
    pr = o.get('promise')
    if pr is None:
        if o.get('promise_held'):
            held.append(o['promise_held'])
        return
    rows = pr['rows']; link = lambda d, text='원문': {'url': d['url'], 'text': text}
    crit = f'기준(초안): 이행률 {OK_RATE:g}% 이상 「이행」 · {PART_RATE:g}% 이상 「부분 이행」 · 그 아래 「미달」'
    if not rows and not pr['retires']:
        F.append({'name': '자기주식 취득·소각 공시 (2023년 이후)', 'claim': '없음 — 받은 DART 원문에 자기주식 취득 결정·주식 소각 결정이 없습니다', 'kind': 'fact_official', 'formula': 'OpenDART 공시 목록(2023-01-01 이후)에서 해당 종류를 찾은 결과'})
        return
    if rows:
        from collections import Counter
        c = Counter(r['verdict'] or '이행률 보류' for r in rows)
        F.append({'name': '자기주식 취득 약속–실행 (2023년 이후)', 'claim': f"취득 결정 {len(rows)}건 — " + ' · '.join(f'{k} {c[k]}건' for k in ('이행', '부분 이행', '미달', '진행 중', '결과 미확인', '이행률 보류') if c[k]),
                  'value': len(rows), 'unit': '건', 'kind': 'rule_derived', 'formula': '이행률 = 결과보고서의 실제 취득 총액 ÷ 취득 결정의 예정 금액. 짝 = 결과보고서의 「주요사항보고서 제출일」 = 결정 접수일. ' + crit + '. 판정 이름은 규칙에 따른 분류이며 경영진 평가가 아님'})
        for r in rows[-2:]:
            d, rs = r['decision'], r['result']
            F.append({'name': f"자기주식 취득 결정 ({r['filed']})", 'claim': f"{(d['qty'] or 0) + (d['qty_other'] or 0):,}주 · {_eok(r['planned_amount'])} 예정, {d['start']}~{d['end']}, 목적: {d['purpose']}" + (' (정정 공시 반영)' if d.get('corrected') else ''),
                      'kind': 'fact_official', 'formula': '주요사항보고서(자기주식 취득 결정) 원문의 칸 값 그대로', 'source': {'title': d['report_nm'], 'url': d['url'], 'rcept_no': d['rcept_no']}})
            if rs:
                F.append({'name': f"취득 결과 ({r['filed']} 결정)", 'claim': f"{rs['qty']:,}주 · {_eok(r['actual_amount'])} 취득 ({rs['start']}~{rs['end']})" if rs.get('qty') else f"{_eok(r['actual_amount'])} 취득 ({rs['start']}~{rs['end']})",
                          'kind': 'fact_official', 'formula': '자기주식취득결과보고서 원문의 칸 값 그대로', 'source': {'title': rs['report_nm'], 'url': rs['url'], 'rcept_no': rs['rcept_no']}})
            if r['rate'] is not None:
                F.append({'name': f"이행률 ({r['filed']} 결정)", 'claim': f"{r['rate']:.1f}% → 「{r['verdict']}」 ({crit})", 'value': r['rate'], 'unit': '%', 'kind': 'rule_derived',
                          'formula': f"{r['actual_amount']:,}원 ÷ {r['planned_amount']:,}원 × 100. 판정 이름은 규칙에 따른 분류"})
            elif r['verdict']:
                F.append({'name': f"취득 결과 ({r['filed']} 결정)", 'claim': '진행 중 — 취득 예정 기간이 기준 날짜 뒤까지입니다' if r['verdict'] == '진행 중' else '결과 미확인 — 취득 기간이 지났지만 결과보고서를 사본에서 찾지 못했습니다',
                          'kind': 'rule_derived', 'formula': '결과보고서가 없을 때: 취득 예정 종료일이 기준 날짜 뒤면 「진행 중」, 아니면 「결과 미확인」'})
            if r['retire']:
                t = r['retire']
                F.append({'name': f"취득 뒤 소각 결정 ({r['filed']} 결정)", 'claim': f"{t['rcept_dt']} {(t['qty'] or 0) + (t['qty_other'] or 0):,}주 소각 결정" + (f" (소각 예정일 {t['retire_date']})" if t['retire_date'] else ''),
                          'kind': 'fact_official', 'formula': '연결 규칙: 이 결정 뒤에 나온 소각 결정 중 수량 차이가 1% 이내이고 가장 가까운 공시. 숫자는 주식소각결정 원문 그대로',
                          'source': {'title': t['report_nm'], 'url': t['url'], 'rcept_no': t['rcept_no']}})
        T.append({'title': '자기주식 취득 결정과 결과 (2023년 이후, 최근 순)', 'cols': ['결정 접수일', '예정 금액', '실제 취득', '이행률 %', '판정(규칙)', '목적', '뒤이은 소각', '원문'],
                  'rows': [[r['filed'], _eok(r['planned_amount']), _eok(r['actual_amount']), '' if r['rate'] is None else f"{r['rate']:.1f}", r['verdict'] or '보류', (r['decision']['purpose'] or '')[:40],
                            r['retire']['rcept_dt'] if r['retire'] else '', link(r['decision'])] for r in reversed(rows[-30:])], 'hint': crit + '. 금액은 억원 미만을 반올림해 보였고, 이행률은 원 단위 값으로 계산했습니다.'})
    if pr['retires']:
        R = pr['retires']; last = R[-1]; tq = (last['qty'] or 0) + (last['qty_other'] or 0)
        F.append({'name': '주식 소각 결정 (2023년 이후)', 'claim': f"{len(R)}건, 최근: {last['rcept_dt']} {tq:,}주" + (f"(보통주 {last['qty']:,}주는 발행 보통주의 {last['qty'] / last['shares_total'] * 100:.2f}%)" if last.get('shares_total') and last.get('qty') else '') + f" · {_eok(last['amount'])}",
                  'value': len(R), 'unit': '건', 'kind': 'fact_official', 'formula': '주식소각결정 원문의 칸 값. 비율 = 소각 주식 수 ÷ 같은 공시의 발행주식 총수(보통주)', 'source': {'title': last['report_nm'], 'url': last['url'], 'rcept_no': last['rcept_no']}})
        T.append({'title': '주식 소각 결정 (2023년 이후, 최근 순)', 'cols': ['접수일', '소각 주식 수', '발행주식 대비 %', '소각 예정 금액', '소각할 주식', '소각 예정일', '원문'],
                  'rows': [[t['rcept_dt'], f"{(t['qty'] or 0) + (t['qty_other'] or 0):,}", f"{((t['qty'] or 0)) / t['shares_total'] * 100:.2f}" if t.get('shares_total') and t.get('qty') else '', _eok(t['amount']), t['method'] or '', t['retire_date'] or '', link(t)]
                           for t in reversed(R[-30:])]})
    held.extend(pr['held'])
    # v0.37.8: 연표·계획은 _capital_findings가 보임


def n13(node, inputs, ctx):
    pkt = _one(inputs, 'ownership'); _check_packet(pkt, 'OwnershipData')
    o = pkt['payload']
    F, held, T = [], [], []
    H = o['holders']
    years = sorted({int(h['fiscal_year']) for h in H})
    def common(rows):
        tot_row = lambda h: re.sub(r'\s', '', str(h.get('holder') or '')) in ('계', '합계', '소계', '총계', '-')
        return [h for h in rows if not tot_row(h) and ('보통' in str(h.get('stock_kind') or '') or '의결권 있는' in str(h.get('stock_kind') or ''))]
    tot = {}
    for y in years:
        rs = common([h for h in H if int(h['fiscal_year']) == y])
        tot[y] = sum(_f(h['stake_rt']) or 0 for h in rs)
    if years:
        y = years[-1]
        rs = sorted(common([h for h in H if int(h['fiscal_year']) == y]), key=lambda h: -(_f(h['stake_rt']) or 0))
        top = next((h for h in rs if '최대주주' in str(h.get('relate') or '')), rs[0] if rs else None)
        if top:
            F.append({'name': f'최대주주 ({y}년 말, 사업보고서)', 'claim': f"{top['holder']} {top['stake_rt']}% · 특수관계인 포함 합계 {tot[y]:.2f}% ({len(rs)}명)",
                      'kind': 'fact_official', 'formula': '보통주(의결권 있는 주식) 지분율 합. 기준일 ' + str(top.get('settle_dt'))})
        if len(years) > 1:
            F.append({'name': '최대주주 측 합계 변화', 'claim': ' → '.join(f'{yy}년 {tot[yy]:.2f}%' for yy in years), 'kind': 'derived', 'formula': '연말 기준 합계의 차이'})
        T.append({'title': f'{y}년 말 최대주주 및 특수관계인 (보통주)', 'cols': ['주주', '관계', '주식 수', '지분율 %', '기초 %'],
                  'rows': [[h['holder'], h.get('relate') or '', f"{_f(h['end_qty']):,.0f}" if _f(h['end_qty']) else '-', h['stake_rt'], h.get('begin_rt') or ''] for h in rs[:15]]})
    else:
        held.append('최대주주 현황: 사본에 없음')
    R = o['reports']
    if R:
        last = R[-8:]
        F.append({'name': '대량보유(5%) 보고', 'claim': f"{len(R)}건, 최근: " + ' / '.join(f"{r['rcept_dt']} {r['repror']} {r['stkrt']}% ({'+' if (_f(r['stkrt_irds']) or 0) >= 0 else ''}{r['stkrt_irds']}%p, {' '.join(str(r['report_resn'] or '').split())[:60]})" for r in last[-3:]),
                  'kind': 'fact_official', 'formula': '보고자·보유 비율·직전 대비 증감·보고 사유 (공시 그대로)'})
        T.append({'title': '대량보유 보고 (최근 15건)', 'cols': ['접수일', '보고자', '보유 %', '증감 %p', '사유', '형식'],
                  'rows': [[r['rcept_dt'], r['repror'], r['stkrt'], r['stkrt_irds'], r['report_resn'] or '', r['report_tp'] or ''] for r in reversed(R[-15:])]})
    else:
        held.append('대량보유 보고: 기간 안에 없음')
    D = o['insider_dates']
    if D:
        from collections import Counter
        mon = Counter(d[:7] for d in D)
        F.append({'name': '임원·주요주주 소유 보고 건수', 'claim': f"전체 {len(D)}건, 최근 6개월: " + ', '.join(f'{m} {n}건' for m, n in sorted(mon.items())[-6:]),
                  'kind': 'fact_official', 'formula': '「임원ㆍ주요주주특정증권등소유상황보고서」 접수 개수 (매수·매도 방향은 원문 확인 필요)'})
    dk = _one(inputs, 'docs')
    if dk:
        _check_packet(dk, 'DocPassages')
        text = ' '.join(h['text'] for h in dk['payload']['hits'])
        if years:
            y = years[-1]
            rs = sorted(common([h for h in H if int(h['fiscal_year']) == y]), key=lambda h: -(_f(h['stake_rt']) or 0))[:5]
            hit = [h for h in rs if str(h['holder']).replace('㈜', '').replace('(주)', '').strip()[:6] in text]
            stake_hit = [h for h in rs if str(h['stake_rt']) in text]
            F.append({'name': '사업보고서 원문 대조', 'claim': f"상위 {len(rs)}명 중 이름 {len(hit)}명·지분율 숫자 {len(stake_hit)}명이 검색된 원문 문단에 그대로 나옴",
                      'kind': 'derived', 'formula': 'T02가 찾은 「주주에 관한 사항」 문단에 이름·지분율 문자열이 있는지 확인 (문단을 못 찾으면 0일 수 있음)'})
    _promise_findings(o, F, held, T)
    _capital_findings(o, F, held, T)
    held.append('경영권 안정성·지배구조 평가: 하지 않음')
    return Result('succeeded' if H or R or (o.get('promise') or {}).get('rows') else 'partial', f"{o['name']} 최대주주·5% 보고·임원 보고 현황" + (' · 자기주식 약속–실행' if o.get('promise') else '') + f" {len(F)}건 (공시). 지배구조·경영진 평가가 아닙니다.",
                  {'company': o['company'], 'name': o['name'], 'findings': F, 'held': held, 'tables': T, 'owner_source': o['source'],
                   'notice': '누가 얼마나 가지고 있는지의 공시 기록입니다. 경영권·지배구조의 좋고 나쁨을 판단하지 않습니다.'})



# ---------------------------------------------------------------- N15 관계 기록 조사 (v0.17 B)
def n15(node, inputs, ctx):
    from .market import index_series, SnapshotError
    from . import relations as R
    px, rows, dig = _price_inputs(inputs, 'N15')
    mpk = _one(inputs, 'macro'); _check_packet(mpk, 'MacroSeries')
    if mpk['header']['produced_by']['node_type'] != 'T10':
        raise Integrity('N15는 T10 결과만 받을 수 있습니다.')
    ms = mpk['payload']
    cfg = node['config']
    factors = [f for f in (cfg.get('factors') or R.DEFAULT_FACTORS) if f]
    minm = int(cfg.get('min_months') or R.MIN_MONTHS)
    minm = max(minm, R.MIN_MONTHS)                       # 안전장치: 최소 표본을 낮출 수 없다
    last_m = px['last_usable_date'][:7]
    lev = {m: v for m, v in R.monthly_last([(r['trade_date'], _f(r['close'])) for r in rows]).items() if m < last_m}
    stock = R.changes(lev)
    if len(stock) < minm:
        return Result('held', f"{px['name']} 월간 수익률이 {len(stock)}개월뿐이라 관계를 재지 않습니다(최소 {minm}개월). 가격 자료를 더 길게(1,300거래일) 불러오세요.",
                      error_code='too_short')
    snap = cfg.get('snapshot') or ''
    recs, tabrows, F, held, isrc = [], [], [], [], None
    for fid in factors:
        if fid in R.INDEX_FACTORS:
            try:
                pts, isrc = index_series(ctx.cutoff, snap, fid)
            except SnapshotError as e:
                held.append(f'{R.INDEX_FACTORS[fid]}: {e}'); continue
            name, freq, src, diff, pub = R.INDEX_FACTORS[fid], 'D', 'yfinance(비공식)', False, 0
        else:
            s = (ms.get('series') or {}).get(fid)
            if not s or not s.get('obs'):
                held.append(f'{fid}: 기준시점에 공개된 관측이 없습니다.'); continue
            pts, name, freq, src = s['obs'], s['name'], s.get('frequency') or 'D', s.get('source')
            diff = fid in R.LEVEL_DIFF
            pub = 0 if freq == 'D' else (1 if src == 'kcs' else (3 if freq == 'Q' else 2))
            if freq == 'Q':
                held.append(f'{name}: 분기 지표라 월간 관계를 재지 않습니다.'); continue
        fl = {m: v for m, v in R.monthly_last([(str(d)[:10], v) for d, v in pts]).items() if m < last_m}
        fc = R.changes(fl, diff)
        rec = R.record(stock, fc, pub_lag=pub, min_months=minm)
        rec.update({'factor': fid, 'factor_name': name, 'source': src, 'frequency': freq, 'change': '%p 차이' if diff else '% 변화', 'pub_lag_months': pub})
        recs.append(rec)
        if rec['grade'] == 'too_few':
            held.append(f"{name}: 겹치는 달이 {rec['n']}개월뿐이라 계산하지 않습니다(최소 {minm}개월)."); continue
        lag_txt = '같은 달' if rec['best_lag'] == 0 else f"{rec['best_lag']}개월 앞선 {name} 변화"
        lo, hi = rec['ci_adjusted']
        claim = (f"{lag_txt} ↔ 주가 월간 수익률: 상관 {rec['r']:+.2f} (보정 범위 {lo:+.2f}~{hi:+.2f}, {rec['n']}개월). "
                 f"{rec['grade_label']}. 인과 아님.")
        F.append({'name': f'{name}와(과) 주가의 관계 기록', 'claim': claim, 'kind': 'derived', 'value': round(rec['r'], 4), 'unit': '상관계수',
                  'formula': (f"월말 종가 수익률 vs {name} 월말 {rec['change']}, 시차 0~{R.MAX_LAG}개월 중 |상관| 최대. "
                              f"범위 = Fisher 변환, {rec['lags_tested']}개 시차를 시험해 z={rec['z_adjusted']:.2f}로 넓힘. "
                              f"앞·뒤 절반 {_fmt_r(rec['halves']['first'])} / {_fmt_r(rec['halves']['second'])}"
                              + (f". 과거 맞히기: 뒤 {rec['oos']['test_months']}개월 맞힌 비율 {rec['oos']['hit']*100:.0f}% vs 기준선 {rec['oos']['baseline']*100:.0f}%" if rec.get('oos') else ''))})
        tabrows.append([name, '같은 달' if rec['best_lag'] == 0 else f"{rec['best_lag']}개월 앞", f"{rec['r']:+.2f}", f'{lo:+.2f}~{hi:+.2f}', str(rec['n']),
                        f"{_fmt_r(rec['halves']['first'])} / {_fmt_r(rec['halves']['second'])}",
                        (f"{rec['oos']['hit']*100:.0f}% / {rec['oos']['baseline']*100:.0f}%" if rec.get('oos') else ('대상 아님(같은 달)' if not rec['known_before'] else '시험 표본 부족')),
                        rec['grade_label']])
    done = [r for r in recs if r['grade'] != 'too_few']
    held.append('원인 해석·앞으로의 방향 판단: 하지 않음 (관계의 기록일 뿐)')
    if not done:
        return Result('held', '관계를 잴 수 있는 지표가 없습니다(표본 부족 또는 공개된 관측 없음).', error_code='too_short')
    tab = {'title': f"{px['name']} 관계 기록표 ({stock and min(stock)}~{max(stock)}, 월간)",
           'cols': ['지표', '시차', '상관', '보정 범위', '개월', '앞 절반 / 뒤 절반', '과거 맞히기 / 기준선', '기록 등급'], 'rows': tabrows,
           'hint': R.NOTICE}
    return Result('succeeded', f"{px['name']} 월간 수익률과 지표 {len(done)}종의 관계 기록(인과 아님). 표본·기간 나눔·과거 맞히기 시험을 거쳤습니다.",
                  {'company': px['company'], 'name': px['name'], 'findings': F, 'held': held, 'tables': [tab], 'relations': recs,
                   'months': {'from': min(stock), 'to': max(stock), 'n': len(stock), 'dropped_partial_month': last_m},
                   'price_source': px['source'], 'macro_source': ms.get('source'), 'index_source': isrc, 'notice': R.NOTICE,
                   'kind': 'derived'})


def _fmt_r(v):
    return '-' if v is None else f'{v:+.2f}'


# ---------------------------------------------------------------- T13·N16 증권사 전망 추이·집계 (v0.18)
def t13(node, inputs, ctx):
    import hashlib
    from .broker import broker_dir, load_manifest, report_ticker
    co = str(node['config'].get('company') or '005930')
    cut = ctx.cutoff[:10]
    reports, cands = ctx.store.broker_reports()
    man = load_manifest(broker_dir())
    mine = [r for r in reports if (r.get('ticker') or report_ticker(man.get(r['file']))) == co]
    if not mine:
        return Result('held', '이 회사의 증권사 보고서가 아직 없습니다. 전문가 모드 「증권사 전망」에서 보고서를 등록·스캔·승인하세요.', error_code='no_reports')
    ctx.step('보고서 PDF 해시 재확인')
    F, used, later, changed, pending = [], [], 0, [], 0
    okfiles = set()
    for r in sorted(mine, key=lambda r: (r['report_date'], r['broker'])):
        if str(r['report_date'])[:10] > cut:
            later += 1
            continue
        pdf = broker_dir() / r['file']
        if not pdf.exists() or hashlib.sha256(pdf.read_bytes()).hexdigest() != r['sha256']:
            changed.append(r['file']); continue
        okfiles.add((r['file'], r['sha256']))
        ok = [c for c in cands if c['file'] == r['file'] and c['sha256'] == r['sha256'] and c['state'] == 'approved']
        pending += sum(1 for c in cands if c['file'] == r['file'] and c['state'] == 'proposed')
        if not ok:
            continue
        used.append({k: r.get(k) for k in ('file', 'sha256', 'broker', 'report_date', 'title', 'source_url', 'past_check')})
        for c in ok:
            F.append({'id': c['id'], 'broker': c['broker'], 'report_date': c['report_date'], 'fiscal_year': c['fiscal_year'], 'metric': c['metric'],
                      'metric_label': c['metric_label'], 'value': c['effective_value_mn'], 'unit': '백만원', 'edited': bool(c.get('review_value_mn')),
                      'source': {'file': r['file'], 'sha256': r['sha256'], 'page': c['page'], 'quote': c['quote'], 'url': r.get('source_url')},
                      'kind': 'forecast_external'})
    # v0.24: 분기 전망·순이익 전망(새 표). 해시가 확인된 보고서(위 used)와 같은 파일·해시만, 기준 날짜 뒤 보고서는 빼고.
    QF, NF = [], []
    for v in (ctx.store.v2_forecasts(co) if hasattr(ctx.store, 'v2_forecasts') else []):
        if (v['file'], v['sha256']) not in okfiles or str(v['report_date'])[:10] > cut:
            continue
        item = {'id': v['id'], 'broker': v['broker'], 'report_date': v['report_date'], 'fiscal_year': int(v['fiscal_year']), 'metric': v['metric'],
                'value': v['value_mn'], 'unit': '백만원', 'auto': v.get('reviewer'), 'source': {'file': v['file'], 'sha256': v['sha256'], 'page': v.get('page'), 'quote': v.get('quote')},
                'kind': 'forecast_external'}
        if v['kind'] == 'quarter':
            QF.append(item | {'quarter': int(v['quarter'])})
        elif v['metric'] == 'netIncome':
            NF.append(item)
    if not F:
        why = '기준 날짜까지 나온 보고서 중 승인된 전망이 없습니다' + (f' (미승인 {pending}건)' if pending else '') + '.'
        return Result('held', why, error_code='no_approved')
    try:
        from .market import company_name
        name = COMPANIES.get(co) or company_name(co)
    except Exception:
        name = COMPANIES.get(co, co)
    held = []
    if changed:
        held.append(f'파일이 바뀌었거나 없는 보고서 {len(changed)}건은 뺐습니다(다시 스캔·승인 필요).')
    st = 'partial' if (changed or pending) else 'succeeded'
    return Result(st, f'{name} 증권사 보고서 {len(used)}건의 승인된 실적 전망 {len(F)}개. 외부 전망이며 사실이 아닙니다.' + (f' 기준 날짜 뒤 보고서 {later}건은 쓰지 않았습니다.' if later else ''),
                  {'company': co, 'name': name, 'forecasts': F, 'reports': used, 'excluded_after_cutoff': later, 'pending': pending, 'held': held,
                   **({'quarter_forecasts': QF} if QF else {}), **({'net_income_forecasts': NF} if NF else {}),
                   'kind': 'forecast_external', 'notice': '증권사 외부 전망입니다. 사람이 승인한 값만 담았습니다.'})


def n16(node, inputs, ctx):
    from decimal import Decimal as _D
    from . import forecasts as FC
    lpk = _one(inputs, 'ledger'); _check_packet(lpk, 'ForecastLedger')
    L = lpk['payload']
    fpk = _one(inputs, 'filings')
    actual = {}
    fsrc = None
    if fpk:
        _check_packet(fpk, 'CompanyFilings')
        for f in fpk['payload'].get('facts', []):
            if f['metric'] in FC.METRICS and f.get('amount') not in (None, ''):
                actual[(int(f['year']), f['metric'])] = (str(_D(str(f['amount'])) / _D(1000000)), f.get('filed_at'), f.get('rcept_no'))
        fsrc = fpk['payload'].get('source')
    keys = sorted({(int(f['fiscal_year']), f['metric']) for f in L['forecasts']}, key=lambda k: (k[0], 0 if k[1] == 'operatingProfit' else 1))
    F, T, trends, held, vs, pend_years = [], [], {}, [], [], set()
    jo = lambda v: f"{_D(str(v)) / _D(1000000):,.1f}조" if abs(_D(str(v))) >= 1000000 else f"{_D(str(v)) / _D(100):,.0f}억"   # v0.24: 1조 미만은 억
    for fy, m in keys:
        tr = FC.trend(L['forecasts'], m, fy, ctx.cutoff[:10])
        if not tr:
            continue
        trends[f'{fy}:{m}'] = tr
        last = tr['latest']
        lab = f"{fy}년 {FC.METRICS[m]}"
        rv = tr['revisions']
        claim = (f"증권사 {last['n']}곳의 최신 승인 전망 집계 중앙값 {jo(last['median'])} (범위 {jo(last['min'])}~{jo(last['max'])}, {last['date']} 기준). "
                 f"{tr['first']['date']} 이후 중앙값 {tr['median_move_pct']}% · 상향 {len(rv['up'])}·하향 {len(rv['down'])}·유지 {len(rv['flat'])}. 컨센서스 아님.")
        if last['thin']:
            claim += f' 보고서 {FC.MIN_REPORTS}건 미만이라 추이로 보지 마세요.'
        F.append({'name': f'{lab} 증권사 전망 집계', 'claim': claim, 'kind': 'forecast_external', 'value': last['median'], 'unit': '백만원',
                  'formula': f'날짜마다 증권사별 최신 전망(그날까지 나온 것, {FC.STALE_DAYS}일 넘은 것 제외)의 중앙값·최솟값·최댓값. 상향·하향은 같은 증권사의 앞뒤 보고서 비교(±{FC.FLAT_PCT}% 안은 유지). 중앙값 변화에는 모인 증권사 수가 바뀐 효과도 섞여 있음.'})
        a = actual.get((fy, m))
        if a and a[1] and a[1] <= ctx.cutoff[:10]:
            cmp = FC.versus_actual(tr, a[0], a[1])
            if cmp:
                vs.append({'key': f'{fy}:{m}', **cmp, 'rcept_no': a[2]})
                F.append({'name': f'{lab} 실제 vs 공시 전 집계', 'kind': 'derived', 'value': cmp['gap_pct'], 'unit': '%',
                          'claim': f"실제 {jo(cmp['actual'])}(공시 {cmp['disclosed']}) vs 공시 전날까지 집계 중앙값 {jo(cmp['median'])}({cmp['n']}건): 차이 {cmp['gap_pct']}%, "
                                   + ('집계 범위 안' if cmp['inside_range'] else '집계 범위 밖') + '.',
                          'formula': '실제 ÷ 공시 전날까지의 집계 중앙값 − 1 (사후 기록)'})
        else:
            pend_years.add(fy)
        for b, pts in sorted(tr['per_broker'].items()):
            T.append([lab, b, ' → '.join(f"{p['date'][5:]} {jo(p['value'])}" for p in pts)])
    if pend_years:
        held.append(f"{'·'.join(str(y) for y in sorted(pend_years))}년 실제 실적: 아직 사업보고서 공시 전이에요. 공시되면 「실제 vs 공시 전 집계」를 자동으로 기록해요.")
    held.append('목표주가·투자의견은 일부러 다루지 않습니다 (전문가 모드 비교표에만 있음).')
    QT = []
    qsc = _quarter_scorecard(L, fpk['payload'] if fpk else None, jo)
    if qsc:
        F += qsc['findings']
        QT = [[f"{x['period']} {FC.METRICS.get(x['metric'], x['metric'])}", x['broker'],
               f"{x['report_date'][5:]} {jo(x['forecast_mn'])}" + (f" · 실제 {jo(x['actual_mn'])} ({x['error_pct']}%)" if x['status'] == 'scored' else ' · 실제 대기')] for x in qsc['rows']]
    if not trends:
        return Result('held', '집계할 전망이 없습니다.', error_code='no_rows')
    return Result('succeeded', f"{L['name']} 증권사 실적 전망 {len(trends)}개 항목의 날짜별 집계와 수정 추이. 외부 전망의 집계이며 컨센서스가 아닙니다.",
                  {'company': L['company'], 'name': L['name'], 'findings': F, 'held': held, 'trends': trends, 'versus_actual': vs,
                   'tables': [{'title': '증권사별 전망 변화 (승인된 값)', 'cols': ['항목', '증권사', '보고서 날짜 → 전망'], 'rows': T, 'hint': FC.NOTICE}]
                             + ([{'title': '분기 전망 성적표 (증권사별 마지막 전망 vs 실제)', 'cols': ['분기·항목', '증권사', '마지막 전망 · 실제'], 'rows': QT,
                                  'hint': qsc['notice']}] if QT else []),
                   'reports': L.get('reports'), 'filings_source': fsrc, 'notice': FC.NOTICE, 'kind': 'forecast_external',
                   **({'quarter_scorecard': {k: qsc[k] for k in ('periods', 'rows', 'notice')}} if qsc else {})})


def _quarter_scorecard(L, fp, jo):
    """v0.24 분기 전망 성적표: 증권사마다 「실적이 처음 알려지기 전날까지」 마지막 분기 전망 vs DART 정기보고서 분기값.
    실적이 처음 알려진 날 = 분기 말 뒤 첫 잠정실적 공시일과 정기보고서 접수일 중 이른 날. 그날 이후 보고서는 채점하지 않는다."""
    from decimal import Decimal as _D
    from statistics import median
    from .broker_quarter import scorecard, known_date
    QF = L.get('quarter_forecasts') or []
    if not QF or not fp:
        return None
    co = L['company']
    qa = {(co, int(a['fiscal_year']), int(a['quarter']), a['metric']): _D(a['value_mn']) for a in fp.get('quarter_actuals', [])}
    qfiled = {(int(a['fiscal_year']), int(a['quarter'])): a['filed_at'] for a in fp.get('quarter_actuals', []) if a.get('filed_at')}
    pre = fp.get('prelim_dates', [])
    known = {(co, y, q): known_date(y, q, pre, qfiled) for (y, q) in {(f['fiscal_year'], f['quarter']) for f in QF}}
    rows = scorecard([{'ticker': co, 'broker': f['broker'], 'report_date': str(f['report_date'])[:10], 'fiscal_year': f['fiscal_year'], 'quarter': f['quarter'],
                       'metric': f['metric'], 'value_mn': f['value']} for f in QF], qa, known)
    periods, findings = [], []
    keys = sorted({(r['period'], r['metric']) for r in rows}, key=lambda k: (k[0], 0 if k[1] == 'operatingProfit' else 1))
    first_wait = next((p for p, m in keys if any(r['status'] == 'awaiting' for r in rows if r['period'] == p)), None)
    lab = {'revenue': '매출액', 'operatingProfit': '영업이익'}
    for p, m in keys:
        rs = [r for r in rows if r['period'] == p and r['metric'] == m]
        sc = [r for r in rs if r['status'] == 'scored']
        med = median(float(r['forecast_mn']) for r in rs) * 1e6
        item = {'period': p, 'metric': m, 'n': len(rs), 'median_forecast_mn': format(_D(str(med / 1e6)).quantize(_D(1)), 'f'), 'status': 'scored' if sc else 'awaiting',
                'known_date': rs[0]['known_date']}
        if sc:
            errs = [abs(float(r['error_pct'])) for r in sc]
            item.update(actual_mn=sc[0]['actual_mn'], median_abs_error_pct=round(median(errs), 1), within5=sum(e <= 5 for e in errs))
            findings.append({'name': f"{p} {lab.get(m, m)} 분기 전망 성적표", 'kind': 'derived', 'unit': '%', 'value': item['median_abs_error_pct'],
                             'claim': f"실제 {jo(sc[0]['actual_mn'])} vs 증권사 {len(sc)}곳의 「실적이 알려지기 전날까지」 마지막 전망: 오차 절댓값 중앙값 {item['median_abs_error_pct']}%, "
                                      f"5% 안에 든 곳 {item['within5']}곳. 지난 기록이며 앞으로의 정확도를 보장하지 않음.",
                             'formula': '증권사별 (마지막 전망 − 실제) ÷ |실제|. 실제 = DART 정기보고서 분기값(4분기 = 연간 − 3분기 누적). 기준일 = 첫 잠정실적 공시일과 정기보고서 접수일 중 이른 날'})
        elif p == first_wait:
            findings.append({'name': f"{p} {lab.get(m, m)} 분기 전망 (채점 대기)", 'kind': 'forecast_external', 'unit': '백만원', 'value': item['median_forecast_mn'],
                             'claim': f"증권사 {len(rs)}곳의 마지막 분기 전망 중앙값 {jo(item['median_forecast_mn'])}. 실제 분기 실적이 정기보고서로 공시되면 자동으로 채점해요.",
                             'formula': '증권사별 마지막 분기 전망의 중앙값 (승인된 값, 컨센서스 아님)'})
        periods.append(item)
    return {'periods': periods, 'rows': rows, 'findings': findings,
            'notice': '분기 전망 성적표: 각 증권사가 실적이 알려지기 전에 낸 마지막 분기 전망과 실제를 견준 지난 기록이에요. 어느 증권사가 앞으로 더 맞힐지를 뜻하지 않아요.'}


# ---------------------------------------------------------------- N17 기대 부채 지수(EDI) (v0.19, KIRI 시간자본론)
def _pct(cfg, k, lo, hi):
    from . import edi as E
    v = cfg.get(k)
    v = E.DEFAULTS[k] if v in (None, '') else float(v)
    if not lo <= v <= hi:
        raise ValueError(f'{k} 값은 {lo}~{hi}% 범위여야 합니다.')
    return v / 100


def _edi_quarters(fp):
    """DART 정기보고서에서 만든 분기(실제 접수일)를 우선, 없으면 분기 재무 표(분기 말 + 45일)."""
    from . import edi as E
    dq = fp.get('dart_quarters') or []
    if len([q for q in dq if q.get('equity') is not None and q.get('ni') is not None]) >= 4:
        return dq, 'DART 정기보고서 분기·반기·사업보고서 (공개일 = 실제 접수일)'
    return E.quarter_table(fp.get('quarters') or []), '분기 재무 표 (공개일 = 분기 말 + 45일로 가정)'


def n17(node, inputs, ctx):
    from . import edi as E
    from . import forecasts as FC
    p, rows, dig = _price_inputs(inputs, 'N17')
    fpk = _one(inputs, 'filings'); _check_packet(fpk, 'CompanyFilings')
    if fpk['header']['produced_by']['node_type'] != 'T11':
        raise Integrity('N17은 T11 결과만 받을 수 있습니다.')
    fp = fpk['payload']
    if fp.get('company') != p['company']:
        raise Integrity(f"가격({p['company']})과 재무({fp.get('company')})의 회사가 다릅니다.")
    cfg = node['config']
    try:
        r = _pct(cfg, 'cost_of_equity', 3, 20); g_lt = _pct(cfg, 'long_growth', -2, 5); g = _pct(cfg, 'edi_growth', 1, 30)
    except (TypeError, ValueError) as e:
        return Result('held', f'가정 값이 올바르지 않습니다: {e}', error_code='bad_config')
    if g_lt >= r:
        return Result('held', '장기성장률은 자기자본비용보다 작아야 합니다.', error_code='bad_config')
    extra_raw = str(cfg.get('extra_shares') or '').replace(',', '').strip()
    try:
        extra = float(extra_raw) if extra_raw else 0.0
        if extra < 0: raise ValueError
    except ValueError:
        return Result('held', '보통주 외 주식 수는 0 이상의 숫자로 적어 주세요.', error_code='bad_config')
    qt, qsrc = _edi_quarters(fp)
    if not qt:
        return Result('held', f"{p['name']}: 분기 재무(자본·순이익)가 사본에 없어 계산하지 않습니다.", error_code='no_quarters')
    ctx.step('날짜별로 그때 공개된 분기만 골라 계산')
    pts = E.series(rows, qt, r, g_lt, g, extra)
    if not pts:
        return Result('held', '분기 재무가 4분기 이상 이어지는 날짜가 없어 계산하지 않습니다.', error_code='too_short')
    now = pts[-1]; last = rows[-1]; d = now['date']
    fu = E.fundamentals_at(qt, d)
    sh = E.shares_at(last, extra)
    jo = lambda x: f'{x / 1e12:,.1f}조원' if abs(x) >= 1e12 else f'{x / 1e8:,.0f}억원'   # v0.22: 1조 미만은 억원으로
    src = {'packet_digest': dig, 'snapshot': p['source']['snapshot']}
    asm = f"자기자본비용 r {r*100:g}% · 장기성장 {g_lt*100:g}% · EDI 기준 연 성장률 g {g*100:g}% (설정에서 바꿀 수 있음)"
    F, held, T = [], [], []
    F.append({'name': '쓴 자료', 'kind': 'fact_official', 'as_of': d, 'source': src,
              'claim': f"{d} 종가 {now['P']:,.0f}원 · {fu['end']} 분기 말 자본총계 {jo(fu['B'])} · 최근 4분기 순이익 {jo(fu['ni_ttm'])} "
                       f"(이 분기는 {fu['available_from']}부터 썼음 · {qsrc})"})
    F.append({'name': 'ROE 두 가지', 'kind': 'derived', 'as_of': fu['end'], 'unit': '%', 'value': round(fu['roe_norm'] * 100, 2),
              'claim': f"최근 {fu['n_norm']}분기 평균(연환산) {fu['roe_norm']*100:.1f}% · 최근 4분기 {fu['roe_ttm']*100:.1f}%",
              'formula': '순이익 합 ÷ 같은 기간 평균 자본총계 (최근 12분기는 4/n 배로 연환산). 자본총계는 비지배지분 포함'})
    for m, lab in E.METHODS:
        V, e = now['V_' + m], now['EDI_' + m]
        if e is None:
            held.append(f'{lab}: ROE가 장기성장률 이하라 V가 0 이하 — 이 방식의 EDI는 계산하지 않음(보류)')
            continue
        F.append({'name': f'주가가 실적보다 앞선 햇수 — {lab}', 'kind': 'assumption_illustrative', 'unit': '년', 'value': round(e, 2), 'as_of': d,
                  'claim': f"주가 {now['P']:,.0f}원 ÷ 실적이 받치는 가치 V {V:,.0f}원 = {now['P']/V:.2f}배 → EDI {e:+.1f}년"
                           + (f' (실적이 주가보다 약 {-e:.1f}년 앞서 있음 — 주가가 지금 실적도 다 반영하지 않음)' if e < 0 else f' (주가가 실적보다 약 {e:.1f}년 앞서 있음 — 실적이 연 {g*100:g}%씩 그만큼 자라야 지금 주가에 닿음)')
                           + (f' ⚠ ROE가 장기성장률에 {E.STABLE_GAP*100:g}%p 안으로 가까워 V가 작게 나오는 구간 — 햇수가 과장됨' if now.get('unstable_' + m) else ''),
                  'formula': ('V = 자본 × (ROE − 장기성장) ÷ (r − 장기성장) ÷ 주식 수; ' if m != 'book' else 'V = 자본 ÷ 주식 수; ')
                             + 'EDI = ln(주가 ÷ V) ÷ ln(1 + g). ' + asm})
    req = E.required_roe(now['P'], sh, fu['B'], r, g_lt)
    F.append({'name': '지금 주가가 요구하는 ROE', 'kind': 'assumption_illustrative', 'unit': '%', 'value': round(req * 100, 2), 'as_of': d,
              'claim': f"지금 주가가 V와 같아지려면 ROE {req*100:.1f}%가 계속돼야 함 — 실제 최근 4분기 {fu['roe_ttm']*100:.1f}%, 3년 평균 {fu['roe_norm']*100:.1f}%. "
                       f"필요한 연 순이익 약 {jo(req * fu['B'])}",
              'formula': 'ROE* = 장기성장 + (r − 장기성장) × 시가총액 ÷ 자본. ' + asm})
    # 증권사 전망이 맞다면 (목표주가가 아니라 실적 전망만 씀)
    lpk = _one(inputs, 'ledger')
    if lpk:
        _check_packet(lpk, 'ForecastLedger')
        L = lpk['payload']
        yrs = sorted({int(f['fiscal_year']) for f in L['forecasts'] if f['metric'] == 'operatingProfit' and int(f['fiscal_year']) >= int(d[:4])})
        ratio, ratio_basis = E.ni_op_ratio(fu)          # v0.22: 적자 기업도 더 긴 기간 비율 → 기본 가정 순으로 환산
        for fy in yrs[:2]:
            tr = FC.trend(L['forecasts'], 'operatingProfit', fy, ctx.cutoff[:10])
            if not tr or ratio is None:
                continue
            lt = tr['latest']
            op_f = float(lt['median']) * 1e6
            # v0.24: 같은 연도의 순이익(연결 당기순이익) 전망이 승인돼 있으면 비율 환산 대신 그 값을 쓴다
            trn = FC.trend(L.get('net_income_forecasts') or [], 'netIncome', fy, ctx.cutoff[:10])
            if trn and not trn['latest'].get('thin'):
                ni_f, nlt = float(trn['latest']['median']) * 1e6, trn['latest']
                used_ni = f"{fy}년 순이익 증권사 {nlt['n']}곳 승인 전망 집계 중앙값 {jo(ni_f)}(영업이익 환산 아님)"
            else:
                ni_f, used_ni = op_f * ratio, None
            roe_f = ni_f / fu['B']
            Vf = E.value(fu['B'], roe_f, r, g_lt)
            ef = E.edi(now['P'], Vf / sh if Vf else None, g)
            claim = (used_ni + f", ROE 약 {roe_f*100:.1f}%. " if used_ni else
                     f"{fy}년 영업이익 증권사 {lt['n']}곳 승인 전망 집계 중앙값 {jo(op_f)} × {ratio_basis} {ratio:.2f} → 순이익 약 {jo(op_f*ratio)}, ROE 약 {roe_f*100:.1f}%. ")
            if (ni_f if used_ni else op_f) <= 0:
                claim += '전망 이익이 0 이하라 계산하지 않음.'
                continue
            if ef is None:
                claim += '이 ROE로는 V가 0 이하라 EDI를 계산하지 않음.'
            else:
                claim += (f"이 수익성이 계속 이어진다면 V {Vf/sh:,.0f}원, EDI {ef:+.1f}년. 거꾸로 보면 지금 주가는 이 전망 순이익의 {req*fu['B']/ni_f*100:.0f}%({jo(req * fu['B'])})가 영구히 이어지는 것과 같은 가격.")
            if lt.get('thin'):
                claim += f' 보고서 {FC.MIN_REPORTS}건 미만 — 대표성 없음.'
            F.append({'name': f'증권사 전망이 맞다면 ({fy}년)', 'kind': 'forecast_external', 'unit': '년', 'value': None if ef is None else round(ef, 2), 'as_of': lt['date'],
                      'claim': claim, 'ratio_basis': '순이익 전망 직접' if used_ni else ratio_basis,
                      'formula': ('외부 전망(연결 당기순이익, 증권사 3곳 이상 집계 중앙값) ÷ 최근 자본 = 전망 ROE → 같은 V·EDI 식. ' if used_ni else
                                  '외부 전망(영업이익) × 순이익/영업이익 비율(최근 4분기 → 최근 12분기 → 기본 0.76 순) ÷ 최근 자본 = 전망 ROE → 같은 V·EDI 식. ') + '컨센서스·목표주가 아님. ' + asm})
        if not yrs:
            held.append('증권사 영업이익 전망: 올해 이후 연도의 승인된 전망이 없음')
        elif not ratio_basis.startswith('최근 4분기'):
            held.append('증권사 전망 환산: 최근 4분기 순이익/영업이익 비율을 쓸 수 없어 ' + ratio_basis.split('(')[0] + '을 씀 — 해석에 주의')
    else:
        held.append('증권사 전망과의 비교: 승인된 증권사 전망 원장(T13)이 연결되지 않았거나 보고서가 없음')
    # 창 안의 흐름: 최고점과 상환 분해
    ok = [x for x in pts if x['EDI_norm'] is not None and not x.get('unstable_norm')]
    skipped = sum(1 for x in pts if x.get('unstable_norm'))
    if skipped:
        held.append(f'정규화 ROE가 장기성장률에 {E.STABLE_GAP*100:g}%p 안으로 가까웠던 {skipped}거래일은 V가 0에 가까워 EDI가 과장되므로 최고·최저·상환 분해에서 뺐음')
    if len(ok) >= 2:
        hi = max(ok, key=lambda x: x['EDI_norm']); lo = min(ok, key=lambda x: x['EDI_norm'])
        F.append({'name': '불러온 기간의 최고·최저 (정규화 V 기준)', 'kind': 'assumption_illustrative', 'unit': '년', 'value': {'high': round(hi['EDI_norm'], 2), 'low': round(lo['EDI_norm'], 2)},
                  'claim': f"{ok[0]['date']}~{d}: 최고 {hi['EDI_norm']:+.1f}년({hi['date']}, 주가 {hi['P']:,.0f} / V {hi['V_norm']:,.0f}), 최저 {lo['EDI_norm']:+.1f}년({lo['date']})",
                  'formula': '날짜마다 그때 공개된 분기만으로 V를 다시 계산. ' + asm})
        rp = E.repayment(pts)
        if rp:
            F.append({'name': '최고점 이후 줄어든 앞섬, 실적과 주가 중 누가 줄였나', 'kind': 'assumption_illustrative', 'unit': '%', 'value': round(rp['share_V'] * 100, 1),
                      'claim': f"{rp['peak']['date']} {rp['peak']['EDI_norm']:+.1f}년 → {d} {rp['now']['EDI_norm']:+.1f}년. "
                               + (f"줄어든 몫의 {rp['share_V']*100:.0f}%는 V 상승(실적), {rp['share_P']*100:.0f}%는 주가 하락. " if rp['share_P'] >= 0 and rp['share_V'] >= 0 else
                                  f"주가는 오히려 올랐지만 V가 그보다 더 올라 모두 실적으로 줄었음(V 몫 {rp['share_V']*100:.0f}%, 주가 몫 {rp['share_P']*100:.0f}%). " if rp['share_P'] < 0 else
                                  f"V는 오히려 내렸고 주가 하락으로 모두 줄었음(주가 몫 {rp['share_P']*100:.0f}%, V 몫 {rp['share_V']*100:.0f}%). ")
                               + "어느 쪽이 격차를 줄였는지의 기록이며 원인 단정이 아님.",
                      'formula': 'ln(주가/V)의 변화 = ln(주가 변화) − ln(V 변화)로 나눔. 원인 단정 아님'})
    if not extra:
        held.append('보통주 외 주식(우선주 등) 수를 넣지 않았음: 자본에는 우선주 몫도 들어 있어 주당 V가 크게(EDI가 작게) 나올 수 있음 — 설정 「보통주 외 주식 수」')
    held.append('자본총계는 비지배지분을 포함한 연결 값이라 지배주주 몫보다 큼(근사)')
    held.append('적정주가·목표주가·매수·매도 판단은 하지 않습니다 — V는 가정 아래 계산값입니다.')
    for x in E.monthly(pts):
        T.append([x['date'], f"{x['P']:,.0f}", x['basis_q'], *[('-' if x['V_' + m] is None else f"{x['V_' + m]:,.0f}") for m, _ in E.METHODS],
                  *[('-' if x['EDI_' + m] is None else f"{x['EDI_' + m]:+.1f}") for m, _ in E.METHODS]])
    status = 'succeeded' if len(pts) >= 252 else 'partial'
    if status == 'partial':
        held.append(f'계산된 날짜가 {len(pts)}일로 1년 미만 — 흐름(최고·최저)은 짧은 기간 기준')
    best = now['EDI_norm']
    why = (f"{p['name']} {d} 주가가 실적보다 앞선 햇수: 정규화 V 기준 {best:+.1f}년" if best is not None else f"{p['name']} {d}: 정규화 V 기준 EDI 보류") + \
          ' (가정 아래 계산값, 세 가지 V를 나란히). 적정주가·목표주가가 아닙니다.'
    return Result(status, why, {
        'company': p['company'], 'name': p['name'], 'as_of': d, 'findings': F, 'held': held,
        'assumptions': {'cost_of_equity': r, 'long_growth': g_lt, 'edi_growth': g, 'extra_shares': extra, 'lag_days': E.LAG_DAYS},
        'series': [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in x.items()} for x in E.monthly(pts)],
        'tables': [{'title': '월말 앞선 햇수(EDI) (그때 공개된 분기 기준)', 'cols': ['날짜', '종가', '쓴 분기', 'V 정규화', 'V 최근4분기', 'V 장부가', 'EDI 정규화', 'EDI 최근4분기', 'EDI 장부가'],
                    'rows': T, 'hint': '단위: 원 · 년. V는 가정 아래 계산값입니다.'}],
        'price_source': p['source'], 'filings_source': fp.get('source'), 'notice': E.NOTICE, 'kind': 'assumption_illustrative'})


# ---------------------------------------------------------------- N18 실적·가격 격차 국면 기록 (v0.20)
def n18(node, inputs, ctx):
    from . import edi as E
    p, rows, dig = _price_inputs(inputs, 'N18')
    fpk = _one(inputs, 'filings'); _check_packet(fpk, 'CompanyFilings')
    if fpk['header']['produced_by']['node_type'] != 'T11':
        raise Integrity('N18은 T11 결과만 받을 수 있습니다.')
    fp = fpk['payload']
    if fp.get('company') != p['company']:
        raise Integrity(f"가격({p['company']})과 재무({fp.get('company')})의 회사가 다릅니다.")
    cfg = node['config']
    try:
        r = _pct(cfg, 'cost_of_equity', 3, 20); g_lt = _pct(cfg, 'long_growth', -2, 5); g = _pct(cfg, 'edi_growth', 1, 30)
    except (TypeError, ValueError) as e:
        return Result('held', f'가정 값이 올바르지 않습니다: {e}', error_code='bad_config')
    if g_lt >= r:
        return Result('held', '장기성장률은 자기자본비용보다 작아야 합니다.', error_code='bad_config')
    qt, qsrc = _edi_quarters(fp)
    if not qt:
        return Result('held', f"{p['name']}: 분기 재무(자본·순이익)가 사본에 없어 계산하지 않습니다.", error_code='no_quarters')
    ctx.step('실적 반영일 사이 구간으로 나누기')
    pts = E.series(rows, qt, r, g_lt, g, 0)
    W = E.windows(pts, g) if pts else []
    done = [w for w in W if w['phase'] != 'open']
    if not done:
        return Result('held', '실적 반영일 사이의 끝난 구간이 없어 판정하지 않습니다(불러온 기간이 짧음).', error_code='too_short')
    lab = lambda k: E.PHASES[k][0]
    asm = f"자기자본비용 {r*100:g}% · 장기성장 {g_lt*100:g}% · g {g*100:g}% · 정규화 V 기준(최근 4분기 V와 결론이 다르면 「가정에 따라 갈림」)"
    rule = (f'구간 = 실적이 반영된 날부터 다음 실적이 반영된 날까지(V는 끝에서 한 번 바뀜). EDI 변화 {E.MIN_YEARS:g}년 미만은 「변화 작음」, '
            f'줄어든 몫의 {E.SHARE_LEAD*100:.0f}% 이상이 한쪽이면 그쪽 「주도」, 재무가 분기 말에서 {E.STALE_DAYS}일 넘게 지났거나 ROE가 장기성장률에 가까우면 보류. ')
    pct = lambda x0, x1: (x1 / x0 - 1) * 100
    F, held, T = [], [], []
    last = done[-1]
    def desc(w):
        t = f"{w['start']} ~ {w['end']} (쓴 분기 {w['basis_from']} → {w['basis_to']}): 주가 {pct(w['P0'], w['P1']):+.1f}%"
        if w.get('EDI0') is not None and w.get('EDI1') is not None:
            t += f", EDI {w['EDI0']:+.1f} → {w['EDI1']:+.1f}년"
        t += f" → 「{lab(w['phase'])}」"
        if w.get('share_V') is not None and w['phase'] in ('earn_led', 'mixed', 'price_led', 'split', 'deeper'):
            sv = w['share_V']
            t += (f" (줄어든 몫 중 실적 {sv*100:.0f}% · 가격 {(1-sv)*100:.0f}%)" if 0 <= sv <= 1 else
                  ' (주가는 올랐지만 V가 더 올라 모두 실적 쪽)' if sv > 1 else ' (V는 내렸고 모두 가격 쪽)')
        if w.get('why'):
            t += f" — {w['why']}"
        return t
    F.append({'name': '가장 최근에 끝난 구간', 'kind': 'assumption_illustrative', 'as_of': last['end'], 'claim': desc(last), 'formula': rule + asm})
    op = W[-1] if W[-1]['phase'] == 'open' else None
    if op:
        F.append({'name': '지금 진행 중인 구간', 'kind': 'assumption_illustrative', 'as_of': op['end'],
                  'claim': f"{op['start']} 실적 반영 이후 {op['end']}까지 주가 {pct(op['P0'], op['P1']):+.1f}%"
                           + (f", EDI {op['EDI0']:+.1f} → {op['EDI1']:+.1f}년" if op.get('EDI0') is not None and op.get('EDI1') is not None else '')
                           + '. 다음 실적이 반영되기 전이라 판정하지 않음(지금까지의 변화는 모두 가격 쪽).',
                  'formula': rule})
    cnt = {}
    for w in done:
        cnt[w['phase']] = cnt.get(w['phase'], 0) + 1
    F.append({'name': f'끝난 구간 {len(done)}개의 국면 기록', 'kind': 'assumption_illustrative',
              'claim': ' · '.join(f"{lab(k)} {v}" for k, v in sorted(cnt.items(), key=lambda kv: -kv[1])), 'formula': rule + asm})
    for w in W:
        T.append([w['start'], w['end'], f"{w['basis_from']}→{w['basis_to']}", f"{pct(w['P0'], w['P1']):+.1f}%",
                  '-' if w.get('EDI0') is None else f"{w['EDI0']:+.1f}", '-' if w.get('EDI1') is None else f"{w['EDI1']:+.1f}",
                  lab(w['phase']), '-' if w.get('share_V') is None else f"{w['share_V']*100:.0f}%"])
    if cnt.get('held'):
        held.append(f"보류 {cnt['held']}구간: 재무가 오래됐거나(정정 공시로 접수일이 늦게 잡힌 경우 포함) ROE가 장기성장률에 가까움")
    held.append('국면은 지난 기록이며 앞으로의 방향·매매 판단을 하지 않습니다.')
    held.append('보통주 외 주식 수를 넣지 않음: V 수준은 달라질 수 있으나, 주식 수가 같으면 구간 안의 변화(국면)는 영향을 받지 않음')
    return Result('succeeded' if len(done) >= 4 else 'partial',
                  f"{p['name']} 실적 반영일 사이 {len(done)}개 구간의 국면 기록. 가장 최근 끝난 구간은 「{lab(last['phase'])}」. 가정 아래의 기록이며 판단이 아닙니다.",
                  {'company': p['company'], 'name': p['name'], 'as_of': pts[-1]['date'], 'findings': F, 'held': held,
                   'windows': [{k: v for k, v in w.items()} for w in W], 'quarters_source': qsrc,
                   'assumptions': {'cost_of_equity': r, 'long_growth': g_lt, 'edi_growth': g, 'share_lead': E.SHARE_LEAD, 'min_years': E.MIN_YEARS, 'stale_days': E.STALE_DAYS},
                   'tables': [{'title': '실적 반영일 사이 구간 기록', 'cols': ['시작', '끝', '쓴 분기', '주가 변화', 'EDI 시작', 'EDI 끝', '국면', '실적 몫'], 'rows': T,
                               'hint': '정규화 V 기준. 국면 이름은 기록용 중립어입니다.'}],
                   'price_source': p['source'], 'filings_source': fp.get('source'), 'notice': E.NOTICE, 'kind': 'assumption_illustrative'})

# ---------------------------------------------------------------- T14 / N19 사업부별 분기 매출 (v0.37, 박상혁 P02 이식)
def _docs_digest(docs):
    """쓴 원문들만의 해시 — 다른 회사 원문이 사본에 더 들어와도 이 값은 바뀌지 않는다(확인서 재계산용)."""
    import hashlib
    return hashlib.sha256(chr(10).join(sorted(f"{d['rcept_no']}:{d['sha256']}" for d in docs)).encode()).hexdigest()


def t14(node, inputs, ctx):
    from .market import resolve, load_manifest, read_rows, companies, SnapshotError
    from . import segments as SG, dartdocs as DD
    cfg = node['config']
    company = cfg.get('company') or '005930'
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다.', error_code='company_unknown')
    ctx.step('Neon 사본·DART 원문 사본 해시 재대조')
    name, rev, src = company, {}, {}
    try:
        root = resolve(cfg.get('snapshot') or ''); man = load_manifest(root)
        name = (companies(root, man).get(company) or {}).get('name', company)
        rows, meta = read_rows(root, man, 'financial_quarter', company)
        rev = {r['period_end']: int(float(r['amount'])) for r in rows if r.get('metric') == 'revenue' and r.get('amount') not in (None, '')}
        src['financial_quarter'] = {'origin': '분기 재무(공시 API) — 연결 합계 대조용, Neon 공용 DB 경유', 'snapshot': root.name, 'sha256': meta.get('sha256'), 'source_grade': meta.get('source_grade'), 'file': meta.get('file')}
        if not rev:                                          # v0.37.5: 분기 재무 표에 없는 회사는 공시 재무(financial_fact)의 연결 매출로 대조
            frows, fmeta = read_rows(root, man, 'financial_fact', company)
            rev = SG.revenue_from_facts(frows)
            src = {'financial_fact': {'origin': '공시 재무(DART 재무 API) 연결 매출 — 연결 합계 대조용, Neon 공용 DB 경유', 'snapshot': root.name, 'sha256': fmeta.get('sha256'), 'source_grade': fmeta.get('source_grade'), 'file': fmeta.get('file')}}
    except SnapshotError as e:
        return Result('held', str(e), error_code=e.code)
    base = {'company': company, 'name': name, 'qualified': False, 'kind': 'fact_official', 'source': src}
    try:
        dman = DD.load_manifest()
        if company not in (dman.get('listed') or {}):
            return Result('succeeded', f'{name}: 이 회사의 DART 원문을 아직 받지 않아 사업부별 매출을 읽지 않았습니다.', {**base, 'reasons': ['이 회사의 DART 원문을 아직 받지 않음']})
        res = SG.qualified(company, ctx.cutoff, rev, None, name)
    except DD.DartDocsError as e:
        return Result('succeeded', f'{name}: DART 원문 사본을 쓸 수 없어 사업부별 매출을 읽지 않았습니다.',
                      {**base, 'reasons': ['DART 원문 사본이 이 PC에 없음' if e.code == 'no_docs' else f'DART 원문 사본의 해시가 맞지 않아 쓰지 못함({e.code}) — 보류']})
    src['dart_docs'] = {'origin': 'DART 정기보고서 원문(연결재무제표 주석 「부문별 보고」) — OpenDART document.xml, 받은 그대로', 'snapshot': None, 'sha256': _docs_digest(res['docs']), 'source_grade': 'official', 'file': f"manifest.json 중 이 회사 정기보고서 {len(res['docs'])}건"}
    payload = {**base, **res, 'name': name, 'source': src}
    if not res['qualified']:
        return Result('succeeded', f"{name}: 사업부별 매출은 자격 관문을 통과하지 못해 값을 넘기지 않습니다 — " + ' / '.join(res['reasons']), payload)
    return Result('succeeded', f"{name} 정기보고서 {len(res['docs'])}건에서 사업부·제품·지역별 분기 매출 {len(res['quarters'])}칸을 읽었습니다. "
                               f"표 {res['tables']['count']}개 중 {res['tables']['exact']}개는 합계와 원 단위까지 일치, 분기 연결 합계 {res['independent']['matched']}개 분기가 분기 재무와 일치.", payload)


def n19(node, inputs, ctx):
    pkt = _one(inputs, 'segments'); _check_packet(pkt, 'SegmentRevenue')
    if pkt['header']['produced_by']['node_type'] != 'T14':
        raise Integrity('N19는 T14 결과만 받을 수 있습니다.')
    p = pkt['payload']; F, held, T = [], [], []
    if not p.get('qualified'):
        held += ['사업부별 분기 매출: ' + r for r in (p.get('reasons') or ['자료 없음'])]
        return Result('succeeded', f"{p['name']} 사업부별 분기 매출은 보류했습니다(자격 관문).",
                      {'company': p['company'], 'name': p['name'], 'findings': F, 'held': held, 'tables': T, 'segment_source': p.get('source') or {},
                       'notice': '확인을 통과한 회사만 사업부별 매출을 보여 줍니다. 통과하지 못한 회사는 값을 지어내지 않고 이유를 적습니다.'})
    Q = p['quarters']; AX = (('segment', '사업부(보고부문)'), ('product', '제품'), ('region', '지역'))
    order = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4}
    from collections import Counter
    cnt = {}
    for r in Q:
        cnt.setdefault((r['axis'], r['key']), Counter())[r['name']] += 1
    nm = lambda r: cnt[(r['axis'], r['key'])].most_common(1)[0][0]      # 같은 사업의 표기가 보고서마다 다르면 가장 많이 쓰인 표기
    for axis, alab in AX:
        rows = [r for r in Q if r['axis'] == axis]
        if not rows:
            continue
        slots = sorted({(r['year'], order[r['q']]) for r in rows})[-6:]
        last = slots[-1]; lab = lambda s: f"{s[0]}년 {s[1]}분기"
        cur = sorted((r for r in rows if (r['year'], order[r['q']]) == last), key=lambda r: -r['value'])
        if axis == 'segment' or not any(r['axis'] == 'segment' for r in Q) and axis == AX[1][0]:
            for r in cur:
                F.append({'name': f"{nm(r)} {lab(last)} 매출", 'claim': _eok(r['value']) + ('' if r['method'] == 'reported_3m' else ' (누적 값끼리 빼서 계산)'),
                          'value': r['value'], 'unit': '원', 'kind': 'fact_official' if r['method'] == 'reported_3m' else 'derived',
                          'formula': '정기보고서 주석 「부문별 보고」 표의 3개월 값 × 표의 단위' if r['method'] == 'reported_3m' else (r.get('formula') or '연간 − 9개월 누적') + ' (같은 사업 구성일 때만)',
                          'source': {'title': r['sources'][0]['report'], 'url': r['sources'][0]['url'], 'rcept_no': r['sources'][0]['rcept_no']}})
            ys = [r for r in cur if r.get('yoy')]
            if ys:
                F.append({'name': f"{alab} 전년 동기 대비 ({lab(last)})", 'claim': ' · '.join(f"{nm(r)} {r['yoy']['pct']:+.2f}%" for r in ys), 'kind': 'derived',
                          'formula': '(당기 분기 매출 ÷ 전년 같은 분기 매출 − 1) × 100, 소수 둘째 자리 반올림. 같은 보고서의 당기·전기 칸끼리(같은 정의) 계산. 증감의 좋고 나쁨은 판단하지 않음'})
        keys = []
        for r in sorted(rows, key=lambda r: (-(r['year'] * 10 + order[r['q']]), -r['value'])):
            if r['key'] not in keys:
                keys.append(r['key'])
        cell = {(r['key'], r['year'], order[r['q']]): r for r in rows}
        def show(k, s):
            r = cell.get((k,) + s)
            if not r:
                return ''
            return f"{r['value'] / 1e8:,.0f}" + (f" ({r['yoy']['pct']:+.1f}%)" if r.get('yoy') else '') + ('' if r['method'] == 'reported_3m' else ' ※')
        T.append({'title': f'{alab}별 분기 매출 (억원, 괄호는 전년 동기 대비)', 'cols': ['구분'] + [lab(s) for s in slots],
                  'rows': [[nm(next(r for r in rows if r['key'] == k))] + [show(k, s) for s in slots] for k in keys if any(show(k, s) for s in slots)],
                  'hint': '※ = 누적 값끼리 뺀 값(연간 − 9개월, 반기 − 1분기 등). 빈칸은 그 이름으로 공시되지 않았거나 같은 정의로 계산할 수 없는 분기입니다. 이름이 바뀐 사업은 잇지 않고 따로 보입니다.'})
    tb, ind = p['tables'], p['independent']
    F.append({'name': '부문 표 합계 점검', 'claim': f"표 {tb['count']}개 중 {tb['exact']}개는 항목 합(+내부거래 조정)이 합계와 원 단위까지 같음 · {tb['C']}개는 회사가 일부 항목만 공시한 표(합계 일치를 주장하지 않음)",
              'kind': 'derived', 'formula': '표마다 항목 합 + 공시된 조정 = 표의 합계 인지 확인. 허용오차 = 0.5 × 표시 단위 × 더한 칸 수'})
    F.append({'name': '독립 자료와의 대조', 'claim': f"분기 연결 매출 {ind['matched']}개 분기가 공시 재무의 연결 매출과 모두 같음", 'kind': 'derived',
              'formula': '부문 표에서 만든 분기 연결 합계 vs Neon 사본의 분기 재무 매출. 이 대조와 합계 점검을 모두 통과한 회사만 값을 보임(자격 관문)'})
    if p.get('held'):
        held.append(f"분기 값을 만들 수 없어 비워 둔 칸 {len(p['held'])}개(9개월 누적 값이 없거나 사업 이름·구성이 바뀐 분기) — 보류")
    _AX = {'segment': '사업부', 'product': '제품', 'region': '지역'}
    for x in p.get('axes_held') or []:
        held.append(f"{_AX.get(x['axis'], x['axis'])}별 매출: 줄 이름 점검에서 보류 — {'; '.join(x['reasons'])}")
    if p.get('lag_quarters'):
        held.append('가장 최근 정기보고서의 표는 읽지 못해 한 분기 전까지만 보임 — 보류')
    held.append('사업 지도(제품·수요·경쟁에 관한 원문 문장): 아직 넣지 않음(다음 단계)')
    held.append('사업부의 좋고 나쁨·전망 판단: 하지 않음')
    return Result('succeeded', f"{p['name']} 사업부·제품·지역별 분기 매출과 전년 동기 대비 {len(F)}건. 정기보고서 주석의 값이며 판단이 아닙니다.",
                  {'company': p['company'], 'name': p['name'], 'findings': F, 'held': held, 'tables': T, 'segment_source': p['source'],
                   'notice': '회사가 정기보고서 주석에 공시한 사업부별 매출을 옮긴 것입니다. 사업의 좋고 나쁨이나 앞으로의 방향을 판단하지 않습니다.'})


# ---------------------------------------------------------------- T15 / N20 공시 1건 숫자로 보기 (v0.38 T1)
def t15(node, inputs, ctx):
    from . import filing as FL, dartdocs as DD
    from .market import company_name
    cfg = node['config']
    company, no = cfg.get('company') or '', (cfg.get('rcept_no') or '').strip()
    if not (isinstance(company, str) and re.fullmatch(r'\d{6}', company)):
        return Result('held', f'{company}는 6자리 종목코드가 아닙니다.', error_code='company_unknown')
    if not re.fullmatch(r'\d{14}', no):
        return Result('held', '접수번호(숫자 14자리)를 넣어 주세요.', error_code='bad_rcept_no')
    ctx.step('DART 원문 사본 해시 재대조')
    try:
        f = FL.load(company, no, ctx.cutoff)
    except DD.DartDocsError as e:
        return Result('held', str(e), error_code=e.code)
    name = company_name(company) or company
    src = {'dart_docs': {'origin': f"DART 공시 원문 「{f['report_nm']}」 — OpenDART document.xml, 받은 그대로", 'snapshot': None, 'sha256': _docs_digest(f['docs']),
                         'source_grade': 'official', 'file': f"manifest.json 중 {len(f['docs'])}건 (접수번호 {no}" + ((' 외 앞선 배당 결정' if f['kind'] == 'dividend' else ' 외 앞선 공시') if len(f['docs']) > 1 else '') + ')'}}
    src['dart_docs'].update(rcept_no=no, url=f['url'], fetched_at=f.get('fetched_at'), how=f.get('fetched_how'))   # v0.38 T2-4d 출처 표시(더하기만). 앱이 처음 본 시각은 답을 보일 때 붙임(J23)
    payload = {**{k: v for k, v in f.items() if k not in ('docs', 'kind')}, 'filing_kind': f['kind'], 'company': company, 'name': name, 'rule': FL.RULE, 'source': src,
               'kind': 'fact_official'}       # 'kind'은 값 종류(사실) 칸이라 공시 종류는 filing_kind에
    return Result('succeeded', f"{name} {f['rcept_dt']} 「{f['report_nm']}」 원문(접수번호 {no})을 읽었습니다. 해시 대조 통과.", payload)


def n20(node, inputs, ctx):
    from . import filing as FL
    pkt = _one(inputs, 'filing'); _check_packet(pkt, 'FilingDoc')
    if pkt['header']['produced_by']['node_type'] != 'T15':
        raise Integrity('N20은 T15 결과만 받을 수 있습니다.')
    f = {**pkt['payload'], 'kind': pkt['payload']['filing_kind']}; held = []
    mkt, psrc = None, None
    pp = _one(inputs, 'prices')
    if pp:
        _check_packet(pp, 'PriceSeries')
        if pp['header']['produced_by']['node_type'] != 'T06':
            raise Integrity('N20의 가격 입력은 T06 결과만 받을 수 있습니다.')
        if pp['payload'].get('company') not in (None, f['company']):
            raise Integrity('가격 자료와 공시의 회사가 다릅니다.')
        mkt = FL.market_before(pp['payload']['rows'], f['rcept_dt']); psrc = pp['payload'].get('source')
        if mkt is None:
            held.append(f"공시일({f['rcept_dt']}) 전 시세가 사본에 없어 시가총액·거래대금과 견주는 계산은 보류")
    elif f['kind'] not in ('prelim', 'pl_change'):
        held.append('가격 자료를 잇지 않아 시가총액·거래대금과 견주는 계산은 하지 않음')
    F, h2, T, notes = FL.compute(f, mkt, prices=(pp['payload']['rows'] if pp else None), ticker=f['company'], snapshot=(psrc or {}).get('snapshot'))     # v0.38 T2-3: 발행가 산식은 기준 날짜까지의 시세를 씀(확률도 같은 사본)
    held += h2
    status = 'succeeded' if F else 'partial'
    return Result(status, f"{f['name']} 「{f['kind_label']}」 공시의 칸 값 {sum(1 for x in F if x['kind'] == 'fact_official')}개와 계산 {sum(1 for x in F if x['kind'] == 'derived')}개. 방향 판단은 하지 않았습니다.",
                  {'company': f['company'], 'name': f['name'], 'rcept_no': f['rcept_no'], 'filing_kind': f['kind'], 'findings': F, 'held': held + ['호재·악재 같은 방향 판단: 하지 않음'],
                   'tables': T, 'notes': notes, 'filing_source': f.get('source') or {}, 'price_source': psrc, 'market': mkt, 'rule': FL.RULE,
                   'notice': ' '.join(notes + ['공시의 숫자를 원문 그대로 옮기고 식으로 나눈 값입니다. 매수·매도 판단이 아닙니다.'])})


HANDLERS = {'T01': t01, 'T03': t03, 'T04': t04, 'T05': t05, 'N01': n01, 'N02': n02, 'N05': n05, 'N06': n06, 'T06': t06, 'N09': n09, 'N10': n10, 'T07': t07, 'N07': n07, 'N08': n08, 'T09': t09, 'N03': n03, 'T10': t10, 'T11': t11, 'T08': t08, 'N11': n11, 'N12': n12, 'N14': n14, 'T02': t02, 'N04': n04, 'T12': t12, 'N13': n13, 'N15': n15, 'T13': t13, 'N16': n16, 'N17': n17, 'N18': n18, 'T14': t14, 'N19': n19, 'T15': t15, 'N20': n20}
