"""Generate synthetic A-company fixtures without external API calls."""
import hashlib
import json
from pathlib import Path

from agent.research_contract import revise_claim, seal_report

ROOT = Path(__file__).resolve().parents[1]


def build_example():
    docs = []
    for ident, name in [('D01', 'a_company_business.md'), ('D02', 'a_company_prices.json')]:
        path = ROOT / 'examples' / 'data' / name
        docs.append({'documentId': ident, 'version': '1', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'path': 'examples/data/' + name, 'originalUrl': None, 'dataMode': 'synthetic',
                     'publishedAt': '2026-10-26T00:00:00+09:00', 'collectedAt': '2026-10-26T09:00:00+09:00',
                     'access': 'fixture_only', 'redistribution': 'synthetic example'})
    prices = json.loads((ROOT / 'examples/data/a_company_prices.json').read_text(encoding='utf-8-sig'))
    closes = [x['close'] for x in prices['observations']]
    average = sum(closes[-3:]) / 3
    r = {
        'schemaVersion': '1.0', 'reportId': 'SAMPLE-A-001', 'contentRevision': 1,
        'parentDigest': None, 'dataMode': 'synthetic', 'status': 'partial',
        'question': '가상 A기업의 제품 구성 변화가 이익 개선으로 이어질까? 단기 가격 흐름과 함께 확인한다.',
        'asOf': '2026-10-26T09:00:00+09:00',
        'subject': {'name': '가상 A기업', 'ticker': None}, 'documents': docs,
        'evidence': [
            {'evidenceId': 'E01', 'documentId': 'D01', 'documentVersion': '1',
             'location': {'type': 'markdown_heading', 'heading': '제품 구성'},
             'excerpt': '고부가 제품 매출 비중은 전년 30%에서 40%로 증가했다.',
             'observationPeriod': '가상 연도 Y0~Y1', 'verificationStatus': 'unverified'},
            {'evidenceId': 'E02', 'documentId': 'D01', 'documentVersion': '1',
             'location': {'type': 'markdown_heading', 'heading': '비용과 경쟁'},
             'excerpt': '신규 공급자의 증설 계획이 있으며 투자 부담이 증가했다. 제품별 마진은 제공하지 않는다.',
             'observationPeriod': '가상 연도 Y1', 'verificationStatus': 'unverified'},
            {'evidenceId': 'E03', 'documentId': 'D02', 'documentVersion': '1',
             'location': {'type': 'json_pointer', 'pointer': '/observations'},
             'excerpt': json.dumps(prices['observations'], ensure_ascii=False),
             'observationPeriod': '가상 거래일 T1~T5', 'verificationStatus': 'unverified'},
        ],
        'calculations': [{'calculationId': 'CAL01', 'method': 'simple_moving_average',
                          'methodVersion': '1', 'formula': 'sum(last 3 closes) / 3',
                          'inputEvidenceIds': ['E03'], 'inputs': closes[-3:], 'parameters': {'window': 3},
                          'priceAdjustment': 'synthetic unadjusted', 'missingPolicy': 'reject',
                          'unit': '가상 가격 단위', 'result': average}],
        'claims': [
            {'claimId': 'C01', 'claimVersion': 1, 'domain': 'industry_business_model',
             'kind': 'interpretation', 'horizon': '향후 네 분기 가설',
             'text': '고부가 제품 비중 증가는 이익 개선 요인이 될 수 있으나 마진·투자비 확인 전에는 보류한다.',
             'assessment': 'withheld', 'evidenceLinks': [
                 {'evidenceId': 'E01', 'relation': 'supports'}, {'evidenceId': 'E02', 'relation': 'opposes'}],
             'calculationIds': [], 'assumptions': ['가격·수율·비용 조건 확인 필요'],
             'missingInformation': ['제품별 마진', '경쟁사 공급능력 비교'],
             'nextQuestions': ['제품별 수익성과 경쟁사의 공급 계획을 확보할 수 있는가?']},
            {'claimId': 'C02', 'claimVersion': 1, 'domain': 'technical_analysis',
             'kind': 'fact', 'horizon': '가상 거래일 T5 현재',
             'text': f'마지막 종가 {closes[-1]}는 3거래일 단순이동평균 {average}보다 낮다.',
             'assessment': 'provisional', 'evidenceLinks': [{'evidenceId': 'E03', 'relation': 'supports'}],
             'calculationIds': ['CAL01'], 'assumptions': ['합성 가격·비조정 기준'],
             'missingInformation': ['실제 시장 자료', '유사 신호 실패 분포'],
             'nextQuestions': ['충분한 실제 기간에서 같은 조건과 실패 사례를 확인할 수 있는가?']},
        ],
        'map': {'nodes': [{'nodeId': 'N' + str(i), 'label': label} for i, label in enumerate(
            ['고객', '제품·서비스', '매출', '비용', '이익', '위험'], 1)],
                'edges': [{'edgeId': 'EDGE01', 'from': 'N3', 'to': 'N5', 'claimId': 'C01',
                           'claimVersion': 1, 'status': 'missing_evidence',
                           'meaning': '검토할 관계이며 인과관계 입증 아님'}]},
        'agentResults': [
            {'domain': 'industry_business_model', 'status': 'example',
             'claims': [{'claimId': 'C01', 'claimVersion': 1}],
             'competition': {'status': 'insufficient_data', 'score': None}},
            {'domain': 'technical_analysis', 'status': 'example',
             'claims': [{'claimId': 'C02', 'claimVersion': 1}]}],
        'analysisRelations': [{'relationId': 'REL01', 'type': 'different_horizons',
                              'claims': [{'claimId': 'C01', 'claimVersion': 1},
                                         {'claimId': 'C02', 'claimVersion': 1}],
                              'explanation': '장기 사업 가설과 단기 가격 위치는 관찰 기간이 다르며 함께 성립할 수 있다.'}],
        'objections': [{'objectionId': 'O01', 'target': {'claimId': 'C01', 'claimVersion': 1},
                        'targetReportRevision': 1, 'status': 'in_review', 'critical': True,
                        'text': '매출 구성 변화만으로 이익 개선을 판단할 수 없으며 투자비 확인이 필요하다.',
                        'authorResponse': {'decision': 'accept', 'reason': '비용 조건을 더 명확히 표시할 예정'},
                        'reviewerDecision': None, 'implementation': None}],
        'checks': [], 'approvals': [], 'history': [],
    }
    return seal_report(r)


def main():
    report = build_example()
    revised = revise_claim(report, 'C01', text='제품 비중 변화는 확인 대상이나 이익 개선은 미확인이다.',
                           reason='O01 반론에 따라 비용·마진 누락을 더 명확히 표시; 재검토 대기')
    for name, data in [('a_company_report_v1.json', report), ('a_company_report_v2.json', revised)]:
        (ROOT / 'examples/data' / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Generated and validated two synthetic snapshots')


if __name__ == '__main__':
    main()
