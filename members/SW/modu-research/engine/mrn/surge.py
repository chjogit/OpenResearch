"""v0.38 T3-1 관심회사 주가 큰 움직임 감지 → 공시 목록 바로 확인. AI 모델 호출 0회.

- 시세: 한국투자증권 Open API 「주식 현재가」(PM 결정 2026-11-13: KIS 현재가). 전일 종가 대비 등락률(prdy_ctrt)과
  같은 시장 지수(코스피 0001 · 코스닥 1001)의 등락률. **감지에만 쓰고 답 카드 숫자·근거 확인서에는 넣지 않는다**(KIS 목록 X2).
- 기준(J29): |회사 등락률 − 같은 시장 지수 등락률| ≥ MODU_SURGE_PCT(기본 7%p). 지수를 못 받으면 회사 등락률만으로 보고 그 사실을 적는다.
  오름·내림 모두(방향 판단 없음, 공시 확인이 목적). 사본 210개사 3년: 등락 ±7% 이상은 회사당 한 해 약 11번.
- 감지되면: 그날(거래일) 그 회사 줄을 남기고, 공시 목록 확인(autocheck.check_once, trigger='surge')을 바로 돌린다. 바로 확인은 하루 MODU_SURGE_DAILY(기본 30)번까지.
- 언제: 장중(거래일 09:00~15:30)에는 MODU_SURGE_MIN(기본 10)분마다, 장 밖에서는 거래일마다 한 번(전날·그날 종가 기준).
- 키: KIS_APP_KEY·KIS_APP_SECRET 환경 변수에서만. 토큰은 PC 임시 폴더에만 잠깐(프로젝트·묶음 밖). 키·토큰은 화면·로그·오류 문장에 남기지 않는다.
- KIS 호출 수는 DART와 따로 센다(kis_usage, KIS 목록 X10). 주문 코드 없음(조회만).
"""
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from . import tradecal as C

KST = timezone(timedelta(hours=9))
SERVER = 'https://openapi.koreainvestment.com:9443'          # 실전 서버(조회만)
INDEX = {'KOSPI': '0001', 'KOSDAQ': '1001'}
SPACING = 0.08                                               # 실전 서버 초당 호출 한도 아래로
DDL = """
CREATE TABLE IF NOT EXISTS surge_events(
  day TEXT NOT NULL, ticker TEXT NOT NULL, name TEXT, pct REAL NOT NULL, mkt TEXT, mkt_pct REAL, excess REAL, price INTEGER,
  seen_at TEXT NOT NULL, run_id INTEGER, run_status TEXT, note TEXT, PRIMARY KEY(day, ticker));
CREATE TABLE IF NOT EXISTS kis_usage(day TEXT PRIMARY KEY, calls INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS surge_polls(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, day TEXT NOT NULL, session TEXT NOT NULL,
  cal TEXT NOT NULL, tickers INTEGER NOT NULL DEFAULT 0, calls INTEGER NOT NULL DEFAULT 0, found INTEGER NOT NULL DEFAULT 0, checked INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL, message TEXT);
"""


class KisError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code


def config(env=None):
    env = os.environ if env is None else env

    def num(k, d, lo, hi, f=float):
        try:
            return min(hi, max(lo, f(env.get(k) or d)))
        except (TypeError, ValueError):
            return d
    return {'enabled': (env.get('MODU_SURGE') or '1') != '0', 'pct': num('MODU_SURGE_PCT', 7.0, 2.0, 30.0),
            'minutes': int(num('MODU_SURGE_MIN', 10, 5, 120, int)), 'daily': int(num('MODU_SURGE_DAILY', 30, 0, 30, int)),
            'key': (env.get('KIS_APP_KEY') or '').strip(), 'secret': (env.get('KIS_APP_SECRET') or '').strip()}


def ensure(store):
    with store.lock, store.connect() as c:
        c.executescript(DDL)


def now_kst(clock=None):
    return (clock() if clock else datetime.now(timezone.utc)).astimezone(KST)


def session(at):
    """(거래일, 'open'|'closed') — 장 시작 전에는 직전 거래일의 종가 기준, 장중에는 오늘."""
    d = at.date().isoformat()
    hm = at.hour * 100 + at.minute
    if C.is_open(d) and hm >= 900:
        return d, ('open' if hm < 1530 else 'closed')
    return C.shift(d, -1), 'closed'


def _http(method, url, headers=None, body=None, timeout=15):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header('content-type', 'application/json; charset=utf-8')
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode('utf-8', 'replace'))
        except Exception:
            return e.code, {}
    except Exception as e:
        raise KisError('network', f'KIS 연결 실패({type(e).__name__})')


class Kis:
    """조회만. http(method, url, headers, body) → (status, json) 를 바꿔 끼워 시험한다."""
    def __init__(self, key, secret, http=None, store=None, clock=None, sleep=time.sleep, token_path=None):
        self.key, self.secret, self.http, self.store, self.clock, self.sleep = key, secret, http or _http, store, clock, sleep
        self.token_path = token_path or os.path.join(tempfile.gettempdir(), 'modu_kis_engine_token.json')   # 프로젝트 밖 임시 폴더
        self.tok = None; self.calls = 0

    def _count(self):
        self.calls += 1
        if self.store is not None:
            day = now_kst(self.clock).date().isoformat()
            with self.store.lock, self.store.connect() as c:
                c.execute('INSERT INTO kis_usage(day,calls) VALUES(?,1) ON CONFLICT(day) DO UPDATE SET calls=calls+1', (day,))

    def token(self):
        if self.tok:
            return self.tok
        path = self.token_path
        try:
            with open(path, encoding='utf-8') as f:
                s = json.load(f)
            if s.get('key_tail') == self.key[-4:] and s.get('until', 0) > time.time() + 600:
                self.tok = s['token']; return self.tok
        except Exception:
            pass
        self._count()
        st, js = self.http('POST', SERVER + '/oauth2/tokenP', None, {'grant_type': 'client_credentials', 'appkey': self.key, 'appsecret': self.secret})
        tok = (js or {}).get('access_token')
        if not tok:
            raise KisError('kis_token', f"KIS 접근 토큰을 받지 못했어요(HTTP {st}). 토큰은 1분에 한 번만 받을 수 있어요.")
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({'token': tok, 'key_tail': self.key[-4:], 'until': time.time() + int(js.get('expires_in', 80000))}, f)
        except Exception:
            pass
        self.tok = tok
        return tok

    def get(self, path, tr_id, params):
        tok = self.token()
        self.sleep(SPACING); self._count()
        st, js = self.http('GET', SERVER + path + '?' + urllib.parse.urlencode(params),
                           {'authorization': 'Bearer ' + tok, 'appkey': self.key, 'appsecret': self.secret, 'tr_id': tr_id, 'custtype': 'P'}, None)
        if st != 200 or str((js or {}).get('rt_cd')) != '0':
            raise KisError('kis_' + str((js or {}).get('msg_cd') or st), f"KIS 조회 실패(HTTP {st} {(js or {}).get('msg_cd', '')})")
        return js.get('output') or {}

    def price(self, ticker):
        o = self.get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100', {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': ticker})
        return {'price': _int(o.get('stck_prpr')), 'pct': _f(o.get('prdy_ctrt')), 'market': (o.get('rprs_mrkt_kor_name') or '').upper()}

    def index(self, code):
        o = self.get('/uapi/domestic-stock/v1/quotations/inquire-index-price', 'FHPUP02100000', {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': code})
        return _f(o.get('bstp_nmix_prdy_ctrt'))


def _f(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


def _int(x):
    v = _f(x)
    return int(v) if v is not None else None


def _mkt(name):
    return 'KOSDAQ' if 'KOSDAQ' in (name or '') else 'KOSPI'


def checks_today(store, cal):
    """오늘(한국 날짜) 감지 때문에 공시 목록을 바로 확인한 횟수."""
    with store.lock, store.connect() as c:
        return c.execute('SELECT COUNT(*) FROM surge_polls WHERE cal=? AND checked=1', (cal,)).fetchone()[0]


def poll(store, tickers, env=None, kis=None, clock=None, check=None, names=None):
    """한 번 훑기. 반환: {status, day, session, found[...], calls, message}. check(store, trigger) = 공시 목록 바로 확인."""
    from . import autocheck as AC
    ensure(store); cfg = config(env); at = now_kst(clock); day, ses = session(at); cal = at.date().isoformat()
    seen = at.astimezone(timezone.utc).isoformat()
    tickers = [t for t in tickers if len(t) == 6 and t.isdigit()]                # 국내 종목만(해외는 KIS 국내 현재가로 볼 수 없음)

    def done(status, message, found=(), calls=0, checked=0):
        with store.lock, store.connect() as c:
            c.execute('INSERT INTO surge_polls(at,day,session,cal,tickers,calls,found,checked,status,message) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (seen, day, ses, cal, len(tickers), calls, len(found), checked, status, message))
        return {'status': status, 'day': day, 'session': ses, 'found': list(found), 'calls': calls, 'checked': bool(checked), 'message': message}
    if not cfg['enabled']:
        return done('off', '주가 움직임 감지가 꺼져 있어요(MODU_SURGE=0).')
    if not (cfg['key'] and cfg['secret']):
        return done('no_key', 'KIS 키가 없어 주가 움직임 감지를 하지 않았어요(local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).')
    if not tickers:
        return done('empty', '관심회사가 없어요.')
    kis = kis or Kis(cfg['key'], cfg['secret'], store=store, clock=clock)
    idx, found, notes = {}, [], []
    try:
        for t in tickers:
            try:
                p = kis.price(t)
            except KisError as e:
                if e.code in ('network', 'kis_token'):
                    raise
                notes.append(f'{t}: {e}'); continue
            if p['pct'] is None:
                notes.append(f'{t}: 등락률을 읽지 못함'); continue
            m = _mkt(p['market'])
            if m not in idx:
                try:
                    idx[m] = kis.index(INDEX[m])
                except KisError:
                    idx[m] = None
            mp = idx[m]
            ex = round(p['pct'] - mp, 2) if mp is not None else None
            hit = abs(ex if ex is not None else p['pct']) >= cfg['pct']
            if not hit:
                continue
            note = None if mp is not None else f'{m} 지수 등락률을 받지 못해 회사 등락률만으로 봄'
            with store.lock, store.connect() as c:
                new = c.execute('INSERT OR IGNORE INTO surge_events(day,ticker,name,pct,mkt,mkt_pct,excess,price,seen_at,note) VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (day, t, (names or {}).get(t), p['pct'], m, mp, ex, p['price'], seen, note)).rowcount
                if not new:                                               # 같은 거래일에 이미 잡은 회사 — 더 크게 움직였으면 값만 갱신
                    c.execute('UPDATE surge_events SET pct=?, mkt_pct=?, excess=?, price=? WHERE day=? AND ticker=? AND ABS(COALESCE(excess,pct)) < ?',
                              (p['pct'], mp, ex, p['price'], day, t, abs(ex if ex is not None else p['pct'])))
            if new:
                found.append(t)
    except KisError as e:
        return done('error', f'{e} — 다음 훑기 때 다시 해요.', found, kis.calls)
    ix = ' · '.join(f"{'코스피' if m == 'KOSPI' else '코스닥'} {'못 받음' if v is None else f'{v:+.2f}%'}" for m, v in idx.items())   # 기준으로 쓴 지수(보이게)
    msg = f"관심회사 {len(tickers)}곳 훑음 · 크게 움직인 회사 {len(found)}곳" + (f" ({', '.join(found)})" if found else '') + (f' · 기준 지수 {ix}' if ix else '') + (' · ' + ' · '.join(notes) if notes else '')
    checked = 0
    if found:
        if checks_today(store, cal) >= cfg['daily']:
            msg += f" · 오늘 바로 확인 {cfg['daily']}번을 다 써서 다음 정기 확인 때 봄"
        else:
            r = (check or AC.check_once)(store, 'surge', env=env)
            rid, rst = (r or {}).get('id'), (r or {}).get('status')
            checked = 1
            with store.lock, store.connect() as c:
                c.executemany('UPDATE surge_events SET run_id=?, run_status=? WHERE day=? AND ticker=?', [(rid, rst, day, t) for t in found])
            msg += f" · 공시 목록 바로 확인: {AC.STATUS_LABEL.get(rst, rst)}" if rst != 'busy' else ' · 다른 확인이 돌고 있어 그 결과로 봄'
    return done('ok', msg, found, kis.calls, checked)


def board(store, tickers, days=14, clock=None):
    """화면용: 최근 days일 크게 움직인 관심회사 + 같은 날 공시 수(접수일 기준). 원인은 판단하지 않는다."""
    ensure(store)
    if not tickers:
        return []
    since = (now_kst(clock).date() - timedelta(days=days)).isoformat(); q = ','.join('?' * len(tickers))
    with store.lock, store.connect() as c:
        rows = [dict(r) for r in c.execute(f'SELECT * FROM surge_events WHERE ticker IN ({q}) AND day >= ? ORDER BY day DESC, ABS(COALESCE(excess,pct)) DESC', (*tickers, since))]
        for r in rows:
            fs = c.execute('SELECT rcept_no, report_nm FROM filing_seen WHERE ticker=? AND rcept_dt=? ORDER BY rcept_no', (r['ticker'], r['day'])).fetchall()
            r['filings'] = [{'rcept_no': f['rcept_no'], 'report_nm': f['report_nm'], 'url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={f['rcept_no']}"} for f in fs]
    return rows


def status(store, tickers, env=None, clock=None):
    ensure(store); cfg = config(env); at = now_kst(clock); day, ses = session(at)
    with store.lock, store.connect() as c:
        last = c.execute('SELECT * FROM surge_polls ORDER BY id DESC LIMIT 1').fetchone()
        kc = c.execute('SELECT calls FROM kis_usage WHERE day=?', (at.date().isoformat(),)).fetchone()
    th = getattr(WATCH.get('w'), 'thread', None)
    return {'enabled': cfg['enabled'], 'has_key': bool(cfg['key'] and cfg['secret']), 'running': bool(th and th.is_alive()),
            'pct': cfg['pct'], 'minutes': cfg['minutes'], 'day': day, 'session': ses,
            'checks_today': checks_today(store, at.date().isoformat()), 'daily_cap': cfg['daily'], 'kis_calls_today': kc[0] if kc else 0,
            'last_poll': dict(last) if last else None, 'events': board(store, tickers, clock=clock),
            'note': f"관심회사 주가가 같은 시장 지수보다 ±{cfg['pct']:g}%p 넘게 움직이면 그 회사 공시 목록을 바로 확인해요(하루 {cfg['daily']}번까지). "
                    '시세는 한국투자증권 현재가로 감지에만 쓰고 답 카드 숫자에는 넣지 않아요. 움직인 이유는 판단하지 않아요.'}


class Watcher:
    """앱이 켜져 있는 동안: 장중 minutes분마다, 장 밖에서는 거래일마다 한 번 훑는다. 30초마다 깨어나 벽시계로 본다."""
    def __init__(self, store, env=None, clock=None, tick=30, poll_fn=poll, delay=60):
        self.store, self.env, self.clock, self.tick, self.poll_fn, self.delay = store, env, clock, tick, poll_fn, delay
        self.stop_event = threading.Event(); self.thread = None; self.last = None; self.last_closed_day = None

    def due(self, now):
        day, ses = session(now_kst(lambda: now))
        gap_ok = self.last is None or (now - self.last).total_seconds() >= config(self.env)['minutes'] * 60   # 실패해도 minutes분 뒤에 다시(토큰 남발 방지)
        return gap_ok if ses == 'open' else (self.last_closed_day != day and gap_ok)

    def step(self, now=None):
        from . import autocheck as AC
        now = now or (self.clock() if self.clock else datetime.now(timezone.utc))
        if not self.due(now):
            return None
        day, ses = session(now_kst(lambda: now))
        try:
            r = self.poll_fn(self.store, AC.watched(self.store), env=self.env, names=_names())
        except Exception as e:                                   # 훑기 하나가 실패해도 일정은 멈추지 않는다
            r = {'status': 'error', 'message': type(e).__name__}
        self.last = now
        if ses == 'closed' and (r or {}).get('status') in ('ok', 'no_key', 'off', 'empty'):
            self.last_closed_day = day
        return r

    def start(self):
        if not config(self.env)['enabled'] or (self.thread and self.thread.is_alive()):
            return False
        self.thread = threading.Thread(target=self._loop, name='surge', daemon=True); self.thread.start()
        return True

    def _loop(self):
        if self.stop_event.wait(self.delay):
            return
        while not self.stop_event.is_set():
            self.step()
            self.stop_event.wait(self.tick)


def _names():
    try:
        from .dartdocs import _companies
        return {c['ticker']: c['name'] for c in _companies()}
    except Exception:
        return {}


WATCH = {'w': None}


def start(store, env=None):
    """python -m mrn 에서만(autocheck.start_scheduler 가 부른다)."""
    ensure(store)
    w = Watcher(store, env); WATCH['w'] = w
    return w.start()
