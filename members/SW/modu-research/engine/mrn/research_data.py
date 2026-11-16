"""v0.39.2 연구용 데이터 (PM 결정 2026-11-15): 계약 전에 「구현이 되는지」 확인하려고 만든 두 가지. 둘 다 스위치로 켜고 끈다.

1) KIS 현재가 보여 주기  GET /api/quote/{ticker}
   - MODU_SHOW_QUOTES=1 일 때만. 꺼져 있으면 {"enabled": false} 만 돌려준다(KIS를 부르지 않음).
   - 한국투자증권 현재가·전일 대비 등락률. 같은 회사는 30초 동안 다시 부르지 않음(캐시). KIS 사용량은 기존 kis_usage에 함께 셈(X10).
   - 「연구용 · 재배포 계약 전」 표시. 답 카드·근거 확인서에는 넣지 않는다(X2 그대로) — 화면의 회사 이름 옆에만.
2) 컨센서스(연구용)  GET /api/consensus/{ticker}
   - ① 증권사 보고서 집계: 승인된 증권사 보고서의 연도·항목별 최신 집계(중앙값·범위·보고서 수) — 이미 있던 N16 계산(forecasts.trend)을 그대로 씀
   - ② 정식 데이터 파일: _sources/consensus/*.csv (MODU_NODES_CONSENSUS_DIR) — 계약 뒤 받은 파일을 이 형식으로 넣으면 바로 나옴
       provider,ticker,fiscal_year,metric,value_mn,n_estimates,as_of
       metric: revenue(매출액)·operatingProfit(영업이익)·netIncome(순이익), value_mn: 백만원 정수, as_of: YYYY-MM-DD
   - MODU_SHOW_CONSENSUS=0 이면 끔(기본 켬 — 이미 화면에 있던 보고서 집계를 모아 보여 주는 것뿐).
   - 기준 날짜(cutoff)가 있으면 그날까지의 보고서·파일만.
판단(사라·팔아라·목표주가) 없음. 「컨센서스」라는 이름은 연구용 화면 이름이며, ①은 공식 시장 예상치가 아니라는 고지를 함께 보낸다."""
import csv
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
METRIC_LABEL = {'revenue': '매출액', 'operatingProfit': '영업이익', 'netIncome': '순이익'}
COLS = ['provider', 'ticker', 'fiscal_year', 'metric', 'value_mn', 'n_estimates', 'as_of']
QUOTE_LABEL = '한국투자증권 현재가 · 연구용(재배포 계약 전)'
QUOTE_NOTE = '연구용 시연에서만 보여 줘요. 다른 사람에게 시세를 보여 주는 것은 정식 계약 뒤에 열어요. 답 카드·근거 확인서에는 넣지 않아요.'
CONS_NOTE = ('연구용 화면이에요. ① 증권사 보고서 집계는 앱이 승인된 보고서를 모아 계산한 것으로 공식 시장 예상치(컨센서스)가 아니에요. '
             '② 정식 데이터는 계약 뒤 받은 파일을 넣으면 나와요. 사거나 팔라는 판단이 아니에요.')
CACHE_SEC = 30
_cache, _lock = {}, threading.Lock()


def flags(env=None):
    env = os.environ if env is None else env
    return {'quotes': (env.get('MODU_SHOW_QUOTES') or '0') == '1', 'consensus': (env.get('MODU_SHOW_CONSENSUS') or '1') != '0'}


def consensus_dir(env=None):
    env = os.environ if env is None else env
    return Path(env.get('MODU_NODES_CONSENSUS_DIR') or ROOT.parent / '_sources' / 'consensus')


# ---------- 1) KIS 현재가 ----------
def quote(ticker, store=None, env=None, kis=None, clock=time.time):
    f = flags(env)
    if not f['quotes']:
        return {'enabled': False, 'note': '시세 보여 주기가 꺼져 있어요(MODU_SHOW_QUOTES=1 로 켬).'}
    if not re.fullmatch(r'\d{6}', ticker or ''):
        return {'enabled': True, 'available': False, 'note': '국내 6자리 종목코드만 시세를 보여 줘요.'}
    now = clock()
    with _lock:
        hit = _cache.get(ticker)
        if hit and now - hit[0] < CACHE_SEC:
            return {**hit[1], 'cached': True}
    from . import surge
    if kis is None:
        cfg = surge.config(env)
        if not (cfg['key'] and cfg['secret']):
            return {'enabled': True, 'available': False, 'note': 'KIS 키가 없어요(엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'}
        kis = surge.Kis(cfg['key'], cfg['secret'], store=store)
    try:
        p = kis.price(ticker)
    except Exception as e:   # 키·토큰·한도 오류는 문장만(키 값은 쓰지 않음)
        return {'enabled': True, 'available': False, 'note': f'KIS 조회 실패 — {str(e)[:80]}'}
    if not p.get('price'):
        return {'enabled': True, 'available': False, 'note': 'KIS가 현재가를 주지 않았어요(장 시작 전·거래 정지 등).'}
    out = {'enabled': True, 'available': True, 'ticker': ticker, 'price': p['price'], 'pct': p.get('pct'),
           'as_of': datetime.fromtimestamp(now, KST).isoformat(timespec='seconds'), 'label': QUOTE_LABEL, 'note': QUOTE_NOTE, 'cached': False}
    with _lock:
        _cache[ticker] = (now, out)
    return out


# ---------- 2) 컨센서스(연구용) ----------
def read_files(folder, ticker=None, until=None):
    """정식 데이터 파일(csv) 읽기. 형식이 틀린 줄은 버리고 이유를 남긴다. → (rows, problems, files)"""
    rows, problems, files = [], [], []
    folder = Path(folder)
    if not folder.is_dir():
        return rows, problems, files
    for p in sorted(folder.glob('*.csv')):
        files.append(p.name)
        try:
            with open(p, encoding='utf-8-sig', newline='') as fh:
                rd = csv.DictReader(fh)
                miss = [c for c in COLS if c not in (rd.fieldnames or [])]
                if miss:
                    problems.append(f'{p.name}: 빠진 칸 {", ".join(miss)}'); continue
                for i, r in enumerate(rd, start=2):
                    try:
                        t = r['ticker'].strip().zfill(6)
                        fy = int(r['fiscal_year']); m = r['metric'].strip()
                        v = Decimal(r['value_mn'].strip().replace(',', ''))
                        n = int(r['n_estimates']) if (r.get('n_estimates') or '').strip() else None
                        d = datetime.strptime(r['as_of'].strip(), '%Y-%m-%d').date().isoformat()
                        if m not in METRIC_LABEL or not (2000 <= fy <= 2100) or v != v.to_integral_value():
                            raise ValueError
                    except (ValueError, InvalidOperation, KeyError, AttributeError):
                        problems.append(f'{p.name} {i}번째 줄: 형식이 맞지 않아 뺐어요'); continue
                    if ticker and t != ticker:
                        continue
                    if until and d > str(until)[:10]:
                        continue
                    rows.append({'provider': r['provider'].strip(), 'ticker': t, 'fiscal_year': fy, 'metric': m, 'metric_label': METRIC_LABEL[m],
                                 'value_mn': str(int(v)), 'n_estimates': n, 'as_of': d, 'file': p.name})
        except OSError:
            problems.append(f'{p.name}: 읽지 못했어요')
    latest = {}
    for r in rows:   # 같은 제공처·연도·항목은 가장 최근 as_of 한 줄
        k = (r['provider'], r['fiscal_year'], r['metric'])
        if k not in latest or r['as_of'] > latest[k]['as_of']:
            latest[k] = r
    return sorted(latest.values(), key=lambda r: (r['fiscal_year'], r['metric'], r['provider'])), problems, files


def broker_summary(forecasts, until=None):
    """승인된 증권사 전망 → 연도·항목별 최신 집계(forecasts.trend 의 latest)."""
    from . import forecasts as FC
    out = []
    keys = sorted({(int(f['fiscal_year']), f['metric']) for f in forecasts})
    for fy, m in keys:
        tr = FC.trend(forecasts, m, fy, until)
        if not tr:
            continue
        L = tr['latest']
        out.append({'fiscal_year': fy, 'metric': m, 'metric_label': FC.METRICS.get(m, m), 'date': L['date'], 'n': L['n'],
                    'median_mn': L['median'], 'min_mn': L['min'], 'max_mn': L['max'], 'brokers': L['brokers'], 'thin': L['thin'],
                    'median_move_pct': tr['median_move_pct']})
    return out


def consensus(ticker, forecasts, env=None, until=None):
    f = flags(env)
    if not f['consensus']:
        return {'enabled': False, 'note': '컨센서스(연구용) 화면이 꺼져 있어요(MODU_SHOW_CONSENSUS=0).'}
    rows, problems, files = read_files(consensus_dir(env), ticker, until)
    return {'enabled': True, 'ticker': ticker, 'cutoff': until or '', 'broker': broker_summary(forecasts, until),
            'provider': rows, 'provider_files': files, 'provider_problems': problems[:20],
            'provider_format': ','.join(COLS), 'note': CONS_NOTE, 'model_calls': 0}
