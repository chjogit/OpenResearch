"""Numeric & judgment expression checker — rules v0.3 (_spec/numeric-expressions-v0.3.md).

analyze(text, facts, mode) renders slots with verified values, then finds every numeric or
judgment expression outside the slots and grades it:

  verified   ✅ slot bound to a source fact / quote
  computed   ✅ code calculation from bound facts
  match      🧮 model wording agrees with a code calculation
  mismatch   ⚠️ model wording or number disagrees with the source / calculation
  external   🔵 approved external forecast (slot)
  model      🟡 model judgment / estimate with no way to verify here
  red        🔴 exact number written by the model without a slot
  hidden     trade-instruction words hidden from display (logged)
  info       neutral (period labels, proper nouns)

Research mode flags everything and blocks nothing (except hidden trade words).
Conservative mode drops sentences that contain red / mismatch / model items.
"""
import re
from decimal import Decimal, InvalidOperation

POLICY_VERSION = 'numeric-v0.3.2'
DEGREE_BANDS = {'sharp': Decimal('30'), 'large': Decimal('10'), 'normal': Decimal('3')}  # |%| thresholds
SURPRISE_PCT = Decimal('10')

METRIC_WORDS = [('영업이익', 'operatingProfit'), ('매출', 'revenue'), ('영업활동현금흐름', 'cfo'), ('현금흐름', 'cfo'),
                ('CFO', 'cfo'), ('유동자산', 'currentAssets'), ('유동부채', 'currentLiabilities'), ('자산총계', 'assets'),
                ('총자산', 'assets'), ('자산', 'assets'), ('부채총계', 'liabilities'), ('부채', 'liabilities'),
                ('자본총계', 'equity'), ('자본', 'equity'), ('재고', 'inventory')]
COMPANY_WORDS = [('삼성전자', '005930'), ('삼성', '005930'), ('SK하이닉스', '000660'), ('하이닉스', '000660'), ('SK', '000660')]

PROPER = re.compile(r'(HBM\d+[A-Z]?|DDR\d+X?|LPDDR\d+X?|GDDR\d+X?|\d+\s?나노|갤럭시\s?[A-Z]+\d+\+?|제\s?\d+\s?(기|조|항|호)|\(주\s?\d+\)|'
                    r'K-IFRS\s?\d+호?|005930|000660|N\d{2}|T\d{2}|\d+\s?nm|PCIe\s?\d(\.\d)?|USB\s?\d(\.\d)?|5G|4K|8K)')
PERIOD = re.compile(r'(\d{4}\s?년(\s?[1-4]\s?분기)?|[1-4]\s?분기|[1-4]Q\s?\d{2}|\d{4}\s?[1-4]Q|(상|하)반기|연간|연초|연말|YoY|QoQ|전년\s?(대비|동기)|전분기)')

# Ordered: earlier patterns win on overlap. (category, regex, tier, note)
RULES = [
    ('trade', r'(투자\s?의견\s?(을\s?)?(매수|매도|중립|보유|비중\s?(확대|축소))|(매수|매도)\s?(의견|추천|유지|권고|전환|하라|하세요|할 때|타이밍|를 권|가 유리|기회)|'
              r'비중\s?(확대|축소)|적극\s?매수|강력\s?매수|\b(Strong\s)?(Buy|Sell|Hold|Outperform|Underperform|Overweight|Underweight)\b)', 'hidden', '매매 지시 표현(숨김)'),
    ('flow', r'(외국인|기관|개인|연기금)?\s?(\d+\s?(일|거래일)\s?연속\s?)?(순매수|순매도|매도\s?우위|매수\s?우위)|쌍끌이|대차\s?잔고|공매도(\s?비중)?', 'model', '수급 표현 — 수급 자료 미연결'),
    ('technical', r'신고가|신저가|상한가|하한가|박스권|지지선|저항선|골든\s?크로스|데드\s?크로스|과매수|과매도|RSI\s?\d*|이평선|이동\s?평균선?\s?(돌파|이탈)?|정배열|역배열', 'model', '기술적 표현 — 가격 자료 미연결'),
    ('macro_step', r'베이비\s?스텝|빅\s?스텝|자이언트\s?스텝|울트라\s?스텝|빅\s?컷|금리\s?(동결|인하|인상)|피벗|\d+\s?(회|차례)\s?(인하|인상)', 'model', '거시 정책 표현'),
    ('target', r'목표\s?주가|적정\s?주가|목표가|상승\s?여력|하락\s?여력|업사이드|다운사이드', 'model', '목표주가류 — 외부 전망 없으면 모델 판단'),
    ('valuation', r'저평가|고평가|밸류에이션\s?(매력|부담)|리레이팅|디레이팅|멀티플\s?(확장|축소)|밴드\s?(상단|하단)|역사적\s?(저점|고점)|싸다|비싸다|할인\s?(거래|받)|프리미엄을?\s?받', 'model', '가치 판단'),
    ('consensus', r'컨센(서스)?\s?(상회|하회|부합|대비)|어닝\s?(서프라이즈|쇼크|비트|미스)|서프라이즈|실적\s?쇼크|가이던스\s?(상향|하향)|전망\s?(상향|하향)|추정치\s?(상향|하향)', 'model', '전망 대비 표현 — 승인된 외부 전망 필요'),
    ('turnaround', r'흑자\s?전환|적자\s?전환|적자\s?(지속|축소|확대)|흑자\s?(지속|확대)|턴어라운드|피크\s?아웃|바닥\s?(통과|확인|권)|정점', 'model', '국면 표현'),
    ('outlook', r'((실적|이익|수요|업황|주가|성장|이익\s?개선)\s?)?모멘텀|펀더멘털\s?(개선|악화|강화|훼손|견조)?|(이익|실적)?\s?체력\s?(회복|약화|개선|저하)?|업황\s?(개선|회복|악화|둔화|반등|부진|호조)?|'
                r'(업|다운|슈퍼)\s?사이클|사이클\s?(회복|진입|정점|저점|반등)|수혜(주)?|호조|부진|호실적|어닝\s?시즌|견조|양호|탄탄|강세|약세|기대감|우려|'
                r'불확실성\s?(확대|축소|해소)?|가시성|성장성|경쟁력\s?(강화|약화|우위|열위)?|실적\s?(개선세|호조|부진|기대|우려|눈높이)|레벨\s?업|구조적\s?(성장|변화|하락)|'
                r'성장\s?(스토리|동력|둔화)|이익\s?(훼손|가시성)|눈높이\s?(상향|하향)|센티먼트|투자\s?심리\s?(개선|악화|위축|회복)', 'model', '전망·모멘텀 판단(정성)'),
    ('superlative', r'역대\s?(최고|최대|최저|급)|사상\s?(최대|최고|최저)|최초|처음으로|업계\s?\d+\s?위|세계\s?(최대|1위)|국내\s?(최대|1위)|신기록|최고\s?수준|최저\s?수준', 'model', '순위·최상급 — 전체 비교 자료 없음'),
    ('continuity', r'\d+\s?(년|분기|개월|거래일|일)\s?연속|매년|매\s?분기|연속\s?(흑자|적자|증가|감소)|꾸준히', 'model', '연속·빈도'),
    ('degree', r'급증|급감|급등|급락|대폭|큰\s?폭|소폭|크게\s?(늘|줄|증가|감소|개선|악화)|두\s?자릿수|한\s?자릿수|역성장|반등|둔화|가속|보합|미미', 'model', '변화 정도'),
    ('multiple', r'(두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s?배|곱절|갑절|절반|반토막|\d+\s?분의\s?\d+|(이|삼|사|오|십)\s?분의\s?(일|이|삼)|과반', 'model', '배수·비율 표현'),
    ('vague', r'수\s?(십|백|천)\s?(만|억|조)?\s?(원|달러|%|명|개|건)?|몇\s?(십|백|천|배)|한두|서너', 'model', '막연한 수량(근사)'),
    ('forecast', r'(내년|올해|향후|다음\s?(해|분기))[^.。!?\n]{0,12}(전망|예상|추정|예측)|가능성\s?\d+\s?%|확률이\s?(높|낮)', 'model', '모델 전망·확률'),
    ('kor_number', r'([일이삼사오육칠팔구십백천]{2,}\s?(조|억|만)|[이삼사오육칠팔구]\s?(조|억))(\s?[일이삼사오육칠팔구십백천]+\s?(억|만|천))*\s?(원|달러|%|퍼센트)?', 'red', '한글 수사 수치'),
    ('number', r'(약|대략|거의|무려|최대|최소)?\s?[-+]?\(?\d[\d,]*(\.\d+)?\)?\s?(조|억|만|천)?\s?(원|달러|USD|%p|%|퍼센트|포인트|bp|배|주|건|명|개|대|위)?\s?(내외|가량|정도|수준|육박|돌파|이상|이하|안팎)?', 'red', '모델 작성 수치'),
    ('symbol', r'[↑↓▲▼±≈≒]', 'model', '증감 기호'),
]
COMPILED = [(c, re.compile(p), t, n) for c, p, t, n in RULES]
SLOT = re.compile(r'\{\{\s*(fact|calc|cmp|period|ext|extset|vsext|assume|quote|val)\s*:\s*([^}]*)\}\}')
UP = re.compile(r'(증|늘|상승|확대|개선|급등|반등|가속)')
DOWN = re.compile(r'(감|줄|하락|축소|악화|급락|둔화|역성장)')


def D(v):
    try:
        return Decimal(str(v).replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def fmt_amount(v, unit):
    d = D(v)
    if d is None:
        return f'{v}{unit or ""}'
    s = f'{d:,.0f}' if d == d.to_integral() else f'{d:,.2f}'
    if unit == '백만원' and abs(d) >= 1000000:
        return f'{s}백만원 (약 {d / 1000000:,.1f}조원)'
    return f'{s}{unit or ""}'


# ---------------------------------------------------------------- slots
def _fact(facts, fid):
    return facts.get(fid.strip())


def render_slot(kind, arg, facts, externals, derived=None):
    """Return (text, tier, detail) for one slot."""
    if kind == 'val':  # v0.3.2: a value computed by a node, bound to its output packet
        v = (derived or {}).get(arg.strip())
        if not v:
            return f'[계산값 {arg} 없음]', 'mismatch', '연결된 실행 결과에 없는 계산값'
        return f"{fmt_amount(v['value'], v.get('unit'))}", 'computed', v.get('source', '')
    a = [x.strip() for x in arg.split(',') if x.strip()]
    if kind in ('fact', 'period'):
        f = _fact(facts, a[0]) if a else None
        if not f:
            return '[근거 없음]', 'mismatch', f'{kind} 슬롯 근거 {arg} 없음'
        if kind == 'period':
            return f"{f['period']}년", 'verified', f"{f['fact_id']} 기간"
        return fmt_amount(f['value'], f.get('unit')), 'verified', f"{f['fact_id']} · {f.get('source', {}).get('table_id', '')}"
    if kind == 'calc':
        m = re.fullmatch(r'(pct|diff|ratio|sum)\((.*)\)', arg.strip())
        if not m:
            return '[계산식 오류]', 'mismatch', f'지원하지 않는 계산식 {arg}'
        op, ids = m.group(1), [x.strip() for x in m.group(2).split(',') if x.strip()]
        fs = [_fact(facts, i) for i in ids]
        if not fs or any(f is None for f in fs):
            return '[근거 없음]', 'mismatch', f'계산 입력 없음: {ids}'
        if len({(f.get('unit'), f.get('scope')) for f in fs}) != 1:
            return '[단위·범위 불일치]', 'mismatch', '계산 입력의 단위나 연결/별도 범위가 다름'
        vals = [D(f['value']) for f in fs]
        if op == 'pct':
            if len(vals) != 2 or vals[1] == 0:
                return '[계산 불가]', 'mismatch', 'pct(새값,기준값) 형식 필요'
            r = (vals[0] - vals[1]) / abs(vals[1]) * 100
            return f'{r:+.2f}%', 'computed', f'({ids[0]} − {ids[1]}) / |{ids[1]}| × 100'
        if op == 'diff':
            return fmt_amount(vals[0] - vals[1], fs[0].get('unit')), 'computed', f'{ids[0]} − {ids[1]}'
        if op == 'ratio':
            return f'{vals[0] / vals[1] * 100:.2f}%', 'computed', f'{ids[0]} / {ids[1]} × 100'
        return fmt_amount(sum(vals), fs[0].get('unit')), 'computed', ' + '.join(ids)
    if kind == 'cmp':
        fs = [_fact(facts, i) for i in a[:2]]
        if len(fs) != 2 or None in fs:
            return '[근거 없음]', 'mismatch', '비교 입력 없음'
        if (fs[0].get('unit'), fs[0].get('scope')) != (fs[1].get('unit'), fs[1].get('scope')):
            return '[비교 불가: 단위·범위 다름]', 'mismatch', '단위나 범위가 다름'
        x, y = D(fs[0]['value']), D(fs[1]['value'])
        rel = '큽니다' if x > y else ('작습니다' if x < y else '같습니다')
        return f"{fmt_amount(x, fs[0]['unit'])}로 {fmt_amount(y, fs[1]['unit'])}보다 {rel}", 'computed', f'{a[0]} vs {a[1]}'
    if kind in ('ext', 'extset', 'vsext'):
        e = externals.get(a[0]) if a else None
        if not e:
            return '[승인된 외부 전망 없음]', 'mismatch', f'{kind} 슬롯: 승인된 외부 전망 없음 (T04 미연결)'
        return f"{e['broker']}({e['report_date']}) {fmt_amount(e['value'], e.get('unit'))}", 'external', e.get('report_title', '')
    if kind == 'assume':
        return f'[가정 {arg}]', 'info', '사용자 가정 슬롯'
    return '[원문 인용 저장소 미연결]', 'mismatch', 'quote 슬롯은 아직 원문 구절 저장소가 없음'


# ---------------------------------------------------------------- red-number cross check
def to_million_won(num, scale, unit):
    v = D(num)
    if v is None:
        return None
    mul = {'조': Decimal(10) ** 12, '억': Decimal(10) ** 8, '만': Decimal(10) ** 4, '천': Decimal(10) ** 3}.get(scale or '', Decimal(1))
    if unit == '원':
        return v * mul / Decimal(10) ** 6
    return None


def cross_check(sentence, span_text, facts):
    """Try to match a money figure to a fact by metric/company/year words in the sentence."""
    m = re.search(r'([-+]?\d[\d,]*(?:\.\d+)?)\s?(조|억|만|천)?\s?(원)', span_text)
    if not m:
        return None
    val = to_million_won(m.group(1), m.group(2), m.group(3))
    if val is None:
        return None
    metric = next((k for w, k in METRIC_WORDS if w in sentence), None)
    company = next((c for w, c in COMPANY_WORDS if w in sentence), None)
    years = [int(y) for y in re.findall(r'(20\d{2})\s?년', sentence)]
    if not metric:
        return None
    cands = [f for f in facts.values() if f['metric'] == metric and (not company or f['company'] == company) and (not years or f['period'] in years)]
    if len(cands) != 1:
        return None
    f = cands[0]
    actual = D(f['value'])
    if not actual:
        return None
    err = abs(val - actual) / abs(actual) * 100
    if err <= 3:
        return ('red', f"원문 {f['fact_id']} {fmt_amount(actual, '백만원')}와 근사 일치(오차 {err:.1f}%) — 슬롯 사용 권장")
    return ('mismatch', f"원문과 다름: {f['fact_id']} = {fmt_amount(actual, '백만원')} (차이 {err:.1f}%)")


def degree_band(word):
    if re.search(r'급', word):
        return 'sharp'
    if re.search(r'대폭|큰\s?폭|크게|두\s?자릿수', word):
        return 'large'
    if re.search(r'소폭|보합|미미|한\s?자릿수', word):
        return 'small'
    return None


def band_of(pct):
    a = abs(pct)
    if a >= DEGREE_BANDS['sharp']:
        return 'sharp'
    if a >= DEGREE_BANDS['large']:
        return 'large'
    if a >= DEGREE_BANDS['normal']:
        return 'normal'
    return 'small'


BAND_LABEL = {'sharp': f"±{DEGREE_BANDS['sharp']}% 이상", 'large': f"±{DEGREE_BANDS['large']}~{DEGREE_BANDS['sharp']}%",
              'normal': f"±{DEGREE_BANDS['normal']}~{DEGREE_BANDS['large']}%", 'small': f"±{DEGREE_BANDS['normal']}% 미만"}


# ---------------------------------------------------------------- main
def analyze(text, facts=None, mode='research', externals=None, question='', derived=None):
    facts = facts or {}
    externals = externals or {}
    out, spans = [], []
    # 1) render slots
    pos = 0
    rendered = ''
    for m in SLOT.finditer(text):
        rendered += text[pos:m.start()]
        val, tier, detail = render_slot(m.group(1), m.group(2), facts, externals, derived)
        spans.append({'start': len(rendered), 'end': len(rendered) + len(val), 'text': val, 'category': 'slot:' + m.group(1),
                      'tier': tier, 'detail': detail, 'source': m.group(0)})
        rendered += val
        pos = m.end()
    rendered += text[pos:]
    slot_ranges = [(s['start'], s['end']) for s in spans]

    def taken(a, b):
        return any(a < e and b > s for s, e in slot_ranges + [(x['start'], x['end']) for x in spans])

    # 2) protect proper nouns and period labels (info) first
    for rx, cat in ((PROPER, 'proper'), (PERIOD, 'period')):
        for m in rx.finditer(rendered):
            if not taken(m.start(), m.end()) and m.group(0).strip():
                tier, detail = 'info', '고유명사' if cat == 'proper' else '기간 표기'
                if cat == 'period' and question and m.group(0).replace(' ', '') in question.replace(' ', ''):
                    detail = '기간 표기 (질문과 같음)'
                spans.append({'start': m.start(), 'end': m.end(), 'text': m.group(0), 'category': cat, 'tier': tier, 'detail': detail})
    # 3) rules
    for cat, rx, tier, note in COMPILED:
        for m in rx.finditer(rendered):
            s, e = m.start(), m.end()
            seg = m.group(0)
            lead = len(seg) - len(seg.lstrip())
            s += lead
            seg = seg.strip()
            e = s + len(seg)
            if not seg or taken(s, e):
                continue
            if cat == 'number' and not re.search(r'\d', seg):
                continue
            spans.append({'start': s, 'end': e, 'text': seg, 'category': cat, 'tier': tier, 'detail': note})
    spans.sort(key=lambda x: x['start'])
    # 4) sentence-level checks: degree words vs computed pct; red-number cross check
    bounds = [0] + [m.end() for m in re.finditer(r'(?<!\d)[.!?。](?!\d)|\n', rendered)] + [len(rendered)]
    sentences = []
    for i in range(len(bounds) - 1):
        a, b = bounds[i], bounds[i + 1]
        if not rendered[a:b].strip():
            continue
        sent = rendered[a:b]
        mine = [x for x in spans if a <= x['start'] < b]
        pcts = [D(x['text'].rstrip('%')) for x in mine if x['category'] == 'slot:calc' and x['text'].endswith('%') and x['detail'].startswith('(')]
        for x in mine:
            if x['category'] == 'degree' and pcts:
                p = pcts[0]
                want, have = degree_band(x['text']), band_of(p)
                dir_ok = not ((UP.search(x['text']) and p < 0) or (DOWN.search(x['text']) and p > 0))
                if want is None:
                    x['tier'], x['detail'] = ('match', f'방향 일치 (계산 {p:+.2f}%)') if dir_ok else ('mismatch', f'방향 불일치 (계산 {p:+.2f}%)')
                elif (want == have or (want == 'small' and have == 'small')) and dir_ok:
                    x['tier'], x['detail'] = 'match', f'계산 {p:+.2f}% → 기준({BAND_LABEL[have]})과 일치'
                else:
                    x['tier'], x['detail'] = 'mismatch', f'계산 {p:+.2f}%는 기준상 {BAND_LABEL[have]} 구간인데 「{x["text"]}」이라고 표현'
            if x['category'] == 'number' and x['tier'] == 'red':
                r = cross_check(sent, x['text'], facts)
                if r:
                    x['tier'], x['detail'] = r
        sentences.append({'start': a, 'end': b, 'text': sent.strip(), 'tiers': sorted({x['tier'] for x in mine})})
    # 5) mode
    shown = rendered
    held = []
    for x in sorted(spans, key=lambda x: -x['start']):
        if x['tier'] == 'hidden':
            shown = shown[:x['start']] + '[매매 의견 표현 숨김]' + shown[x['end']:]
    if mode == 'conservative':
        bad = {'red', 'mismatch', 'model', 'hidden'}
        keep = []
        for sn in sentences:
            if bad & set(sn['tiers']):
                held.append({'text': sn['text'], 'reason': '검증되지 않은 수치·판단 표현 포함'})
            else:
                keep.append(rendered[sn['start']:sn['end']])
        shown = ''.join(keep).strip()
    counts = {}
    for x in spans:
        counts[x['tier']] = counts.get(x['tier'], 0) + 1
    return {'policy': POLICY_VERSION, 'mode': mode, 'rendered': rendered, 'display': shown, 'spans': spans,
            'sentences': sentences, 'held': held, 'counts': counts,
            'note': ('연구 모드: 모든 표현을 표시만 하고 막지 않습니다(매매 지시 단어만 숨김). 이 모드에서는 "모델이 숫자를 지어낼 수 없다"가 보장되지 않습니다.'
                     if mode == 'research' else '보수 모드: 검증되지 않은 수치·판단이 있는 문장은 보류합니다.')}
