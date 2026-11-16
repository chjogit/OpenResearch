"""v0.39.3 가격 행 출처 고르기 (PM 결정 2026-11-15, 연구용).
- 금융위(fsc) 시세는 늘 씀.
- 한국투자증권 일별 시세(kis): 가격 사본에 KIS로 보충한 날이 있으면 씀(연구용 · 재배포 계약 전). MODU_PRICE_KIS=0 이면 쓰지 않음.
- 같은 날짜에 둘 다 있으면 금융위 값을 씀. 그 밖의 출처(yfinance 등)는 쓰지 않음(전과 같음)."""
import os

SOURCES = ('fsc', 'kis')


def ok(src):
    return src == 'fsc' or (src == 'kis' and (os.environ.get('MODU_PRICE_KIS') or '1') != '0')


def pick(rows, datecol='trade_date'):
    """출처가 맞는 행만, 날짜당 한 줄(금융위 우선), 날짜순."""
    best = {}
    for r in rows:
        if not ok(r.get('source')):
            continue
        d = str(r[datecol])[:10]
        if d not in best or (best[d].get('source') != 'fsc' and r.get('source') == 'fsc'):
            best[d] = r
    return [best[d] for d in sorted(best)]


def kis_count(rows):
    return sum(1 for r in rows if r.get('source') == 'kis')
