"""Planning agent (stage 3): question -> one of the published case templates.

v0.1 deliberately chooses among validated templates instead of free-composing graphs, so a
plan can never produce a workflow that has not been tested. Two paths:
  - keyword planner (always available, deterministic)
  - optional AI model (OpenAI-compatible chat endpoint, e.g. local Ollama), configured only
    through server env vars; its answer must name a known template or the keyword plan is used.
The chosen workflow still passes the normal validator and the self-correcting runner.
"""
import json
import os
import re
import urllib.request

TEMPLATES = [
    {'id': 'facts-only', 'persona': 'novice-narrow', 'title': '공시로 확인된 실적만 보기',
     'does': '삼성전자·SK하이닉스의 2024·2025 매출액·영업이익·현금흐름 등을 공시 원문 셀 그대로 확인',
     'kw': ['실적', '매출', '영업이익', '공시', '재무제표', '현금흐름', '얼마', '확인', '숫자', '이익', '부채', '자산']},
    {'id': 'facts-macro', 'persona': 'novice-wide', 'title': '실적과 거시 환경 함께 보기',
     'does': '실적 사실과 함께 금리·환율 지표 관측값, 회사가 공시에 쓴 거시 노출 문장을 나란히 표시',
     'kw': ['금리', '환율', '거시', '경기', '매크로', '노출', '달러', '원화', '정책', '민감']},
    {'id': 'samsung-broker-dcf', 'persona': 'expert-narrow', 'title': '증권사 전망 한 건으로 기업가치 계산',
     'does': '삼성전자 2025 사실 + 승인된 증권사 전망 1건 + 사용자 가정으로 DCF 주당가치와 민감도 계산',
     'kw': ['기업가치', '가치평가', '적정', 'dcf', '주당', '가치', '밸류', '전망', '증권사', '현금흐름할인']},
    {'id': 'broker-compare', 'persona': 'expert-wide', 'title': '증권사 3곳 전망을 같은 가정에 넣어 비교',
     'does': '같은 사실·가정에 서로 다른 증권사 전망 3건을 넣어 DCF 결과가 얼마나 갈리는지 비교',
     'kw': ['비교', '여러', '증권사별', '차이', '갈리', '3곳', '세 곳', '각각', '시각차', '나란히', '벌어']},
    {'id': 'normalized-scenario', 'persona': None, 'title': '정상화 이익 시나리오',
     'does': '같은 사실·증권사 전망 1건에 정상화 FCFF(정점 이후 정상 현금흐름)만 낮음·중간·높음으로 바꿔 DCF 결과 비교',
     'kw': ['정상화', '정점', '피크', '사이클', '업황', '장기', '말기', '시나리오', '고점', '이후', '정상 이익']},
    {'id': 'price-basic', 'persona': None, 'title': '주가 흐름과 거래량 기본 보기',
     'does': '금융위원회 일별 시세 사본으로 기간 수익률·이동평균·1년 최고/최저·거래량·변동성·최대 낙폭을 계산 (매매 판단 아님)',
     'kw': ['주가', '차트', '추세', '이동평균', '거래량', '변동성', '낙폭', '수익률', '주가 흐름', '기술적', '52주', '고점 대비']},
]
IDS = {t['id'] for t in TEMPLATES}
PERSONA_DEFAULT = {t['persona']: t['id'] for t in TEMPLATES if t['persona']}
TRADE = re.compile(r'(사야|팔아|살까|팔까|매수|매도|들어가도|손절|익절|오를까|떨어질까|타이밍)')
KNOWN_COMPANIES = {'삼성전자': '005930', '삼성': '005930', 'SK하이닉스': '000660', '하이닉스': '000660'}
OTHER_CO = re.compile(r'(LG|현대|카카오|네이버|NAVER|셀트리온|포스코|POSCO|기아|애플|엔비디아|테슬라|마이크론|TSMC)')


def keyword_plan(question, persona=None):
    q = (question or '').lower()
    scores = {t['id']: sum(1 for k in t['kw'] if k.lower() in q) for t in TEMPLATES}
    # comparison words dominate valuation words; macro words dominate plain facts
    if scores['broker-compare'] and scores['samsung-broker-dcf']:
        scores['broker-compare'] += 2
    if scores['facts-macro'] and scores['facts-only']:
        scores['facts-macro'] += 1
    if scores['normalized-scenario'] >= 1 and (scores['samsung-broker-dcf'] or scores['broker-compare']):
        scores['normalized-scenario'] += 2   # long-run normalisation question beats a plain valuation request
    best = max(scores.values())
    if best == 0:
        pick = PERSONA_DEFAULT.get(persona or '', 'facts-only')
        why = '질문에서 고를 단서를 찾지 못해 ' + ('내 유형의 추천 사례' if persona in PERSONA_DEFAULT else '가장 기본 사례') + '를 골랐습니다.'
    else:
        tied = [k for k, v in scores.items() if v == best]
        pick = PERSONA_DEFAULT.get(persona or '') if PERSONA_DEFAULT.get(persona or '') in tied else tied[0]
        t = next(x for x in TEMPLATES if x['id'] == pick)
        hits = [k for k in t['kw'] if k.lower() in q]
        why = f"질문의 단어({', '.join(hits[:5]) or '비교 표현'})가 「{t['title']}」 사례와 가장 잘 맞습니다." + (' 동점이라 내 유형 추천을 우선했습니다.' if len(tied) > 1 else '')
    return pick, why, scores


def notes_for(question, pick):
    q = question or ''
    notes = []
    if TRADE.search(q):
        notes.append('사거나 팔지, 오를지에 대한 판단은 하지 않습니다. 대신 확인된 사실과 「이 가정이라면」의 계산을 보여 드립니다.')
    if OTHER_CO.search(q):
        notes.append('현재 저장된 공식 원문은 삼성전자·SK하이닉스뿐입니다. 다른 기업은 아직 조사할 수 없습니다.')
    if ('하이닉스' in q) and pick in ('samsung-broker-dcf', 'broker-compare', 'normalized-scenario'):
        notes.append('증권사 전망 자료는 삼성전자 보고서만 있어 가치평가는 삼성전자로 계산합니다. SK하이닉스는 실적 사례에서 볼 수 있습니다.')
    return notes


def model_plan(question, persona):
    url = os.environ.get('MODU_NODES_LLM_URL', '').rstrip('/')
    model = os.environ.get('MODU_NODES_LLM_MODEL', '')
    if not url or not model:
        return None, '모델 미설정 (MODU_NODES_LLM_URL / MODU_NODES_LLM_MODEL)'
    menu = '\n'.join(f"- {t['id']}: {t['title']} — {t['does']}" for t in TEMPLATES)
    prompt = ('다음 투자 리서치 질문에 가장 맞는 사례 하나를 고르세요. 목록 밖의 id는 쓰지 마세요.\n'
              f'사례 목록:\n{menu}\n\n사용자 유형: {persona or "미정"}\n질문: {question}\n\n'
              'JSON 한 줄로만 답하세요: {"example_id": "...", "reason": "한국어 한 문장"}')
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 1024}   # v0.39.1 R12
    if not model.lower().startswith('claude'):
        body['temperature'] = 0                                   # Claude 최신 모델은 temperature 를 받지 않음(400)
    body = json.dumps(body).encode()
    headers = {'Content-Type': 'application/json'}
    key = os.environ.get('MODU_NODES_LLM_KEY', '')
    if key:
        headers['Authorization'] = 'Bearer ' + key   # server-side only; never sent to the browser or logged
    try:
        req = urllib.request.Request(url + '/chat/completions', data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=float(os.environ.get('MODU_NODES_LLM_TIMEOUT', '30'))) as r:
            out = json.loads(r.read().decode('utf-8'))
        text = re.sub(r'<think>.*?</think>', '', out['choices'][0]['message']['content'] or '', flags=re.S)
        m = re.search(r'\{[^{}]*"example_id"[^{}]*\}', text, re.S)
        ans = json.loads(m.group(0)) if m else {}
        if ans.get('example_id') in IDS:
            return {'example_id': ans['example_id'], 'reason': str(ans.get('reason', ''))[:300]}, f'모델 {model}'
        return None, f'모델 답이 목록에 없는 사례라 버렸습니다: {str(ans.get("example_id"))[:40]}'
    except Exception as e:
        return None, f'모델 호출 실패: {type(e).__name__}'


def plan(question, persona=None, use_model=True):
    question = (question or '').strip()[:500]
    kw_pick, kw_why, scores = keyword_plan(question, persona)
    method, model_note, pick, why = 'keyword', '', kw_pick, kw_why
    if use_model:
        ans, model_note = model_plan(question, persona)
        if ans:
            method, pick, why = 'model', ans['example_id'], ans['reason'] or '모델이 고른 사례입니다.'
    t = next(x for x in TEMPLATES if x['id'] == pick)
    return {'question': question, 'example_id': pick, 'title': t['title'], 'reason': why, 'method': method,
            'model_note': model_note, 'keyword_choice': kw_pick, 'scores': scores, 'notes': notes_for(question, pick),
            'alternatives': [{'id': x['id'], 'title': x['title']} for x in TEMPLATES if x['id'] != pick]}
