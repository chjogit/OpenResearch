"""v0.26 AI 길잡이 (T1: 질문 통역 · 사용 안내).

원칙 — 「AI는 길만, 숫자는 앱만」
- 모델은 숫자를 만들지 않는다: 모델이 쓴 글에 숫자가 있으면(원래 질문에 있던 연도만 예외) 버린다.
- 모델의 답은 정해진 선택지(질문 카드 id)와 짧은 질문 문장뿐. 고른 카드는 등록부와 대조하고, 바꾼 질문은 규칙 엔진(조립 에이전트)이
  다시 읽어 알아들을 때만 내보낸다. 실행은 언제나 사람이 누른다.
- 모델 자신의 지식으로 답하지 않게 한다(앱 기능 목록만 준다) → 기준 날짜 뒤 정보가 섞이지 않게.
- 매수·매도·목표주가 질문은 모델을 부르지 않고 규칙으로 정중히 거절한 뒤 판단 재료로 안내한다.
- 모델 호출은 숨기지 않는다: 몇 번, 어떤 모델, 프롬프트 지문. 질문 원문은 감사 기록에 남기지 않는다(지문만).
- 기본은 꺼짐. 서버에 모델이 설정되고(MODU_NODES_LLM_URL·MODEL) 사용자가 켰을 때만 부른다. 아니면 규칙으로 가까운 질문을 찾는다.
"""
import hashlib
import json
import os
import re
import urllib.request

PROMPT_VERSION = 'guide-t1-v2'   # v0.33: 낱말→카드 길잡이표, 「지난 기록을 묻는 말」 규칙
# 판단을 묻는 질문(모델을 부르지 않고 정중히 거절): 플래너의 매매 낱말 + 일상 말투
JUDGE_Q = re.compile(r'(목표\s?주가|적정\s?주가|사도\s?(돼|될|되나)|팔아도|살\s?만|살만|들어가도|담아도|사\s?모아|매수\s?타이밍|언제\s?(사|팔)|오를\s?(까|거)|내릴\s?(까|거)|떨어질\s?(까|거)|유망|대박|추천\s?종목|종목\s?추천)')
FLOW_WORDS = re.compile(r'순매수|순매도|매수세|매도세|매매\s?동향|매수\s?주체|매도\s?주체')   # v0.33: 수급 용어는 판단 표현이 아님
BANNED = re.compile(r'(목표\s?주가|적정\s?주가|매수|매도|사야|팔아|살까|팔까|추천|오를|떨어질|상승할|하락할|수익을|손절|익절|비중\s?(확대|축소))')


def status():
    url = os.environ.get('MODU_NODES_LLM_URL', '').rstrip('/')
    model = os.environ.get('MODU_NODES_LLM_MODEL', '')
    local = bool(re.search(r'//(127\.0\.0\.1|localhost|\[::1\])', url))
    return {'available': bool(url and model), 'model': model or None, 'local': local if url else None,
            'how': '앱 폴더 local-env.cmd 에 set MODU_NODES_LLM_URL=http://127.0.0.1:11434/v1 와 set MODU_NODES_LLM_MODEL=모델이름 을 넣고 stop.cmd → start.cmd'}


def _cards():
    from .easy import CARDS
    return [{'id': c['id'], 'title': c['title'], 'sub': c['sub']} for c in CARDS]


def _years(text):
    return set(re.findall(r'20\d\d', text or ''))


def _clean_text(s, question, limit):
    """모델 글 검사: 길이, 숫자(질문에 있던 연도만 허용), 매매·목표주가 표현. 통과 못 하면 None."""
    s = re.sub(r'\s+', ' ', str(s or '')).strip().strip('"')
    if not s or len(s) > limit:
        return None, '길이'
    rest = s
    for y in _years(question):
        rest = rest.replace(y, '')
    if re.search(r'\d', rest):
        return None, '숫자'
    if BANNED.search(FLOW_WORDS.sub('', s)):
        return None, '판단 표현'
    return s, ''


def rule_suggest(question, cards_ok=None, n=3):
    """모델 없이: 조립 에이전트의 낱말 단서(약한 것 포함)로 가까운 질문 카드를 고른다."""
    from .assembler import parse
    from .easy import CARDS
    P = parse(question)
    score = {}
    for s, gid, _ in P['goals'] + P.get('weak', []):
        for c in CARDS:
            if gid.lower() in c.get('outputs', []):
                score[c['id']] = score.get(c['id'], 0) + s
    ids = [k for k, _ in sorted(score.items(), key=lambda kv: -kv[1])]
    if cards_ok is not None:
        ids = [i for i in ids if i in cards_ok]
    if len(ids) < n:                                              # 단서가 없으면 처음 오는 사람에게 좋은 카드부터
        for d in ('earnings', 'price', 'events', 'forecasts'):
            if d not in ids and (cards_ok is None or d in cards_ok):
                ids.append(d)
    by = {c['id']: c for c in CARDS}
    return [{'id': i, 'title': by[i]['title']} for i in ids[:n]]


HINTS = '\n'.join([   # v0.33: 낱말 → 카드 길잡이(모델이 비슷한 카드 사이에서 헤매지 않게)
    '- 장사·돈 벌이·매출·이익·빚·부채·현금·재무 상태 → earnings',
    '- 달러·원화·환율·금리가 실적에 주는 영향, 오르면/내리면 회사에 어떤지 → macro',
    '- 주가가 오르내린 흐름·하락·급등·거래량·외국인·기관·개인·순매수·공매도·누가 사고팔았나 → price',
    '- 뉴스·이슈·공시·무슨 일·공시 뒤 주가 반응 → events',
    '- 대주주·최대주주·회장·오너·지분·큰손·5% 보고 → holders',
    '- 지수·코스피·환율·금리·수출과 주가가 함께 움직였는지, 경기와의 관계 → relations',
    '- 증권사·애널리스트·전망치·눈높이·컨센서스·내년 실적 예상 → forecasts',
    '- 비싸다·싸다·고평가·주가에 실적이 반영된 정도 → edi',
    '- 이번 분기 매출을 발표 전에 미리 가늠·수출 통계 → nowcast',
    '- 경쟁사·다른 회사와 견주기는 아직 맞는 카드가 없음 → null',
])


def _prompt(question, company_name, cards):
    menu = '\n'.join(f"- {c['id']}: {c['title']} ({c['sub']})" for c in cards)
    words = '매출·영업이익·현금흐름·부채 / 기업가치·DCF / 금리·환율·환율 영향·민감도 / 주가 흐름·이동평균·거래량 / 변동성·낙폭·국면 / 외국인·기관·순매수·공매도 / 엇갈 / 경쟁사·비교기업 / 점유율·경쟁력 / 뉴스·최근 공시 / 공시 후 반응 / 대주주·지분 / 수출·실적 발표 전 / 상관관계·함께 움직 / 컨센서스·전망치'
    return ('당신은 투자 리서치 앱의 길잡이입니다. 사용자의 질문을 이 앱이 알아듣는 질문으로 바꾸고, 가장 가까운 질문 카드를 고르는 일만 합니다.\n'
            '규칙: 1) 숫자를 쓰지 마세요(질문에 있던 연도만 그대로 쓸 수 있음). 2) 사실·전망·매수·매도·목표주가를 말하지 마세요. '
            '3) 앱 기능 목록 밖의 지식으로 답하지 마세요. 4) 카드는 목록의 id만 쓰세요(맞는 카드가 없으면 null).\n'
            '5) 바꾼 질문은 지금까지 기록된 사실·관계를 묻는 말로 쓰세요(앞날을 짐작하거나 좋다·나쁘다를 묻는 말투 금지).\n'
            f'질문 카드 목록:\n{menu}\n\n카드 고르는 길잡이(사용자 말 → 카드):\n{HINTS}\n\n앱이 알아듣는 낱말: {words}\n\n'
            f'회사: {company_name or "(고르지 않음)"}\n사용자 질문: {question}\n\n'
            'JSON 한 줄로만 답하세요: {"card": "카드 id 또는 null", "rewrite": "회사 이름을 넣어 앱이 알아듣는 낱말로 바꾼 질문(40자 안팎)", '
            '"why": "어떻게 바꿨는지 한국어 한 문장"}')


def _call_model(prompt):
    url = os.environ.get('MODU_NODES_LLM_URL', '').rstrip('/')
    model = os.environ.get('MODU_NODES_LLM_MODEL', '')
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 1024}   # v0.39.1 R12
    if not model.lower().startswith('claude'):
        body['temperature'] = 0                                   # Claude 최신 모델은 temperature 를 받지 않음(400)
    body = json.dumps(body).encode()
    headers = {'Content-Type': 'application/json'}
    key = os.environ.get('MODU_NODES_LLM_KEY', '')
    if key:
        headers['Authorization'] = 'Bearer ' + key               # 서버에서만 씀. 화면·기록에 남기지 않음
    req = urllib.request.Request(url + '/chat/completions', data=body, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=float(os.environ.get('MODU_NODES_LLM_TIMEOUT', '30'))) as r:
        out = json.loads(r.read().decode('utf-8'))
    text = re.sub(r'<think>.*?</think>', '', out['choices'][0]['message']['content'] or '', flags=re.S)
    m = re.search(r'\{.*\}', text, re.S)
    return json.loads(m.group(0)) if m else {}


def translate(question, company_name='', cards_ok=None, use_model=False):
    """질문 → {mode, refused, card, rewrite, why, suggestions, model, model_calls, prompt_sha, checks}. 실행은 하지 않는다."""
    from .assembler import assemble
    from .planner import TRADE
    q = (question or '').strip()[:300]
    st = status()
    out = {'mode': 'rule', 'refused': False, 'card': None, 'rewrite': None, 'why': '', 'suggestions': [], 'model': None,
           'model_calls': 0, 'prompt_sha': None, 'prompt_version': PROMPT_VERSION, 'checks': [], 'ai_written': False}
    q_trade = re.sub(r'순매수|순매도|매수세|매도세|매매동향', '', q)
    if TRADE.search(q_trade) or JUDGE_Q.search(q_trade):
        out.update(refused=True, why='사거나 팔지, 목표주가는 판단하지 않아요. 대신 스스로 판단할 재료를 볼 수 있는 질문을 골라 보세요.',
                   suggestions=[s for s in rule_suggest('실적 증권사 전망 주가', cards_ok) if s['id'] in ('earnings', 'forecasts', 'edi', 'price')][:3]
                   or rule_suggest(q, cards_ok))
        return out
    out['suggestions'] = rule_suggest(q, cards_ok)
    if not (use_model and st['available']):
        return out
    cards = _cards()
    prompt = _prompt(q, company_name, cards)
    out.update(mode='model', model=st['model'], prompt_sha=hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16])
    try:
        ans = _call_model(prompt)
        out['model_calls'] = 1
    except Exception as e:
        out.update(mode='rule', why=f'AI 길잡이를 부르지 못해 규칙으로 찾았어요 ({type(e).__name__}).')
        out['checks'].append('모델 호출 실패')
        return out
    ids = {c['id'] for c in cards}
    card = ans.get('card')
    if card in ids and (cards_ok is None or card in cards_ok):
        out['card'] = {'id': card, 'title': next(c['title'] for c in cards if c['id'] == card)}
    elif card not in (None, 'null', ''):
        out['checks'].append(f'목록에 없는 카드라 버림: {str(card)[:20]}')
    rw, why_bad = _clean_text(ans.get('rewrite'), q, 80)
    if rw:
        if company_name and company_name not in rw:
            rw = f'{company_name} {rw}'
        a = assemble(rw)
        if a['status'] == 'ok' and a['targets']:
            out['rewrite'] = rw
        else:
            out['checks'].append('바꾼 질문을 앱이 알아듣지 못해 버림')
    elif ans.get('rewrite'):
        out['checks'].append(f'바꾼 질문에 {why_bad} 문제가 있어 버림')
    why, _ = _clean_text(ans.get('why'), q, 120)
    out['why'] = why or '질문을 앱이 알아듣는 말로 바꿔 봤어요.'
    out['ai_written'] = bool(out['rewrite'] or why)
    if out['card']:
        out['suggestions'] = [s for s in out['suggestions'] if s['id'] != out['card']['id']]
    if not out['card'] and not out['rewrite']:
        out.update(mode='rule', why='AI 길잡이의 답이 앱 규칙을 통과하지 못해 규칙으로 찾은 질문을 보여 드려요.', ai_written=False)
    return out


def audit_detail(question, r):
    """감사 기록: 질문 원문 대신 지문만."""
    return {'q_sha': hashlib.sha256((question or '').encode('utf-8')).hexdigest()[:16], 'mode': r['mode'], 'refused': r['refused'],
            'card': (r['card'] or {}).get('id'), 'rewrite': bool(r['rewrite']), 'model': r['model'], 'model_calls': r['model_calls'],
            'prompt_sha': r['prompt_sha'], 'prompt_version': r['prompt_version'], 'checks': r['checks']}
