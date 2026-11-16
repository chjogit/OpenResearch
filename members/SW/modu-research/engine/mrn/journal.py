"""v0.32 T2 가설 일지 — 내가 적은 실적 가정(모두의 가정 기록)을 한곳에 모으고, 실제가 공시되면 채점한다.

원칙
- 새 숫자를 지어내지 않는다: 내 가정 = crowd_assumptions(내가 적은 값), 그때 증권사 = 승인 전망 집계(그 날짜까지),
  실제 = 공시 API 연간 재무(사업보고서) 값.
- 미래 정보 금지: 실제가 공시된 날 이전에 적은 가정만 채점한다. 공시 뒤에 적은 것은 「채점 안 함」.
- 메모(왜 이렇게 봤나)는 나만 본다. 감사 기록에는 글 내용을 남기지 않는다.
- 새 표 하나(hypothesis_notes)만 더한다. 기존 표는 읽기만.
"""
from decimal import Decimal

NOTE_MAX = 300
DDL = """CREATE TABLE IF NOT EXISTS hypothesis_notes(
  owner_id TEXT NOT NULL, ticker TEXT NOT NULL, fiscal_year INTEGER NOT NULL, metric TEXT NOT NULL, period TEXT NOT NULL,
  note TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(owner_id, ticker, fiscal_year, metric, period))"""


def ensure(store):
    with store.lock, store.connect() as c:
        c.execute(DDL)


def entries(store, owner):
    ensure(store)
    with store.connect() as c:
        rows = [dict(r) for r in c.execute('SELECT ticker, fiscal_year, metric, period, value_mn, submitted_at FROM crowd_assumptions '
                                           'WHERE owner_id=? ORDER BY ticker, fiscal_year, metric, submitted_at', (owner,))]
        notes = {(r['ticker'], r['fiscal_year'], r['metric'], r['period']): r['note'] for r in
                 c.execute('SELECT ticker, fiscal_year, metric, period, note FROM hypothesis_notes WHERE owner_id=?', (owner,))}
    for r in rows:
        r['note'] = notes.get((r['ticker'], r['fiscal_year'], r['metric'], r['period']), '')
    return rows


def save_note(store, owner, ticker, fy, metric, period, note, at):
    ensure(store)
    note = (note or '').strip()
    if len(note) > NOTE_MAX:
        raise ValueError(f'메모는 {NOTE_MAX}자까지 적을 수 있어요.')
    with store.lock, store.connect() as c:
        ok = c.execute('SELECT 1 FROM crowd_assumptions WHERE owner_id=? AND ticker=? AND fiscal_year=? AND metric=? AND period=?',
                       (owner, ticker, int(fy), metric, period)).fetchone()
        if not ok:
            raise LookupError('그 가정을 찾지 못했어요. 먼저 가정을 적어 주세요.')
        if note:
            c.execute('INSERT OR REPLACE INTO hypothesis_notes VALUES(?,?,?,?,?,?,?)', (owner, ticker, int(fy), metric, period, note, at))
        else:
            c.execute('DELETE FROM hypothesis_notes WHERE owner_id=? AND ticker=? AND fiscal_year=? AND metric=? AND period=?',
                      (owner, ticker, int(fy), metric, period))
        store.audit(c, owner, 'journal.note', f'{ticker}:{fy}:{metric}:{period}', {'chars': len(note)})   # 글 내용은 남기지 않음


def _pct(a, b):
    a, b = Decimal(str(a)), Decimal(str(b))
    return (a / b - 1) * 100 if b else None


def score(entry, actual, broker_then):
    """entry: 내 가정 1건, actual: (값 백만원, 공시일) 또는 None, broker_then: 그 날짜 집계 한 점 또는 None."""
    out = {'status': 'pending', 'mine_err_pct': None, 'broker_err_pct': None, 'closer': None}
    if not actual or not actual[0] or not actual[1]:
        return out
    if str(entry['submitted_at'])[:10] >= str(actual[1])[:10]:
        out['status'] = 'after'                 # 공시 당일·뒤에 적음 → 채점 안 함
        return out
    me = _pct(entry['value_mn'], actual[0])
    out.update(status='scored', mine_err_pct=f'{me:.1f}' if me is not None else None)
    if broker_then:
        br = _pct(broker_then['median'], actual[0])
        out['broker_err_pct'] = f'{br:.1f}' if br is not None else None
        if me is not None and br is not None:
            d = abs(me) - abs(br)
            out['closer'] = 'tie' if abs(d) < Decimal('0.05') else ('me' if d < 0 else 'broker')
    return out


def build(store, owner, trend_of, actual_of, name_of=lambda t: None):
    """trend_of(ticker, fy, metric) → forecasts.trend 결과 또는 None
       actual_of(ticker, fy, metric) → (값 백만원 문자열, 공시일 YYYY-MM-DD) 또는 None"""
    from . import forecasts as FC
    groups, cache = {}, {}
    for r in entries(store, owner):
        k = (r['ticker'], int(r['fiscal_year']), r['metric'])
        if k not in cache:
            try:
                tr = trend_of(*k)
            except Exception:
                tr = None
            try:
                act = actual_of(*k)
            except Exception:
                act = None
            cache[k] = (tr, act)
            groups[k] = {'ticker': k[0], 'name': name_of(k[0]) or k[0], 'fiscal_year': k[1], 'metric': k[2],
                         'metric_label': FC.METRICS.get(k[2], k[2]), 'actual': {'value_mn': act[0], 'disclosed': act[1]} if act else None,
                         'entries': []}
        tr, act = cache[k]
        bt = FC.as_of(tr, r['submitted_at']) if tr else None
        crowd = FC.crowd_stats(store.crowd_values(k[0], k[1], k[2], until=r['submitted_at']))
        groups[k]['entries'].append({**r, 'broker_then': {kk: bt[kk] for kk in ('date', 'n', 'median', 'min', 'max', 'thin')} if bt else None,
                                     'crowd_then': crowd if crowd.get('shown') else {'n': crowd['n'], 'shown': False},
                                     **score(r, act, bt)})
    G = sorted(groups.values(), key=lambda g: (g['actual'] is None, g['ticker'], g['fiscal_year'], g['metric']))
    sc = [e for g in G for e in g['entries'] if e['status'] == 'scored']
    mean = lambda xs: f'{sum(xs) / len(xs):.1f}' if xs else None
    me = [abs(Decimal(e['mine_err_pct'])) for e in sc if e['mine_err_pct'] is not None]
    br = [abs(Decimal(e['broker_err_pct'])) for e in sc if e['broker_err_pct'] is not None]
    summary = {'entries': sum(len(g['entries']) for g in G), 'topics': len(G), 'scored': len(sc),
               'pending': sum(1 for g in G for e in g['entries'] if e['status'] == 'pending'),
               'notes': sum(1 for g in G for e in g['entries'] if e['note']),
               'mine_abs_err': mean(me), 'broker_abs_err': mean(br),
               'closer_me': sum(1 for e in sc if e['closer'] == 'me'), 'closer_broker': sum(1 for e in sc if e['closer'] == 'broker')}
    return {'summary': summary, 'groups': G,
            'rule': '실제가 공시되기 전에 적은 가정만 채점해요. 오차 = 내 가정 ÷ 실제 − 1. 「그때 증권사」는 내가 적은 날까지 나온 승인 전망 집계 중앙값이에요(컨센서스 아님).'}
