"""v0.27: 관심 체온계 — 네티즌 반응 자료의 2차 가공 (네티즌 반응-주가 프레임워크 T1). AI 모델 호출 0회.

2차 가공 (tests/test_attention.py 로 고정)
1. 누적 → 하루 증가량: 네이버 검색 결과 수(블로그·카페·뉴스)는 수년 치가 쌓인 누적값이다. 수집은 약 8시간 간격으로 불규칙하므로
   거래일마다 장 마감(15:30 KST) 시각의 누적값을 앞뒤 수집값으로 보간하고, 장 마감~장 마감 사이 새 글을 24시간 기준으로 환산한다
   (주말을 낀 월요일도 하루치로 비교 가능). 기준시점 뒤에 수집된 값은 보간에도 쓰지 않는다.
   - 품질 표시: 음수 증가(검색 색인 변동) → 버림, 다른 날 중앙값의 JUMP_X배 넘는 증가(수집 시작·색인 몰림) → 버림, 간격 → 표시.
2. 평소 대비 배수에서 시장 전체를 뺀다: 회사 배수 = 오늘 ÷ 이 회사의 평소(중앙값), 시장 배수 = 같은 날 모든 회사 배수의 중앙값,
   시장 감안 배수 = 회사 배수 ÷ 시장 배수. 기간이 짧을 때 「시장 전체가 시끄러웠던 날」이 회사 신호처럼 보이는 착시를 막는다.
3. 유튜브 댓글: 본문 없이 날짜와 영상 번호만으로 하루 댓글 수 · 영상 수 · 가장 많이 몰린 영상의 비중.
4. 감성 점수: 점수가 붙은 글의 비율을 항상 함께 낸다(25% 미만이면 참고하기 어렵다고 표시).
5. 가격과 맞대기(모든 회사 묶음): 회사·날짜 효과를 뺀 뒤 같은 날 거래량과의 관계, 다음 날 거래량·변동성과의 관계(당일 거래량·변동 통제).
   서로 다른 거래일이 MIN_DATES 보다 적으면 다음 날 관계는 「기록 부족」으로 보류한다.

원칙: 그때 알 수 있던 것만(기준시점 뒤 수집값 제외) · 매수·매도·목표주가 표현 없음 · 「인과 아님」 · 사람·채널을 지목하지 않음.
"""
import bisect
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .market import (KST, SnapshotError, _src, companies, last_usable_date, load_manifest, read_rows, resolve)

CLOSE = (15, 30)
MAX_SPAN_H = 18       # 앞뒤 수집값 간격이 이보다 길면 보간하지 않는다
NEAR_H = 1.0          # 마감 뒤 수집값이 없을 때, 마감 전 이 시간 안의 값은 그대로 쓴다
BASE_MIN = 3           # 평소(중앙값)를 말하려면 그날 이전 기록이 최소 이만큼
BASE_MAX = 40          # 평소는 최근 40거래일까지
MARKET_OK = (1 / 3, 3.0)  # 시장 배수가 이 범위 밖이면(포털 색인 몰림 등) 시장 감안을 보류한다
JUMP_X = 10.0          # 다른 날 중앙값의 10배 넘는 하루 증가는 수집 효과로 보고 뺀다
MIN_DATES = 20         # 다음 날 관계를 말하려면 서로 다른 거래일이 이만큼 필요
T_LINK = 2.5
SENT_MIN_COVER = 0.25
POST = ('naver_blog', 'naver_cafe')     # 투자자 글(블로그·카페) — 기사(naver_news)와 나눠 센다
CH_LABEL = {'naver_blog': '블로그', 'naver_cafe': '카페', 'naver_news': '뉴스 기사'}
NOTICE = ('관심 체온계는 포털 검색 결과 수와 영상 댓글 수를 하루 단위로 바꾼 기록입니다. 글의 내용이나 사실 여부는 보지 않으며, '
          '관심이 주가를 움직였다는 뜻(인과)이 아닙니다. 매수·매도 추천이나 주가 예측이 아닙니다.')


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def adjust(own, mkt):
    """시장 감안 배수. 시장 배수가 MARKET_OK 밖이면 None (나눗셈이 과장을 만든다)."""
    if not own or not mkt or not (MARKET_OK[0] <= mkt <= MARKET_OK[1]):
        return None
    return own / mkt


def _median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def close_at(d):
    """거래일 d 의 장 마감 시각(KST, aware)."""
    y, m, dd = map(int, d.split('-'))
    return datetime(y, m, dd, CLOSE[0], CLOSE[1], tzinfo=KST)


def at_close(caps, d, max_span_h=MAX_SPAN_H):
    """수집값 [(시각, 누적)] → 장 마감 시각의 누적값. 앞뒤 수집값 사이를 직선 보간(간격 max_span_h 이내),
    뒤 수집값이 없으면 마감 전 NEAR_H 시간 안의 값을 그대로 쓴다. 못 구하면 None."""
    T = close_at(d)
    i = bisect.bisect_right([c[0] for c in caps], T)
    before = caps[i - 1] if i > 0 else None
    after = caps[i] if i < len(caps) else None
    if before and before[0] == T:
        return before[1]
    if before and after and (after[0] - before[0]).total_seconds() <= max_span_h * 3600:
        w = (T - before[0]).total_seconds() / (after[0] - before[0]).total_seconds()
        return before[1] + (after[1] - before[1]) * w
    if before and (T - before[0]).total_seconds() <= NEAR_H * 3600:
        return before[1]
    return None


def increments(rows, cal, until=None):
    """mention_count 행 → {채널: {거래일: {'new', 'hours', 'flags'}}}.
    new = 직전 거래일 장 마감 ~ 이 거래일 장 마감 사이 새 글을 24시간 기준으로 환산한 값. 버린 날도 flags 와 함께 남긴다(new=None)."""
    caps = defaultdict(list)
    for r in rows:
        at = r.get('captured_at')
        tot = _f(r.get('total'))
        if not at or tot is None:
            continue
        at = datetime.fromisoformat(str(at).replace('Z', '+00:00')).astimezone(KST)
        if until is not None and at > until:
            continue
        caps[r.get('source')].append((at, tot))
    out = {}
    for src, cs in caps.items():
        cs.sort()
        lv = [(d, at_close(cs, d)) for d in cal if cs[0][0] <= close_at(d) + timedelta(hours=NEAR_H)]
        lv = [(d, v) for d, v in lv if v is not None]
        days = {}
        for (d0, a), (d1, b) in zip(lv, lv[1:]):
            hours = (close_at(d1) - close_at(d0)).total_seconds() / 3600
            flags = ['gap'] if hours > 96 else []
            if b < a:
                days[d1] = {'new': None, 'hours': hours, 'flags': flags + ['negative_delta']}
                continue
            days[d1] = {'new': (b - a) * 24 / hours, 'hours': hours, 'flags': flags}
        orig = {d: v['new'] for d, v in days.items() if v['new'] is not None}
        if len(orig) >= 4:
            for d, x in orig.items():
                med = _median([y for dd, y in orig.items() if dd != d])
                if med and med > 0 and x > JUMP_X * med:
                    days[d]['flags'].append('jump')
                    days[d]['new'] = None
        out[src] = days
    return out


def youtube_daily(rows, cal, last):
    """유튜브 댓글 행(본문 없음) → {거래일: {'comments', 'videos', 'top_share'}}. 영상 번호는 링크의 v= 값."""
    by = defaultdict(Counter)
    for r in rows:
        if r.get('source') != 'youtube_comment':
            continue
        d0 = str(r.get('published_at') or '')[:10]
        if not d0 or d0 > last:
            continue
        i = bisect.bisect_left(cal, d0)
        if i >= len(cal):
            continue
        m = re.search(r'[?&]v=([\w-]+)', r.get('url') or '')
        by[cal[i]][m.group(1) if m else '?'] += 1
    out = {}
    for d, c in by.items():
        n = sum(c.values())
        out[d] = {'comments': n, 'videos': len(c), 'top_share': max(c.values()) / n}
    return out


def _calendar(root, man, cos, last):
    """거래일 달력: 사본에서 가격 행이 가장 많은 회사(보통 대형주)의 날짜."""
    best = None
    for t in ('005930', '000660'):
        rows, _ = read_rows(root, man, 'price_daily', t)
        if rows:
            best = rows
            break
    if best is None:
        parts = (man['tables'].get('price_daily') or {}).get('parts') or {}
        t = next(iter(sorted(parts)), None)
        best = read_rows(root, man, 'price_daily', t)[0] if t else []
    cal = sorted({r['trade_date'][:10] for r in best if r.get('source') == 'fsc' and r['trade_date'][:10] <= last})
    # 마지막 거래일 뒤 수집값을 다음 거래일로 보낼 자리 — 주말을 건너뛴 다음 평일 3일을 덧붙인다(그날 값은 가격과 맞대지 않음)
    d = datetime.fromisoformat(cal[-1]).date() if cal else None
    extra = []
    while d and len(extra) < 3:
        d += timedelta(days=1)
        if d.weekday() < 5:
            extra.append(d.isoformat())
    return cal, cal + extra


def _volumes(root, man, t, last):
    rows, meta = read_rows(root, man, 'price_daily', t)
    v = sorted((r['trade_date'][:10], _f(r.get('volume')), _f(r.get('close'))) for r in rows if r.get('source') == 'fsc' and r['trade_date'][:10] <= last)
    return [x for x in v if x[1] is not None and x[2]], meta


def abnormal_all(vol):
    """회사 전체 [(로그 거래량 배수, |수익률|)] — abnormal() 과 같은 값을 이동 창으로 한 번에."""
    out = [(None, None)] * len(vol)
    win = []
    for i in range(len(vol)):
        if i >= 1:
            bisect.insort(win, vol[i - 1][1])
        if i >= 21:
            win.pop(bisect.bisect_left(win, vol[i - 21][1]))
            med = (win[9] + win[10]) / 2
            if med > 0 and vol[i][1] > 0:
                out[i] = (math.log(vol[i][1] / med), abs(vol[i][2] / vol[i - 1][2] - 1))
    return out


def abnormal(vol, i):
    """i일 거래량 ÷ 직전 20거래일 중앙값의 로그, |수익률|."""
    if i < 21:
        return None, None
    med = _median([x[1] for x in vol[i - 20:i]])
    if not med or vol[i][1] <= 0:
        return None, None
    return math.log(vol[i][1] / med), abs(vol[i][2] / vol[i - 1][2] - 1)


# ---------------------------------------------------------------- 모든 회사 묶음 (시장 배수 · 가격과의 관계)
_CACHE = {}


def panel(cutoff='', snapshot=''):
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], last, cutoff[:16])
    if key in _CACHE:
        return _CACHE[key]
    until = datetime.fromisoformat(cutoff)
    cos = companies(root, man)
    cal, cal_ext = _calendar(root, man, cos, last)
    parts = (man['tables'].get('mention_count') or {}).get('parts') or {}     # 없으면 빈 체온계(데이터랩만으로도 동작)
    inc, src_files = {}, {}
    for t in sorted(parts):
        c = cos.get(t, {})
        if c and c.get('market') not in (None, 'KR'):
            continue
        rows, m = read_rows(root, man, 'mention_count', t)
        inc[t] = increments(rows, cal_ext, until)
        src_files[t] = m['sha256']
    posts = {}
    for t, ch in inc.items():
        days = {}
        for s in POST:
            for d, v in (ch.get(s) or {}).items():
                if v['new'] is None:
                    continue
                days[d] = days.get(d, 0.0) + v['new']
        posts[t] = days
    # 회사 배수 = 오늘 ÷ 이 회사의 다른 날 중앙값, 시장 배수 = 같은 날 회사 배수의 중앙값
    own = {}
    for t, days in posts.items():       # 평소 = 그날 이전 날들의 중앙값(최근 BASE_MAX일, 최소 BASE_MIN일) — 뒤의 값을 쓰지 않는다
        ds = sorted(days)
        for k, d in enumerate(ds):
            prior = [days[x] for x in ds[max(0, k - BASE_MAX):k]]
            if len(prior) < BASE_MIN:
                continue
            base = _median(prior)
            if base and base > 0:
                own.setdefault(t, {})[d] = days[d] / base
    by_day = defaultdict(list)
    for t, m in own.items():
        for d, x in m.items():
            by_day[d].append(x)
    market = {d: _median(xs) for d, xs in by_day.items() if len(xs) >= 10}
    # 가격과 맞대기: 회사·날짜 효과를 뺀 관심(로그 새 글)과 거래량
    obs = []
    for t, days in posts.items():
        if not days:
            continue
        vol, _ = _volumes(root, man, t, last)
        idx = {d: i for i, (d, _, _) in enumerate(vol)}
        for d, x in days.items():
            i = idx.get(d)
            if i is None or i + 1 >= len(vol):
                continue
            v0, r0 = abnormal(vol, i)
            v1, r1 = abnormal(vol, i + 1)
            if v0 is None or v1 is None:
                continue
            obs.append({'t': t, 'd': d, 'a': math.log1p(x), 'v0': v0, 'r0': r0, 'v1': v1, 'r1': r1})
    rel = relation(obs)
    res = {'cutoff': cutoff, 'last_usable_date': last, 'snapshot': root.name, 'manifest_sha256': man['_manifest_sha256'],
           'n_companies': len(posts), 'trade_days': sorted(market), 'market_multiple': market, 'relation': rel,
           '_posts': posts, '_own': own, '_inc': inc, '_cal': cal, '_cal_ext': cal_ext,
           'source': {'mentions': {'table': 'core.mention_count', 'files': len(src_files), 'origin': '네이버 검색 API 결과 수(포털, 연구용)'}}}
    _CACHE.clear()
    _CACHE[key] = res
    return res


def _demean_np(cols, gids, rounds=8):
    """회사·날짜 두 갈래 평균을 번갈아 빼기(numpy)."""
    import numpy as np
    out = {k: np.asarray(v, dtype=float).copy() for k, v in cols.items()}
    for _ in range(rounds):
        for g, n in gids:
            cnt = np.bincount(g, minlength=n)
            for k in out:
                out[k] -= (np.bincount(g, weights=out[k], minlength=n) / np.maximum(cnt, 1))[g]
    return out


def _resid_np(y, X):
    import numpy as np
    Xm = np.column_stack([np.ones(len(y))] + list(X))
    beta, *_ = np.linalg.lstsq(Xm, y, rcond=None)
    return y - Xm @ beta


def _corr(a, b):
    import numpy as np
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if len(a) < 3 or a.std() == 0 or b.std() == 0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def relation(obs, lag_word='다음 날'):
    """회사·날짜 효과를 뺀 관계 기록. 같은 날 = 함께 움직임, 다음 날 = 당일 거래량·|수익률| 통제 뒤 편상관."""
    import numpy as np
    n_dates = len({o['d'] for o in obs})
    n_co = len({o['t'] for o in obs})
    out = {'n': len(obs), 'n_dates': n_dates, 'n_companies': n_co, 'min_dates': MIN_DATES, 'method': '회사·날짜 효과 제거 뒤 상관(편상관)'}
    if len(obs) < 30 or n_dates < 3:
        return out | {'verdict': 'held', 'line': '관심과 거래량을 맞대 볼 기록이 아직 너무 적어요.'}
    _, gt = np.unique([o['t'] for o in obs], return_inverse=True)
    _, gd = np.unique([o['d'] for o in obs], return_inverse=True)
    C = _demean_np({k: [o[k] for o in obs] for k in ('a', 'v0', 'r0', 'v1', 'r1')}, [(gt, n_co), (gd, n_dates)])
    dof = len(obs) - n_co - n_dates - 2

    def tval(r):
        return None if r is None or abs(r) >= 1 or dof <= 0 else r * math.sqrt(dof / (1 - r * r))
    same_v, same_r = _corr(C['a'], C['v0']), _corr(C['a'], C['r0'])
    ea = _resid_np(C['a'], [C['v0'], C['r0']])
    nv = _corr(ea, _resid_np(C['v1'], [C['v0'], C['r0']]))
    nr = _corr(ea, _resid_np(C['r1'], [C['v0'], C['r0']]))
    out.update(same_day_volume=same_v, same_day_volume_t=tval(same_v), same_day_absret=same_r,
               next_day_volume=nv, next_day_volume_t=tval(nv), next_day_absret=nr, next_day_absret_t=tval(nr))
    st = tval(same_v)
    if same_v is None:
        same = '같은 날 거래량과의 관계는 잴 수 없었어요(거래량 변화가 없음).'
    elif st is not None and abs(st) >= T_LINK:
        same = f'같은 날에는 관심과 거래량이 {"함께" if same_v > 0 else "반대로"} 움직였어요(상관 {same_v:+.2f}).'
    else:
        same = f'같은 날 거래량과의 관계도 뚜렷하지 않았어요(상관 {same_v:+.2f}).'
    if n_dates < MIN_DATES:
        out.update(verdict='held', line=f'{same} {lag_word}을 미리 알려 주는지는 거래일 {n_dates}일 기록뿐이라 아직 말할 수 없어요(최소 {MIN_DATES}일).')
    else:
        tv = tval(nv)
        ok = tv is not None and abs(tv) >= T_LINK
        out.update(verdict='link' if ok else 'none',
                   line=same + ' ' + (f'관심이 높았던 날 {lag_word} 거래량은 평소보다 {"많았어요" if nv > 0 else "적었어요"}(편상관 {nv:+.2f}, t {tv:+.1f}).' if ok
                                      else f'관심이 {lag_word} 거래량을 미리 알려 준다는 기록은 뚜렷하지 않았어요' + (f'(편상관 {nv:+.2f}).' if nv is not None else '.')))
    return out


def public_panel(res):
    return {k: v for k, v in res.items() if not k.startswith('_')}


# ---------------------------------------------------------------- 한 회사 체온계
def _sentiment_cover(root, man, t, start, last):
    try:
        rows, _ = read_rows(root, man, 'doc_daily_agg', t)
    except SnapshotError:
        return None
    rows = [r for r in rows if start <= str(r.get('d'))[:10] <= last]
    n_docs = sum(int(_f(r.get('n_docs')) or 0) for r in rows)
    n_sc = sum(int(_f(r.get('n_scored')) or 0) for r in rows)
    if not n_docs:
        return None
    avg = sum(_f(r.get('score_sum')) or 0 for r in rows) / n_sc if n_sc else None
    return {'n_docs': n_docs, 'n_scored': n_sc, 'cover': n_sc / n_docs, 'avg': avg, 'usable': n_sc / n_docs >= SENT_MIN_COVER,
            'days': len({str(r.get('d'))[:10] for r in rows})}


def thermo(company, cutoff='', snapshot='', days=20):
    P = panel(cutoff, snapshot)
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    if cos and company not in cos:
        raise SnapshotError('company_unknown', f'사본 기업 목록에 {company} 가 없습니다.')
    last = P['last_usable_date']
    name = cos.get(company, {}).get('name', company)
    posts = P['_posts'].get(company) or {}
    own = P['_own'].get(company) or {}
    inc = P['_inc'].get(company) or {}
    vol, vmeta = _volumes(root, man, company, last)
    vidx = {d: i for i, (d, _, _) in enumerate(vol)}
    yt_rows, ym = read_rows(root, man, 'news_title', company) if 'news_title' in man['tables'] else ([], None)
    yt = youtube_daily(yt_rows, P['_cal_ext'], last)
    known = sorted(d for d in set(posts) | set(yt) if d <= last)
    series = []
    for d in known[-days:]:
        i = vidx.get(d)
        av, ar = abnormal(vol, i) if i is not None else (None, None)
        mm = P['market_multiple'].get(d)
        om = own.get(d)
        pd_ = sorted(posts)
        row = {'date': d, 'posts': posts.get(d), 'own_multiple': om, 'market_multiple': mm,
               'base_days': min(BASE_MAX, pd_.index(d)) if d in posts else None,
               'adj_multiple': adjust(om, mm),
               'volume_multiple': math.exp(av) if av is not None else None, 'abs_return': ar,
               'youtube': yt.get(d), 'channels': {s: (inc.get(s) or {}).get(d) for s in ('naver_blog', 'naver_cafe', 'naver_news')}}
        row['flags'] = sorted({f for v in row['channels'].values() if v for f in v['flags']} | ({'market_odd'} if om and mm and row['adj_multiple'] is None else set()))
        series.append(row)
    latest = next((r for r in reversed(series) if r['posts'] is not None), None)
    sent = _sentiment_cover(root, man, company, known[0] if known else last, last)
    yt7 = [yt[d] for d in known[-5:] if d in yt]
    yts = {'comments': sum(x['comments'] for x in yt7), 'days': len(yt7),
           'top_share': max((x['top_share'] for x in yt7), default=None)} if yt7 else None
    rel = P['relation']
    if latest is None:
        head = f'{name}의 포털 검색 결과 수가 사본에 없거나, 하루 증가량을 만들 만큼 쌓이지 않았어요.'
        verdict = 'held'
    else:
        adj = latest['adj_multiple']
        lvl = ('평소보다 훨씬 많아요' if adj and adj >= 2 else '평소보다 많아요' if adj and adj >= 1.3 else
               '평소보다 적어요' if adj and adj <= 0.7 else '평소 수준이에요')
        head = (f"{latest['date']} {name} 새 블로그·카페 글 약 {latest['posts']:,.0f}건 — "
                f"이 회사 평소(이전 {latest['base_days']}일)의 {latest['own_multiple']:.1f}배" if latest['own_multiple'] else f"{latest['date']} {name} 새 블로그·카페 글 약 {latest['posts']:,.0f}건 (평소를 말하기엔 이전 기록이 부족해요)")
        if latest['market_multiple'] and adj is None and 'market_odd' in latest['flags']:
            head += f", 다만 그날 시장 전체 값이 평소의 {latest['market_multiple']:.1f}배로 비정상이라(포털 색인 몰림 등) 시장을 감안한 판단은 보류해요"
        if latest['market_multiple'] and adj:
            head += f", 그날 시장 전체가 평소의 {latest['market_multiple']:.1f}배여서 시장을 감안하면 {adj:.1f}배({lvl})"
        head += '.'
        verdict = 'ok'
    sources = {'mentions': {'table': 'core.mention_count', 'origin': '네이버 검색 API 결과 수(포털, 연구용)'},
               'price': _src(root, man, vmeta, 'core.price_daily', '금융위원회 주식시세 — Neon 공용 DB 경유')}
    if ym:
        sources['youtube'] = _src(root, man, ym, 'rag.document', '유튜브 댓글 날짜·링크(본문 없음)')
    try:
        sb = search_block(search_panel(cutoff, snapshot), company)
    except Exception as e:                      # 데이터랩 사본 문제는 체온계 전체를 막지 않는다
        sb = {'available': False, 'line': f'과거 검색량 사본을 쓰지 못했어요: {e}'}
    return {'company': company, 'name': name, 'cutoff': P['cutoff'], 'last_usable_date': last, 'verdict': verdict, 'head': head, 'search': sb,
            'latest': latest, 'series': series, 'youtube_recent': yts, 'sentiment': sent, 'relation': rel,
            'n_days': len([r for r in series if r['posts'] is not None]), 'snapshot': P['snapshot'], 'manifest_sha256': P['manifest_sha256'],
            'model_calls': 0, 'notice': NOTICE, 'source': sources,
            'notes': ['포털 검색 결과 수는 누적값이라, 장 마감(15:30)과 장 마감 사이에 새로 생긴 글 수로 바꿨어요.',
                      '수집이 약 8시간 간격이라 장 마감 시각의 값은 앞뒤 수집값으로 보간했고, 주말을 낀 날도 24시간 기준으로 환산했어요.',
                      f'줄어든 날(검색 색인 변동)과 다른 날의 {JUMP_X:.0f}배가 넘게 튄 날(수집 시작 효과)은 뺐어요.',
                      '「평소」는 그날 이전 기록(최근 40거래일까지, 최소 3일)의 중앙값이에요. 그 뒤의 값은 쓰지 않아요.',
                      '「시장 감안 배수」는 이 회사 배수를 같은 날 모든 회사 배수의 중앙값으로 나눈 값이에요. 시장 전체가 시끄러웠던 날이나 포털 색인이 몰아서 반영된 날의 착시를 줄여요.',
                      f'시장 전체 배수가 {MARKET_OK[0]:.2f}~{MARKET_OK[1]:.0f}배 밖인 날은 포털 색인이 몰아서 반영된 날일 수 있어 시장 감안 배수를 내지 않아요.',
                      '유튜브 댓글은 본문 없이 날짜와 영상 번호만 셌어요. 사람·채널을 지목하지 않아요.']}


def mention_line(M):
    """N11 요약용: T08 mentions(trade_date·total, 수집 시각 없음) → 하루 증가량 한 줄. 누적값 % 변화는 쓰지 않는다."""
    by = defaultdict(dict)
    for m in M:
        if m.get('source') not in POST:
            continue
        d = str(m.get('trade_date'))[:10]
        v = _f(m.get('total'))
        if v is not None:
            by[m['source']][d] = max(v, by[m['source']].get(d, v))
    daily = defaultdict(float)
    for s, ser in by.items():
        ser = sorted(ser.items())
        for (d0, a), (d1, b) in zip(ser, ser[1:]):
            if b >= a:
                daily[d1] += b - a
    if len(daily) < 2:
        return None
    ds = sorted(daily)
    vals = [daily[d] for d in ds]
    med = _median(vals[:-1])
    if med:
        vals_ok = [x for x in vals[:-1] if x <= JUMP_X * med]
        med = _median(vals_ok) or med
    last = ds[-1]
    mult = f' · 기간 중 하루 중앙값 {med:,.0f}건의 {daily[last] / med:.1f}배' if med else ''
    return {'name': '새 블로그·카페 글 (포털 검색 결과 수의 하루 증가)', 'claim': f'{last} {daily[last]:,.0f}건{mult} (기록 {len(ds)}일)',
            'kind': 'derived', 'formula': '누적 검색 결과 수 → 날짜별 마지막 값의 차이. 시장 전체 감안·품질 표시는 「사람들이 얼마나 몰렸나?」 카드에서'}


CARD = {'id': 'attention', 'title': '사람들이 얼마나 몰렸나?', 'sub': '새 블로그·카페 글과 영상 댓글을 하루 단위로 · 시장 전체 감안 배수 · 같은 날 거래량과 나란히 (인과 아님)',
        'group': 'market', 'kind': '관계', 'doors': ['ask', 'test'], 'next': ['events', 'price'], 'needs': ['price_fsc'], 'view': 'attention'}


# ---------------------------------------------------------------- v0.29 데이터랩 검색량 (과거 소급)
SPIKE = math.log(2.0)      # 시장 감안 검색량이 평소의 2배 이상
SPIKE_GAP = 10             # 같은 회사 급증 사이 최소 거래일
_SCACHE = {}


def search_panel(cutoff='', snapshot=''):
    """데이터랩 사본 → 회사별 거래일 검색량·ASVI·시장 감안 ASVI, 관계 기록(같은 날·다음·다다음 거래일), 급증 뒤 기록. 사본이 없으면 None."""
    from . import datalab as DL
    from . import reaction as RX
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    dman, data = DL.load()
    if not dman:
        return None
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], dman['_manifest_sha256'], last, cutoff[:10])
    if key in _SCACHE:
        return _SCACHE[key]
    known = (datetime.fromisoformat(cutoff).astimezone(KST).date() - timedelta(days=1)).isoformat()   # 데이터랩 하루 값은 그날이 끝난 뒤에야 나온다
    lim = min(known, last)
    cos = companies(root, man)
    cal, _ = _calendar(root, man, cos, last)
    att, A, held = {}, {}, {}
    for t, ser in data.items():
        c = cos.get(t, {})
        if c and c.get('market') not in (None, 'KR'):
            continue
        ser = {d: v for d, v in ser.items() if d <= lim}
        if not ser:
            continue
        if DL.zero_share(ser) > DL.ZERO_MAX:
            held[t] = f'검색이 적은 날(0)이 {DL.zero_share(ser):.0%}라 보류'
            continue
        att[t] = {d: v for d, v in DL.by_trading_day(ser, cal, lim).items() if d <= lim}   # 다 채워지지 않은 거래일 몫은 뺀다
        A[t] = DL.asvi(att[t])
    by_day = defaultdict(list)
    for t, m in A.items():
        for d, x in m.items():
            by_day[d].append(x)
    mkt = {d: _median(v) for d, v in by_day.items() if len(v) >= 20}
    adj = {t: {d: x - mkt[d] for d, x in m.items() if d in mkt} for t, m in A.items()}
    # 가격: 거래량·|수익률|, 보통 종목 동일 가중 비교 기준(자기 제외)
    vols, rets = {}, {}
    for t in adj:
        v, _ = _volumes(root, man, t, last)
        if len(v) < 30:
            continue
        vols[t] = v
        rets[t] = RX.returns([(d, c) for d, _, c in v])
    tot, cnt = defaultdict(float), defaultdict(int)
    for _, (_, r) in rets.items():
        for d, x in r.items():
            tot[d] += x
            cnt[d] += 1
    obs = {1: [], 2: []}
    spikes = []
    dis_days, dis_from = _disclosure_days(root, man, list(adj))
    for t, m in adj.items():
        if t not in vols:
            continue
        v = vols[t]
        ab = abnormal_all(v)
        idx = {d: i for i, (d, _, _) in enumerate(v)}
        for d, x in m.items():
            i = idx.get(d)
            if i is None:
                continue
            v0, r0 = ab[i]
            if v0 is None:
                continue
            for lag in (1, 2):
                if i + lag < len(v):
                    vl, rl = ab[i + lag]
                    if vl is not None:
                        obs[lag].append({'t': t, 'd': d, 'a': x, 'v0': v0, 'r0': r0, 'v1': vl, 'r1': rl})
        # 급증 사건: 시장 감안 ASVI ≥ ln2, 같은 회사 급증 사이 SPIKE_GAP 거래일
        dates, sret = rets[t]
        mret = {d: (tot[d] - sret[d]) / (cnt[d] - 1) for d in sret if cnt.get(d, 0) >= 20}
        lastk = -10 ** 9
        for d in sorted(m):
            if m[d] < SPIKE or d not in idx or idx[d] - lastk < SPIKE_GAP:
                continue
            lastk = idx[d]
            car = RX.event_car(dates, sret, mret, d, last)
            if car:
                known = dis_from is not None and d >= dis_from
                spikes.append(car | {'ticker': t, 'date': d, 'with_disclosure': (d in dis_days.get(t, set())) if known else None, 'asvi_adj': m[d]})
    rel = {'same_and_next': relation(obs[1], '다음 거래일'), 'strict': relation(obs[2], '다다음 거래일')}
    groups = {}
    for name, sel in (('no_disclosure', lambda e: e['with_disclosure'] is False), ('with_disclosure', lambda e: e['with_disclosure'] is True),
                      ('unknown_disclosure', lambda e: e['with_disclosure'] is None), ('all', lambda e: True)):
        evs = [e for e in spikes if sel(e)]
        s = {w: RX.summarize(evs, w) for w in RX.WINDOWS}
        groups[name] = {'stats': s, 'verdict_first': RX.verdict(s['first']), 'verdict_drift20': RX.verdict(s['drift20'])}
    res = {'snapshot': dman['_snapshot'], 'manifest_sha256': dman['_manifest_sha256'], 'mode': dman.get('mode'), 'range': [dman['start'], dman['end']],
           'known_until': lim, 'n_companies': len(adj), 'disclosure_from': dis_from, 'held': held, 'relation': rel, 'spikes': groups, 'n_spikes': len(spikes),
           '_att': att, '_asvi': A, '_adj': adj, '_mkt': mkt, '_spikes': spikes}
    _SCACHE.clear()
    _SCACHE[key] = res
    return res


def _disclosure_days(root, man, tickers):
    """회사별 주요(반복 아닌) 공시가 있던 날과, 공시 목록이 시작되는 날(이보다 앞선 급증은 공시 여부를 모른다)."""
    from .reaction import classify
    out, first = {}, None
    if 'disclosure' not in man['tables']:
        return out, None
    for t in tickers:
        try:
            rows, _ = read_rows(root, man, 'disclosure', t)
        except SnapshotError:
            continue
        keep = set()
        for r in rows:
            d = str(r.get('rcept_dt'))[:10]
            first = d if first is None or d < first else first
            c = classify(r.get('report_nm'))
            if not c['routine'] and c['key'] != 'other':
                keep.add(d)
        out[t] = keep
    return out, first


def public_search(sp):
    return None if sp is None else {k: v for k, v in sp.items() if not k.startswith('_')}


def search_block(sp, company, days=60):
    """한 회사 체온계에 붙일 검색량 부분."""
    if sp is None:
        return {'available': False, 'line': '과거 검색량(네이버 데이터랩)을 아직 받지 않았어요. PC에서 _tools\\datalab\\run-datalab.cmd 를 실행하면 과거 몇 년 치를 받아 와요(키 필요).'}
    if company in sp['held']:
        return {'available': False, 'line': sp['held'][company]}
    a, adj = sp['_asvi'].get(company) or {}, sp['_adj'].get(company) or {}
    ds = sorted(a)[-days:]
    series = [{'date': d, 'multiple': math.exp(a[d]), 'adj_multiple': math.exp(adj[d]) if d in adj else None} for d in ds]
    mine = [e for e in sp['_spikes'] if e['ticker'] == company]
    latest = series[-1] if series else None
    line = (f"검색량(데이터랩 「주가」 검색) {latest['date']}: 이 회사 평소(이전 40거래일)의 {latest['multiple']:.1f}배"
            + (f", 시장 감안 {latest['adj_multiple']:.1f}배" if latest['adj_multiple'] else '') + '.') if latest else '검색량 기록이 부족해요.'
    return {'available': True, 'line': line, 'series': series, 'range': sp['range'], 'known_until': sp['known_until'], 'snapshot': sp['snapshot'],
            'company_spikes': [{k: e.get(k) for k in ('date', 'with_disclosure', 'asvi_adj', 'first', 'drift5', 'drift20')} for e in mine[-10:]],
            'disclosure_from': sp.get('disclosure_from'),
            'relation': sp['relation'], 'spikes': sp['spikes'], 'n_spikes': sp['n_spikes'], 'n_companies': sp['n_companies']}
