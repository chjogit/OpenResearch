"""Per-company preflight. Operational API status is never proof of input quality."""
import json
import math
from datetime import date, datetime
from zoneinfo import ZoneInfo

from agent.research_contract import validate_report

NAMES = {'industry_business_model': '산업·사업모델', 'technical_analysis': '기술적 분석'}
LEVEL = {'pass': 0, 'partial': 1, 'hold': 2}
LABEL = {0: '실행 가능', 1: '일부 가능', 2: '보류'}


def _date(value):
    return date.fromisoformat(str(value)[:10])


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def assess_report(report, *, window=3, reference_date=None, max_price_age_days=5, max_doc_age_days=400):
    """Reference date is explicit for reproducible historical inspection; defaults to KST today."""
    validate_report(report)
    if type(window) is not int or window < 2 or min(max_price_age_days, max_doc_age_days) < 0:
        raise ValueError('Invalid quality policy')
    ref = _date(reference_date) if reference_date else datetime.now(ZoneInfo('Asia/Seoul')).date()
    asof = _date(report['asOf'])
    company = report['subject'].get('ticker') or report['subject'].get('name') or report['reportId']
    checks = []

    def add(domain, rule, status, reason, observed=None):
        checks.append({'기업': company, 'Agent': NAMES[domain], '규칙': rule,
                       '판정': LABEL[LEVEL[status]], '이유': reason, '관측값': observed})

    for domain in NAMES:
        if report['dataMode'] == 'synthetic':
            add(domain, 'data_mode', 'partial', '합성 예시: 실데이터 최신성·거래일 검증 대상 아님')
        add(domain, 'asof', 'hold' if asof > ref else 'pass',
            '보고서 기준일이 검사 기준일 이후' if asof > ref else '보고서 기준일 범위 확인', str(asof))
    domain = 'industry_business_model'
    claims = [c for c in report['claims'] if c['domain'] == domain]
    ids = {x['evidenceId'] for c in claims for x in c['evidenceLinks']}
    evidence = [e for e in report['evidence'] if e['evidenceId'] in ids]
    add(domain, 'source_coverage', 'pass' if claims and evidence else 'hold',
        '주장과 연결된 원문 근거 확보' if claims and evidence else '주장 또는 연결 원문 근거 없음', len(evidence))
    for e in evidence:
        doc = next(d for d in report['documents'] if d['documentId'] == e['documentId'])
        identified = bool(doc.get('path') or doc.get('originalUrl'))
        located = bool(e.get('location')) and bool(e.get('excerpt')) and identified
        add(domain, 'source:' + e['evidenceId'], 'pass' if located else 'hold',
            '원문 위치·발췌·식별자 있음(내용 지지는 별도 검증)' if located else '원문 위치·발췌·식별자 부족')
        if report['dataMode'] == 'actual':
            try:
                published = _date(doc['publishedAt'])
                if published > min(asof, ref):
                    add(domain, 'document_date', 'hold', '기준일 이후 공개된 자료', str(published))
                else:
                    age = (ref - published).days
                    add(domain, 'document_age', 'partial' if age > max_doc_age_days else 'pass',
                        '문서 경과일 정책(공시 의무주기 검증 아님)', age)
            except (KeyError, ValueError, TypeError):
                add(domain, 'document_date', 'hold', '공개일 미확인: 시점 검증 불가')
        if e['verificationStatus'] != 'support_checked':
            add(domain, 'support_check', 'partial', '원문이 주장을 지지하는지 검수 대기')
    missing = list(dict.fromkeys(x for c in claims for x in c.get('missingInformation', [])))
    if missing or any(c['assessment'] == 'withheld' for c in claims):
        add(domain, 'business_gaps', 'partial', '미확보 자료·보류 결론: ' + '; '.join(missing))

    domain = 'technical_analysis'
    e = next((e for e in report['evidence'] if e['evidenceId'] == 'E03'), None)
    try:
        prices = json.loads(e['excerpt']) if e else []
        if not isinstance(prices, list) or not all(isinstance(p, dict) for p in prices):
            raise ValueError('Invalid rows')
    except (ValueError, TypeError):
        prices = []
    add(domain, 'history', 'pass' if len(prices) >= window else 'hold',
        f'이동평균 최소 관측 {window}개 필요; 장기 지표 충분성을 뜻하지 않음', len(prices))
    if prices:
        missing_values = sum(not _finite(p.get('close')) or p.get('close', 0) <= 0
                             or not _finite(p.get('volume')) or p.get('volume', -1) < 0 for p in prices)
        add(domain, 'close_volume', 'hold' if missing_values else 'pass',
            '종가/거래량 결측·비정상 행 수', missing_values)
        days = [p.get('day') for p in prices]
        valid_keys = all(isinstance(d, str) and d for d in days)
        duplicates = len(days) - len({d for d in days if isinstance(d, str)})
        add(domain, 'duplicate_dates', 'pass' if valid_keys and duplicates == 0 else 'hold',
            '날짜 식별자 누락 또는 중복 검사', duplicates)
        ohlc_missing = sum(any(not _finite(p.get(k)) for k in ['open', 'high', 'low']) for p in prices)
        add(domain, 'ohlc_fields', 'partial' if ohlc_missing else 'pass',
            '전체 OHLC 필드 미확보 시 종가·거래량 분석만 가능', ohlc_missing)
        if report['dataMode'] == 'actual':
            try:
                parsed = [_date(d) for d in days]
                if parsed != sorted(parsed) or max(parsed) > min(ref, asof):
                    add(domain, 'date_range', 'hold', '날짜 순서 오류 또는 기준일 이후 시세')
                else:
                    age = (ref - max(parsed)).days
                    add(domain, 'price_age', 'hold' if age > max_price_age_days else 'pass',
                        '달력일 경과 기준. 공식 휴장일 검증과 별도', age)
                    add(domain, 'date_range', 'pass', '보유 구간(중간 거래일 완전성 미확인)',
                        f'{min(parsed)} ~ {max(parsed)}')
            except (ValueError, TypeError):
                add(domain, 'date_range', 'hold', 'ISO 시세 날짜 미확인')
            metadata = report.get('priceMetadata') or {}
            basis = metadata.get('adjustment') in {'unadjusted', 'split_adjusted', 'total_return'}
            add(domain, 'price_basis', 'pass' if basis and metadata.get('sourceDescription') else 'hold',
                '가격 조정 기준·설명 출처 필요(진위·기업행위 대조는 별도)')
            add(domain, 'calendar', 'partial', '공식 거래일·기업행위 대조는 별도 필요')
    gates = {}
    for domain, domain_name in NAMES.items():
        own = [c for c in checks if c['Agent'] == domain_name]
        rank = max(next(k for k, v in LABEL.items() if v == c['판정']) for c in own)
        gates[domain] = {'status': ['passed', 'partial', 'withheld'][rank], 'label': LABEL[rank],
                          'reasons': [c['이유'] for c in own if c['판정'] != '실행 가능'],
                          'company': company, 'reportId': report['reportId'],
                          'inputDigest': report['digest'], 'window': window,
                          'checkedAt': ref.isoformat(), 'ruleVersion': 'preflight-1',
                          'checks': own}
    return gates, checks


def gate_table(gates):
    return [{'기업': g['company'], 'Agent': NAMES[domain], '상태': g['label'],
             '이유': '; '.join(g['reasons']) or '현재 규칙 통과(사실 검증·승인 아님)',
             '기준일': g['checkedAt'], '규칙 버전': g['ruleVersion']} for domain, g in gates.items()]


def run_checked(agent, report, gate):
    """Withheld blocks all calculation/model/LLM calls. Validated against input snapshot and settings."""
    from agent.basic_agents import IndustryBusinessAgent, TechnicalAnalysisAgent, _base
    domain = 'industry_business_model' if isinstance(agent, IndustryBusinessAgent) else 'technical_analysis'
    if not isinstance(agent, (IndustryBusinessAgent, TechnicalAnalysisAgent)):
        raise TypeError('Unsupported agent')
    validate_report(report)
    if gate['inputDigest'] != report['digest'] or gate['window'] != agent.settings.window:
        raise ValueError('품질검사 후 자료/설정이 바뀌었습니다. 검사를 다시 실행하세요.')
    if gate['checks'][0]['Agent'] != NAMES[domain]:
        raise ValueError('Agent와 검사 결과가 다릅니다.')
    if gate['status'] == 'withheld':
        result = _base(report, domain, 'quality-blocked')
        result.update(status='withheld', limitations=gate['reasons'],
                      followUpRequests=['품질 표의 보류 사유를 보완한 후 다시 검사하세요.'])
    else:
        kwargs = {'price_metadata': report.get('priceMetadata')} if domain == 'technical_analysis' else {}
        result = agent.run(report, **kwargs)
    result['qualityGate'] = gate
    return result


def inventory_gate_table(rows, *, start, end, reference_date=None, window=3, max_price_age_days=5):
    """Conservative readiness from aggregate DB inventory; never proves raw-source completeness."""
    ref = _date(reference_date) if reference_date else datetime.now(ZoneInfo('Asia/Seoul')).date()
    output = []
    keys = list(dict.fromkeys((r['종목'], r['기업']) for r in rows))
    for ticker, name in keys:
        tables = {r['테이블']: r for r in rows if (r['종목'], r['기업']) == (ticker, name)}
        for domain, domain_name in NAMES.items():
            rank, reasons = 1, ['집계 기반 점검: 원문·기업행위·공식 거래일은 별도 검수 필요']
            required = ['core.price_daily'] if domain == 'technical_analysis' else ['rag.document']
            if _date(end) > ref:
                rank = 2
                reasons.append('요청 종료일이 검사 기준일 이후')
            for table in required:
                row = tables.get(table)
                if not row or row['상태'] != '기간 내 보유' or not row['건수']:
                    rank = 2
                    reasons.append(table + ': 미보유/조회 실패/권한·스키마 확인 필요')
                    continue
                if row['날짜 결측']:
                    reasons.append(table + ': 날짜 결측 포함')
                if domain == 'technical_analysis':
                    if (row['날짜 수'] or 0) < window:
                        rank = 2
                        reasons.append('지표 최소 관측 기간 부족')
                    nulls = row.get('nullCounts') or {}
                    if any(k not in nulls for k in ['close', 'volume']) or any(nulls.get(k, 0) for k in ['close', 'volume']):
                        rank = 2
                        reasons.append('종가·거래량 결측 또는 검사 필드 부재')
                    try:
                        latest = _date(row['최종'])
                        age = (ref - latest).days
                        if age > max_price_age_days or latest > ref:
                            rank = 2
                            reasons.append(f'시세 최신성 정책 미충족: 경과 {age}일')
                        if _date(row['최초']) > _date(start):
                            reasons.append('요청 시작일보다 보유 시작일이 늦음(휴장·상장 범위 확인)')
                    except (ValueError, TypeError):
                        rank = 2
                        reasons.append('시세 기간 미확인')
                else:
                    reasons.append('문서 건수로 사업보고서 본문·주장 근거 확보를 확정할 수 없음')
            if domain == 'industry_business_model':
                financial = [tables.get(t) for t in ['core.financial_fact', 'core.financial_quarter']]
                if not any(r and r['상태'] == '기간 내 보유' and r['건수'] for r in financial):
                    reasons.append('재무 보유 상태 추가 확인 필요')
            output.append({'종목': ticker, '기업': name, 'Agent': domain_name, '상태': LABEL[rank],
                           '이유': '; '.join(reasons), '검사 기준일': str(ref),
                           '검사 기간': f'{start} ~ {end}', '규칙 버전': 'inventory-preflight-1'})
    return output
