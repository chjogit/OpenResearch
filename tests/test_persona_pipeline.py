"""Persona selection -> presentation, technical states, paragraph baseline, invariance table, model gate."""
import json

import pytest

from agent.basic_agents import AgentSettings, IndustryBusinessAgent, TechnicalAnalysisAgent, select_persona
from agent.model_comparison import compare, weaknesses
from agent.neon_agents import execute_report
from agent.paragraph_labels import (
    LABELS,
    evaluate,
    export_sheet,
    load_labels,
    paragraphs,
    rule_classify,
    split_by_document,
)
from agent.persona_evaluation import evaluate_persona_invariance
from agent.persona_presentation import build_presentation, compare_personas
from agent.quality_gate import assess_report
from agent.result_verifier import verify_result
from agent.snapshots import mock_snapshot, reports_from_snapshot
from agent.technical_states import return_state, trend_state, volatility_state, volume_state

CORRECT = dict(zip((f'K{i}' for i in range(1, 9)), ('b', 'c', 'a', 'c', 'a', 'b', 'b', 'c')))


def mock_run(domain, settings=None):
    snap = mock_snapshot()
    report = reports_from_snapshot(snap)[0]
    cls = IndustryBusinessAgent if domain == 'industry_business_model' else TechnicalAnalysisAgent
    settings = settings or AgentSettings(window=20)
    gate, result = execute_report(report, cls(settings=settings), domain, reference_date='2026-10-28',
                                  trading_dates=snap['mockTradingDates'], corporate_actions=[])
    return report, gate, result


# 1. 페르소나 결정 -------------------------------------------------------------

def test_direct_selection_is_confirmed_and_drives_settings():
    profile, reasons = select_persona(literacy='L1', style='C')
    assert profile.confirmed and profile.persona_id == 'L1-C' and reasons == ['사용자 직접 선택']
    s = AgentSettings.from_persona(profile, window=20)
    assert (s.literacy, s.style, s.persona_status) == ('L1', 'C', 'user_confirmed')
    profile, _ = select_persona(literacy='L3', style='U')
    assert AgentSettings.from_persona(profile).style == 'U'


def test_questionnaire_is_suggestion_until_confirmed():
    answers = {'S1': 'A', 'S2': 'A', 'S3': 'A', 'S4': 'C'}
    profile, _ = select_persona(knowledge_answers=CORRECT, style_answers=answers)
    assert profile.persona_id == 'L4-A' and not profile.confirmed
    s = AgentSettings.from_persona(profile)
    assert (s.literacy, s.style, s.persona_status) == ('L2', 'U', 'suggested')  # 미확인은 기본 표현
    profile, _ = select_persona(knowledge_answers=CORRECT, style_answers=answers, confirmed=True)
    assert AgentSettings.from_persona(profile).literacy == 'L4'
    with pytest.raises(ValueError):
        select_persona(literacy='L1', knowledge_answers=CORRECT)
    profile, _ = select_persona()
    assert AgentSettings.from_persona(profile).persona_status == 'unresolved'
    with pytest.raises(TypeError):
        AgentSettings.from_persona({'literacy_level': 'L1'})


@pytest.mark.parametrize('domain', ['industry_business_model', 'technical_analysis'])
def test_presentation_reorders_but_never_drops(domain):
    _, _, result = mock_run(domain)
    sets = {frozenset(s['key'] for s in build_presentation(result, lv, st)['sections'])
            for lv in ['L1', 'L2', 'L3', 'L4'] for st in ['A', 'C', 'U']}
    assert len(sets) == 1
    a = [s['key'] for s in build_presentation(result, 'L2', 'A')['sections']]
    c = [s['key'] for s in build_presentation(result, 'L2', 'C')['sections']]
    risk = 'risk' if domain == 'industry_business_model' else 'volatility'
    assert c.index(risk) < a.index(risk)
    assert build_presentation(result, 'L1', 'U')['glossary'] and not build_presentation(result, 'L4', 'U')['glossary']
    assert build_presentation(result, 'L4', 'U')['showFormula'] and not build_presentation(result, 'L1', 'U')['showFormula']
    assert len(compare_personas(result)) == 12


def test_result_carries_presentation_and_llm_receives_persona_policy():
    class Capture:
        def explain(self, system, payload):
            Capture.system, Capture.payload = system, payload
            return '설명'
    settings = AgentSettings(window=20, literacy='L1', style='C', persona_status='user_confirmed')
    snap = mock_snapshot()
    report = reports_from_snapshot(snap)[0]
    _, result = execute_report(report, TechnicalAnalysisAgent(Capture(), settings=settings), 'technical_analysis',
                               reference_date='2026-10-28')
    assert result['presentation']['personaId'] == 'L1-C'
    assert '쉬운 말' in Capture.system and '위험과 하방 조건' in Capture.system
    assert Capture.payload['presentation']['sections'][1]['key'] == 'volatility'


def test_withheld_result_also_has_presentation():
    report, _, _ = mock_run('technical_analysis')
    gates, _ = assess_report(report, window=20, reference_date='2026-10-28')
    gate = dict(gates['technical_analysis'], status='withheld', label='보류')
    from agent.quality_gate import run_checked
    result = run_checked(TechnicalAnalysisAgent(settings=AgentSettings(window=20, literacy='L1')), report, gate)
    assert result['presentation']['withheldNotice'] and result['presentation']['literacy']['code'] == 'L1'


# 3. 기술 Agent 관측 상태 --------------------------------------------------------

def test_state_bands():
    assert trend_state(100.5, 100)[1] == '이동평균 부근'
    assert trend_state(105, 100)[1] == '이동평균 위' and trend_state(95, 100)[1] == '이동평균 아래'
    assert return_state(0.01) == '작은 변동(상승)' and return_state(-0.05) == '뚜렷한 변동(하락)'
    assert return_state(0.2) == '큰 폭 변동(상승)' and return_state(0) == '변동 없음'
    assert volatility_state(0.5) == '최근 변동성 축소' and volatility_state(2) == '최근 변동성 확대'
    assert volatility_state(1) == '전체 기간과 비슷한 변동성'
    assert volume_state(-0.6) == '거래량 감소' and volume_state(1.2) == '거래량 급증'
    assert volume_state(0.6) == '거래량 증가' and volume_state(0) == '평이한 거래량'


def test_technical_state_claims_link_to_calculations():
    _, _, result = mock_run('technical_analysis', AgentSettings(window=5))
    states = {c['claimId']: c for c in result['claims'] if c['claimId'].startswith('TECH_STATE_')}
    assert set(states) == {'TECH_STATE_TREND', 'TECH_STATE_RETURN', 'TECH_STATE_VOLATILITY', 'TECH_STATE_VOLUME'}
    calc_ids = {c['calculationId'] for c in result['calculations']}
    for claim in states.values():
        assert set(claim['calculationIds']) <= calc_ids
        assert '예측·매매 신호가 아닙니다' in claim['text'] and claim['kind'] == 'interpretation'
        assert claim['stateRule']['ruleVersion'] == 'technical-states-1'
    ratio = next(c for c in result['calculations'] if c['calculationId'] == 'TECH_VOLATILITY_RATIO')
    assert ratio['result'] > 0


def test_volatility_ratio_needs_two_windows():
    _, _, result = mock_run('technical_analysis', AgentSettings(window=20))  # 29 returns < 40
    assert 'TECH_VOLATILITY_RATIO' not in {c['calculationId'] for c in result['calculations']}


# 2. 산업 Agent 문단 분류 기준선 ---------------------------------------------------

def test_rule_classify_priority_and_subsection_hint():
    assert rule_classify('주요 고객과 경쟁사 현황')[0] == 'competition'
    assert rule_classify('주요 원재료 가격 추이')[0] == 'suppliers_materials'
    assert rule_classify('당사는 1990년 설립되었습니다.', '1. 사업의 개요') == ('business_overview', 'subsection:사업의 개요')
    assert rule_classify('특이 사항 없음')[0] == 'other'


def test_industry_result_has_unreviewed_rule_labels():
    _, _, result = mock_run('industry_business_model')
    labels = result['paragraphClassification']
    assert len(labels) == len(result['evidence'])
    assert all(x['reviewStatus'] == 'unreviewed' and x['label'] in LABELS for x in labels)


def test_label_sheet_roundtrip_and_validation(tmp_path):
    report, _, _ = mock_run('industry_business_model')
    rows = paragraphs(report)
    path = export_sheet(rows, tmp_path / 'sheet.csv')
    text = path.read_text(encoding='utf-8-sig')
    assert 'human_label' in text and 'competition' not in text  # 규칙 예측을 미리 채우지 않음
    import csv
    data = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    data[0].update(human_label='경쟁·시장점유율', labeler='A')  # 한글 이름도 허용
    data[1].update(human_label='customers', labeler='A')
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)
    labelled = load_labels(path)
    assert [r['human_label'] for r in labelled] == ['competition', 'customers']
    data[2].update(human_label='없는분류', labeler='A')
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]))
        w.writeheader()
        w.writerows(data)
    with pytest.raises(ValueError, match='알 수 없는 분류'):
        load_labels(path)


def gold(n_docs=4, per_doc=15):
    rows = []
    texts = [('경쟁사 대비 점유율', 'competition'), ('주요 원재료 매입', 'suppliers_materials'),
             ('주요 고객 매출처', 'customers'), ('당사 설립 연혁', 'business_overview')]
    for d in range(n_docs):
        for i in range(per_doc):
            text, label = texts[i % 4]
            rows.append({'evidenceId': f'E{d}_{i}', 'documentId': f'D{d}', 'publishedAt': f'2026-0{d + 1}-01',
                         'text': text, 'subsection': '1. 사업의 개요' if label == 'business_overview' else None,
                         'human_label': label, 'documentVersion': 'v'})
    return rows


def test_evaluate_baseline_metrics_and_warnings():
    result = evaluate(gold())
    assert result['n'] == 60 and result['accuracy'] == 1 and result['warnings'] == []
    small = evaluate(gold(1, 4))
    assert len(small['warnings']) == 2
    wrong = evaluate(gold(), predict=lambda text, sub: 'other')
    assert wrong['accuracy'] == 0 and wrong['method'] == 'custom' and wrong['confusion']


def test_split_holds_out_whole_documents():
    train, test = split_by_document(gold(), 0.25)
    assert {r['documentId'] for r in test} == {'D3'}
    assert not {r['documentId'] for r in train} & {r['documentId'] for r in test}


# 5. ML 확장 판단 ---------------------------------------------------------------

def test_model_adoption_requires_weakness_gain_and_no_leak():
    rows = gold()
    baseline = evaluate(rows, predict=lambda t, s: 'competition' if '경쟁' in t else 'other')
    model = evaluate(rows)
    info = {'modelVersion': 'm1', 'trainingCutoff': '2026-06-30', 'trainingGoldDigest': 'train-digest'}
    assert weaknesses(baseline)
    decision = compare(baseline, model, model_info=info)
    assert decision['adopt'] and decision['macroF1Gain'] > 0
    assert not compare(baseline, model, model_info={**info, 'trainingGoldDigest': model['goldDigest']})['adopt']
    assert not compare(baseline, model, model_info={})['adopt']
    strong = evaluate(rows)
    assert not compare(strong, model, model_info=info)['adopt']  # 약점 없음 → 모델 불필요
    assert not compare(baseline, evaluate(rows[:20]), model_info=info)['adopt']  # 정답셋 다름·표본 부족


# 4. 페르소나 변경 전후 평가표 ------------------------------------------------------

@pytest.mark.parametrize('domain', ['industry_business_model', 'technical_analysis'])
def test_persona_invariance_table_passes(domain):
    report, gate, result = mock_run(domain)
    cls = IndustryBusinessAgent if domain == 'industry_business_model' else TechnicalAnalysisAgent
    table = evaluate_persona_invariance(report, gate, cls, 20)
    assert table['status'] == 'passed' and len(table['rows']) == 12
    assert len({r['표현 차이'] for r in table['rows']}) > 1  # 표현은 실제로 달라짐
    assert verify_result(report, result, AgentSettings(window=20))['status'] == 'review_required'


def test_persona_invariance_detects_persona_dependent_numbers():
    report, gate, _ = mock_run('technical_analysis')

    class Leaky(TechnicalAnalysisAgent):
        def run(self, report, **kwargs):
            result = super().run(report, **kwargs)
            if self.settings.style == 'A':
                result['calculations'][0]['result'] *= 1.1
            return result
    table = evaluate_persona_invariance(report, gate, Leaky, 20)
    assert table['status'] == 'failed'
    failed = [r for r in table['rows'] if r['결과'] == '실패']
    assert {r['페르소나'][-1] for r in failed} == {'A'} and all(r['수치 보존'] == '실패' for r in failed)


def test_verifier_persona_check_present():
    report, _, result = mock_run('industry_business_model')
    checks = {c['검사']: c['상태'] for c in verify_result(report, result, AgentSettings(window=20))['checks']}
    assert checks['페르소나 불변'] == '통과'
    json.dumps(result, ensure_ascii=False, allow_nan=False)
