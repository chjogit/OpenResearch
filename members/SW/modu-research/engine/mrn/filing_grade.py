"""v0.38 T2-2 공시 등급 — 제목만으로 1·2·3등급(3등급은 상·중·하)을 정한다. 원문 호출 0회, AI 모델 호출 0회.

- 규칙은 설정 파일 `filing_grades.json`(같은 폴더). 위에서부터 차례로 맞춰 처음 맞는 규칙을 쓴다.
- 1등급: 계산으로 숫자가 나옴 · 2등급: 가정을 넣어야 숫자가 나옴 · 3등급: 숫자 없음(상·중·하).
- 방향(좋다·나쁘다) 판단은 하지 않는다. 등급은 「투자자가 알아 둘 필요가 얼마나 큰가」의 묶음일 뿐이다.
- 자회사·종속회사 공시: 이 회사의 숫자로 계산하지 않으므로(T1과 같은 원칙) 1·2등급도 3등급으로 두고, 3등급은 한 단계 낮춘다.
- 맞는 규칙이 없으면 3등급 하 「분류 규칙 없음」 — 지어내지 않고 그대로 보여 준다(규칙을 늘릴 근거로 씀).
- 같은 종류가 많이 나오는 공시(bundle)는 화면에서 회사·종류별로 한 줄로 묶는다(예: 임원·주요주주 지분 보고 9건).
"""
import json
import re
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).with_name('filing_grades.json')
TIERS = ('상', '중', '하')
DOWN = {'상': '중', '중': '하', '하': '하'}
GRADE_LABEL = {1: '숫자로 계산되는 공시', 2: '가정을 넣으면 숫자가 나오는 공시', 3: '숫자 없는 공시'}
TIER_NOTE = {'상': '꼭 알아 둘 공시', '중': '알아 둘 공시', '하': '참고 공시'}
UNMATCHED = {'id': 'unmatched', 'grade': 3, 'tier': '하', 'label': '분류 규칙 없음'}


def norm(report_nm):
    s = re.sub(r'\s+', '', report_nm or '')
    return re.sub(r'^(\[[^\]]*\])+', '', s)


@lru_cache(maxsize=4)
def load(path=str(PATH)):
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    seen = set(); rules = []
    for r in d['rules']:
        if r['id'] in seen:
            raise ValueError(f"등급표: 같은 규칙 이름이 두 번 있어요({r['id']})")
        seen.add(r['id'])
        if r['grade'] not in (1, 2, 3):
            raise ValueError(f"등급표: {r['id']} 등급은 1·2·3 중 하나여야 해요")
        if r['grade'] == 3 and r.get('tier') not in TIERS:
            raise ValueError(f"등급표: {r['id']} 3등급은 상·중·하가 있어야 해요")
        if r['grade'] in (1, 2) and r.get('tier'):
            raise ValueError(f"등급표: {r['id']} 1·2등급에는 상·중·하를 두지 않아요")
        rules.append({**r, '_re': re.compile(r['re'])})
    return {'version': d['version'], 'rules': rules, 'sub': re.compile(d['subsidiary'])}


def classify(report_nm, path=str(PATH)):
    """→ {'grade','tier','rule','label','subsidiary','corrected','bundle'}. tier는 3등급에만."""
    cfg = load(path); raw = re.sub(r'\s+', '', report_nm or ''); n = norm(report_nm)
    rule = next((r for r in cfg['rules'] if r['_re'].search(n)), UNMATCHED)
    sub = bool(cfg['sub'].search(n))
    grade, tier = rule['grade'], rule.get('tier')
    if sub:
        if grade in (1, 2):
            grade, tier = 3, '하'
        else:
            tier = DOWN[tier]
    label = ('자회사 공시 · ' if sub else '') + rule['label']
    return {'grade': grade, 'tier': tier, 'rule': rule['id'], 'label': label, 'subsidiary': sub,
            'corrected': raw.startswith('[') and '정정' in raw.split(']')[0], 'bundle': bool(rule.get('bundle')) and grade == 3}


def board(rows):
    """새 공시 줄들(접수번호 내림차순) → 화면 판: {'computable': [...], '상': [...], '중': [...], '하': [...]}.
    묶음 규칙은 회사·종류별 한 줄로(가장 최근 줄 자리에), 2건 이상일 때만 묶는다.
    묶은 줄은 'group': True 와 count·from·to·rows 를 가진다(한 건짜리는 원래 줄 그대로 — 줄의 'bundle'은 「묶는 종류인가」라는 뜻일 뿐)."""
    out = {'computable': [], '상': [], '중': [], '하': []}
    groups = {}
    for r in rows:
        c = r if 'grade' in r else {**r, **classify(r.get('report_nm'))}
        if c['grade'] in (1, 2):
            out['computable'].append(c); continue
        if c['bundle']:
            k = (c['ticker'], c['rule'], c['subsidiary'])
            if k in groups:
                groups[k]['rows'].append(c); continue
            g = {'group': True, 'ticker': c['ticker'], 'name': c.get('name'), 'rule': c['rule'], 'label': c['label'], 'tier': c['tier'], 'rows': [c]}
            groups[k] = g; out[c['tier']].append(g); continue
        out[c['tier']].append(c)
    for tier in TIERS:
        items = []
        for it in out[tier]:
            if it.get('group'):
                rs = it['rows']
                if len(rs) == 1:
                    items.append(rs[0]); continue
                it['count'] = len(rs); it['from'] = min(x['rcept_dt'] for x in rs); it['to'] = max(x['rcept_dt'] for x in rs)
                it['rcept_no'] = rs[0]['rcept_no']
            items.append(it)
        out[tier] = items
    return out
