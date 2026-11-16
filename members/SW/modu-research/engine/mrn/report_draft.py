"""v0.39.4 근거 고정 보고서 초안 (PM 결정 2026-11-15). 「AI는 근거 안에 묶는다」를 보고서 문장에 그대로 적용한다.

- 재료: 한 답 카드(easy.answer)의 줄들만 — 정리 문장, 숫자 줄(값 종류·계산 단계·원문 제목), 아직 모르는 것, 보류, 「이 결과가 아닌 것」. 줄마다 [E1]… 번호.
- AI(use_model=True, 서버에 모델 설정): 번호 붙은 근거 줄만 보고 쓰게 하고, 문장마다 [E번호]를 달게 한다.
- 검사(모든 문장): ① 근거 번호가 있고 실제로 있는 번호인가 ② 문장의 숫자가 그 번호 근거 글자에 그대로 있는가
  ③ 사라·팔라·목표주가·오를/내릴 같은 판단 표현이 없는가. 하나라도 걸리면 그 문장은 빼고 이유를 남긴다.
  남은 문장이 절반 아래면 AI 초안을 버리고 규칙 초안으로(이유 표시).
- AI를 쓰지 않거나 못 쓰면: 규칙 초안(근거 줄을 그대로 엮은 문장 + 번호). AI 호출 0회.
- 초안은 저장하지 않는다(화면이 보여 주고 복사). 감사 기록에는 질문 원문 대신 지문만."""
import hashlib
import json
import os
import re
import urllib.request

PROMPT_VERSION = 'report-draft-v2'   # v2: 날짜 규칙(같은 날 금지·근거 날짜 함께)
NOTICE = ('근거 고정 초안이에요. 문장마다 붙은 [E번호]가 그 문장의 근거이고, 근거에 없는 숫자나 판단(사라·팔라·목표주가·전망 단정)이 든 문장은 자동으로 뺐어요. '
          '사거나 팔라는 판단이 아니에요. 보내기 전에 근거를 눌러 직접 확인하세요.')
JUDGE = re.compile(r'(매수|매도|사야|팔아|살\s?만|사도\s?(돼|될|되)|팔아도|목표\s?주가|적정\s?주가|추천|유망|대박|호재|악재|오를\s?(것|전망|가능)|'
                   r'내릴\s?(것|전망|가능)|떨어질\s?(것|전망|가능)|상승할|하락할|저평가|고평가|비중\s?(확대|축소)|매력적)')
NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')
CITE = re.compile(r'\[E(\d+)\]')
REL_DAY = re.compile(r'(같은\s?날|그\s?날|당일|이날|전날|다음\s?날|오늘|어제|최근일)')   # 날짜를 흐리게 잇는 말
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
FACT_WORDS = re.compile(r'(순매수|순매도|매수세|매도세|매매\s?동향|매수·매도\s?주체)')


def evidence(a):
    """답 카드 → [{id, text, kind, source}] (번호는 1부터)."""
    ev = []

    def add(text, kind, source=''):
        t = re.sub(r'\s+', ' ', str(text or '')).strip()
        if t:
            ev.append({'id': len(ev) + 1, 'text': t[:400], 'kind': kind, 'source': str(source or '')[:200]})
    add(a.get('headline'), '정리 문장')
    seen = set()
    for it in (a.get('key') or []) + (a.get('items') or []):
        k = (it.get('label'), it.get('text'))
        if k in seen:
            continue
        seen.add(k)
        src = (it.get('source') or {}).get('title') or it.get('node_name') or ''
        add(f"{it.get('label')}: {it.get('text')}" + (f" (계산: {it['formula']})" if it.get('formula') else ''), it.get('kind_label') or it.get('tier_label') or '값', src)
    for u in a.get('unknown') or []:
        add(f"아직 모르는 것 — {u.get('text')}", '아직 모르는 것', u.get('node_name'))
    for h in a.get('held') or []:
        add(f"보류된 단계 — {h.get('node_name') or ''}: {h.get('reason') or h.get('text') or ''}", '보류')
    for n in [a.get('not_this')] + list(a.get('notices') or []) + list(a.get('limits') or []):
        add(n if isinstance(n, str) else (n or {}).get('text', ''), '이 결과가 아닌 것')
    return ev[:80]


def _norm(s):
    return s.replace(',', '')


def check(draft, ev):
    """문장마다 검사 → (통과 문장들, 뺀 문장과 이유들)."""
    by = {e['id']: e for e in ev}
    keep, drop = [], []
    for raw in draft.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            keep.append({'text': line, 'cites': [], 'heading': True}); continue
        body = line.lstrip('-•· ').strip()
        cites = [int(x) for x in CITE.findall(body)]
        plain = CITE.sub('', body)
        why = None
        verbatim = bool(cites) and all(c in by for c in cites) and any(plain.strip().rstrip('.').strip() and plain.strip().rstrip('.').strip() in by[c]['text'] for c in cites)
        cited = ' '.join(by[c]['text'] for c in cites if c in by)
        if not cites:
            why = '근거 번호 없음'
        elif any(c not in by for c in cites):
            why = '없는 근거 번호'
        elif verbatim:
            why = None   # 근거 줄을 글자 그대로 옮긴 문장(엔진이 만든 고지 문장 포함)은 통과
        elif JUDGE.search(FACT_WORDS.sub('', plain)):   # 순매수·순매도 같은 사실 용어는 판단 표현이 아님
            why = '판단 표현'
        elif REL_DAY.search(plain):
            why = '날짜를 「같은 날」처럼 흐리게 씀(근거의 날짜를 직접 적어야 함)'
        elif any(d not in cited for d in DATE.findall(plain)):
            why = '인용한 근거에 없는 날짜'
        elif any(DATE.search(by[c]['text']) and not any(d in plain for d in DATE.findall(by[c]['text'])) and
                 any(_norm(n) in _norm(by[c]['text']) for n in NUM.findall(DATE.sub('', plain)) if len(_norm(n)) >= 3) for c in cites):
            why = '근거 줄의 날짜를 빼고 숫자만 옮김(날짜를 함께 적어야 함)'
        else:
            bad = [n for n in NUM.findall(DATE.sub('', plain)) if _norm(n) not in _norm(cited)]
            if bad:
                why = f'근거에 없는 숫자 {", ".join(bad[:3])}'
        (drop if why else keep).append({'text': body, 'cites': cites, 'why': why} if why else {'text': body, 'cites': cites, 'heading': False})
    return keep, drop


def rule_draft(a, ev):
    lines = [f"## {a.get('name') or ''} · {a.get('card_title') or '답 카드'}".strip(), f"- {ev[0]['text']} [E1]" if ev else '']
    facts = [e for e in ev if e['kind'] not in ('정리 문장', '아직 모르는 것', '보류', '이 결과가 아닌 것')]
    if facts:
        lines.append('## 확인된 숫자')
        lines += [f"- {e['text']} [E{e['id']}]" for e in facts[:12]]
    rest = [e for e in ev if e['kind'] in ('아직 모르는 것', '보류', '이 결과가 아닌 것')]
    if rest:
        lines.append('## 아직 모르는 것 · 한계')
        lines += [f"- {e['text']} [E{e['id']}]" for e in rest[:8]]
    return '\n'.join(l for l in lines if l)


def _prompt(a, ev):
    rows = '\n'.join(f"[E{e['id']}] ({e['kind']}) {e['text']}" for e in ev)
    return ('당신은 증권 리서치 보고서의 초안을 쓰는 도우미입니다. 아래 「근거 줄」만 재료로 한국어 초안을 씁니다.\n'
            '규칙:\n1) 모든 문장 끝에 근거 번호를 [E3] 처럼 단다(여러 개면 [E3][E5]). 번호 없는 문장 금지.\n'
            '2) 숫자는 근거 줄에 적힌 글자 그대로만 쓴다(계산·반올림·단위 바꾸기·새 숫자 금지).\n'
            '3) 사라·팔라·목표주가·적정주가·오를/내릴 것·호재·악재·저평가 같은 판단이나 전망 단정은 쓰지 않는다.\n'
            '4) 근거에 없는 사실·배경지식은 쓰지 않는다. 모르면 쓰지 않는다.\n'
            '5) 날짜는 근거 줄에 적힌 날짜를 그대로 적는다. 「같은 날」·「그날」·「당일」처럼 다른 줄의 날짜와 잇지 않는다. 기준일이 다른 자료는 날짜를 나눠 쓴다.\n'
            '6) 형식: 「## 한 줄 정리」 1문장, 「## 확인된 사실」 3~6문장, 「## 계산한 값」 0~4문장, 「## 아직 모르는 것·한계」 1~4문장. 문장마다 줄을 바꾸고 「- 」로 시작.\n'
            f"회사: {a.get('name') or '(여러 회사)'} · 질문: {a.get('card_title') or ''} · 기준: {a.get('cutoff') or '지금'}\n\n근거 줄:\n{rows}\n\n초안만 출력하세요.")


def _call(prompt):
    url = os.environ.get('MODU_NODES_LLM_URL', '').rstrip('/')
    model = os.environ.get('MODU_NODES_LLM_MODEL', '')
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 2000}
    if not model.lower().startswith('claude'):
        body['temperature'] = 0
    headers = {'Content-Type': 'application/json'}
    key = os.environ.get('MODU_NODES_LLM_KEY', '')
    if key:
        headers['Authorization'] = 'Bearer ' + key        # 서버에서만 씀. 화면·기록에 남기지 않음
    req = urllib.request.Request(url + '/chat/completions', data=json.dumps(body).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=float(os.environ.get('MODU_NODES_LLM_TIMEOUT', '60'))) as r:
        out = json.loads(r.read().decode('utf-8'))
    return re.sub(r'<think>.*?</think>', '', out['choices'][0]['message']['content'] or '', flags=re.S)


def draft(a, use_model=False, call=None):
    from .guide import status
    ev = evidence(a)
    out = {'run_id': a.get('run_id'), 'mode': 'rule', 'model': None, 'model_calls': 0, 'prompt_version': PROMPT_VERSION, 'prompt_sha': None,
           'evidence': ev, 'dropped': [], 'notice': NOTICE, 'why': ''}
    st = status()
    if use_model and st['available'] and ev:
        prompt = _prompt(a, ev)
        out.update(model=st['model'], prompt_sha=hashlib.sha256(prompt.encode('utf-8')).hexdigest()[:16])
        try:
            text = (call or _call)(prompt)
            out['model_calls'] = 1
        except Exception as e:
            text = None
            out['why'] = f'AI를 부르지 못해 규칙 초안으로 만들었어요 ({type(e).__name__}).'
        if text:
            keep, drop = check(text, ev)
            body = [k for k in keep if not k['heading']]
            out['dropped'] = drop
            if body and len(body) >= len(drop):
                out.update(mode='model', sentences=keep, draft_md=_md(keep))
                if drop:
                    out['why'] = f'검사에 걸린 문장 {len(drop)}개를 뺐어요.'
                return out
            out['why'] = f'AI 초안의 문장 {len(drop)}개가 검사에 걸려 규칙 초안으로 바꿨어요.'
    elif use_model and not st['available']:
        out['why'] = 'AI 모델이 설정되지 않아 규칙 초안으로 만들었어요.'
    keep, drop = check(rule_draft(a, ev), ev)
    out.update(sentences=keep, draft_md=_md(keep))
    out['dropped'] = out['dropped'] + drop
    return out


def _md(keep):
    return '\n'.join(k['text'] if k['heading'] else f"- {k['text']}" for k in keep)


def audit_detail(r):
    return {'run_id': r.get('run_id'), 'mode': r['mode'], 'model': r['model'], 'model_calls': r['model_calls'], 'prompt_sha': r['prompt_sha'],
            'prompt_version': r['prompt_version'], 'kept': sum(1 for s in r.get('sentences', []) if not s.get('heading')), 'dropped': len(r['dropped'])}
