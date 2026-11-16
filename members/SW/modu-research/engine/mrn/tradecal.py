"""v0.38 T2-4c 거래일 달력. 지난 날은 시세 자료의 실제 거래일을, 앞으로의 날은 주말 + 한국거래소 휴장일 표(krx_holidays.json)를 쓴다.
휴장일 표가 없는 해는 평일을 거래일로 보고, 그렇게 센 날짜가 있었다는 것을 알린다(covered)."""
import json
from datetime import date, timedelta
from pathlib import Path

_P = Path(__file__).with_name('krx_holidays.json')
_CACHE = {}


def table():
    if 'h' not in _CACHE:
        d = json.loads(_P.read_text(encoding='utf-8'))
        _CACHE['h'] = {day: why for y in d['years'].values() for day, why in y.items()}
        _CACHE['years'] = {int(y) for y in d['years']}
        _CACHE['meta'] = {k: d.get(k) for k in ('source', 'checked_at')}
    return _CACHE['h'], _CACHE['years'], _CACHE['meta']


def covered(day):
    """이 날짜의 해에 휴장일 표가 있는가."""
    return int(day[:4]) in table()[1]


def is_open(day):
    """주말·휴장일이 아니면 거래일. 표가 없는 해는 평일이면 거래일로 본다."""
    d = date.fromisoformat(day)
    return d.weekday() < 5 and day not in table()[0]


def holiday(day):
    return table()[0].get(day)


def shift(day, k):
    """day 에서 거래일로 k번째(k<0 이면 앞, k>0 이면 뒤). day 자신은 세지 않는다."""
    d = date.fromisoformat(day); step = 1 if k > 0 else -1; n = 0
    while n < abs(k):
        d += timedelta(days=step)
        n += is_open(d.isoformat())
    return d.isoformat()


def count(a, b):
    """a~b(양끝 포함)의 거래일 수."""
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b); n = 0
    while d0 <= d1:
        n += is_open(d0.isoformat()); d0 += timedelta(days=1)
    return n


def note(a, b):
    """a~b 사이에 휴장일 표가 없는 해가 끼어 있으면 알리는 한 줄, 아니면 빈 글."""
    ys = [y for y in range(int(a[:4]), int(b[:4]) + 1) if y not in table()[1]]
    return f" {'·'.join(map(str, ys))}년은 휴장일 표가 없어 평일을 거래일로 셈." if ys else ''
