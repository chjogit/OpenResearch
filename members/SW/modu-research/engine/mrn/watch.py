"""v0.38 T1 「내 관심 종목」 — 사본의 회사 목록에서 쉽게 찾아 저장한다.

- 고르는 법: 가나다순 · 종목코드순 · 시가총액순 / 묶음: 전체 · 코스피200 · 시가총액 상위 100 · 중소형(국내, 시가총액 100위 밖) · 코스피200 밖 국내 · 해외 / 업종 / 이름·코드 검색.
- 시가총액은 사본의 금융위 시세(market_cap)에서, 기준 날짜에 확정된 마지막 거래일 값. 순위는 국내 회사끼리만 센다.
- 「중소형」은 이 앱 사본(230곳, 대부분 코스피200) 안에서의 상대 구분이다 — 시장 전체의 중소형주 목록이 아니다(화면에 함께 적는다).
- 저장은 사용자별 표 하나(watchlist). AI 모델 호출 0회.
"""
from datetime import datetime, timezone

DDL = 'CREATE TABLE IF NOT EXISTS watchlist(owner_id TEXT NOT NULL, ticker TEXT NOT NULL, added_at TEXT NOT NULL, PRIMARY KEY(owner_id, ticker))'
TOP_N = 100
LIMIT = 50                      # 한 사람이 저장할 수 있는 관심 종목 수(자동 확인 비용을 묶어 두기 위함, v0.38 T2에서 씀)
SORTS = ('name', 'code', 'cap')
GROUPS = {'all': '전체', 'kospi200': '코스피200', 'top100': f'시가총액 상위 {TOP_N}', 'smallmid': f'중소형(국내, 시가총액 {TOP_N}위 밖)',
          'kr_other': '코스피200 밖 국내', 'us': '해외'}
SMALLMID_NOTE = f'「중소형」은 이 앱 사본 안에서 시가총액 {TOP_N}위 밖인 국내 회사입니다. 시장 전체의 중소형주 목록이 아닙니다.'
_CAP = {}


def ensure(store):
    with store.lock, store.connect() as c:
        c.execute(DDL)


def caps(cutoff, snapshot=''):
    """{종목: {'date','market_cap'}} — 기준 날짜에 확정된 마지막 거래일의 시가총액(국내, 금융위 시세)."""
    from .market import resolve, load_manifest, read_rows, companies, last_usable_date
    root = resolve(snapshot); man = load_manifest(root); last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], last)
    if key not in _CAP:
        out = {}
        for t, c in companies(root, man).items():
            if c.get('market') != 'KR':
                continue
            rows, _ = read_rows(root, man, 'price_daily', t)
            rs = [r for r in rows if r.get('source') == 'fsc' and r.get('market_cap') and r['trade_date'] <= last]
            if rs:
                r = max(rs, key=lambda r: r['trade_date'])
                out[t] = {'date': r['trade_date'], 'market_cap': int(r['market_cap'])}
        _CAP.clear() if len(_CAP) > 4 else None
        _CAP[key] = out
    return _CAP[key]


def pick_list(cutoff, sort='name', group='all', sector='', q='', snapshot=''):
    """종목 고르기 목록."""
    from .market import resolve, load_manifest, companies
    if sort not in SORTS:
        raise ValueError('정렬은 가나다(name)·종목코드(code)·시가총액(cap) 중 하나예요.')
    if group not in GROUPS:
        raise ValueError('묶음 이름을 알 수 없어요.')
    root = resolve(snapshot); man = load_manifest(root); cos = companies(root, man); cp = caps(cutoff, snapshot)
    rank = {t: i + 1 for i, (t, _) in enumerate(sorted(cp.items(), key=lambda x: (-x[1]['market_cap'], x[0])))}
    rows = []
    for t, c in cos.items():
        kr = c.get('market') == 'KR'
        tags = c.get('index_tags') or []
        r = rank.get(t)
        row = {'ticker': t, 'name': c.get('name') or t, 'market': c.get('market'), 'krx_sector': c.get('krx_sector') or '',
               'kospi200': 'KOSPI200' in tags, 'cap': cp.get(t, {}).get('market_cap'), 'cap_date': cp.get(t, {}).get('date'), 'cap_rank': r}
        ok = {'all': True, 'kospi200': row['kospi200'], 'top100': bool(r and r <= TOP_N), 'smallmid': kr and not (r and r <= TOP_N),
              'kr_other': kr and not row['kospi200'], 'us': not kr}[group]
        if not ok or (sector and row['krx_sector'] != sector):
            continue
        if q:
            s = q.strip().lower().replace(' ', '')
            if s not in row['name'].lower().replace(' ', '') and s not in t.lower():
                continue
        rows.append(row)
    if sort == 'name':
        rows.sort(key=lambda r: (not ('가' <= r['name'][:1] <= '힣'), r['name'], r['ticker']))     # 한글 이름 먼저 가나다순, 영문은 뒤
    elif sort == 'code':
        rows.sort(key=lambda r: r['ticker'])
    else:
        rows.sort(key=lambda r: (r['cap'] is None, -(r['cap'] or 0), r['ticker']))
    sectors = sorted({c.get('krx_sector') for c in cos.values() if c.get('krx_sector')})
    dates = sorted({v['date'] for v in cp.values()})
    return {'snapshot': root.name, 'cutoff': cutoff, 'sort': sort, 'group': group, 'sector': sector, 'q': q, 'count': len(rows), 'rows': rows,
            'groups': [{'key': k, 'label': v} for k, v in GROUPS.items()], 'sectors': sectors,
            'cap_note': f"시가총액: 금융위 시세(사본), 기준 날짜에 확정된 마지막 거래일 값({dates[-1] if dates else '없음'}). 순위는 국내 {len(cp)}곳끼리만 셉니다.",
            'smallmid_note': SMALLMID_NOTE, 'universe_note': f'이 앱 사본의 회사 {len(cos)}곳 안에서만 고를 수 있어요.'}


def listing(store, owner, snapshot=''):
    from .market import resolve, load_manifest, companies
    ensure(store)
    root = resolve(snapshot); cos = companies(root, load_manifest(root))
    with store.connect() as c:
        rs = [dict(r) for r in c.execute('SELECT ticker, added_at FROM watchlist WHERE owner_id=? ORDER BY added_at, ticker', (owner,))]
    return {'rows': [{**r, 'name': (cos.get(r['ticker']) or {}).get('name') or r['ticker'], 'in_snapshot': r['ticker'] in cos} for r in rs], 'limit': LIMIT}


def add(store, owner, ticker, snapshot=''):
    from .market import resolve, load_manifest, companies
    root = resolve(snapshot)
    if ticker not in companies(root, load_manifest(root)):
        raise LookupError('사본에 없는 종목이에요.')
    ensure(store)
    with store.lock, store.connect() as c:
        n = c.execute('SELECT COUNT(*) FROM watchlist WHERE owner_id=?', (owner,)).fetchone()[0]
        have = c.execute('SELECT 1 FROM watchlist WHERE owner_id=? AND ticker=?', (owner, ticker)).fetchone()
        if not have and n >= LIMIT:
            raise ValueError(f'관심회사는 {LIMIT}곳까지 담을 수 있어요.')
        c.execute('INSERT OR IGNORE INTO watchlist VALUES(?,?,?)', (owner, ticker, datetime.now(timezone.utc).isoformat(timespec='seconds')))
        store.audit(c, owner, 'watch.add', ticker)
    return listing(store, owner, snapshot)


def remove(store, owner, ticker, snapshot=''):
    ensure(store)
    with store.lock, store.connect() as c:
        c.execute('DELETE FROM watchlist WHERE owner_id=? AND ticker=?', (owner, ticker))
        store.audit(c, owner, 'watch.remove', ticker)
    return listing(store, owner, snapshot)
