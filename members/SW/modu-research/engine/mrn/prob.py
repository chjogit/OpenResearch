"""v0.38 T2-3 공용: 「시장 대비」 확률 — 과거 경로 되쓰기. 유상증자 발행가·전환가액 조정(리픽싱) 시나리오가 함께 쓴다.

왜 이렇게 만들었나 (J10, 사본 210개사 5년 시세로 먼저 검증한 결과 — NOTES.md 「T2-3 (다)」)
- 「주가가 x원 아래일 확률」을 그대로 내면 맞지 않는다: 한 해씩 빼고 맞춰 보면 20거래일 뒤 최대 10%p, 60거래일 뒤 최대 21%p 어긋났다(2022년 하락장·2025년 상승장). 시장 전체의 방향은 변동성으로 맞힐 수 없기 때문.
- 그래서 둘로 나눈다. ① 시장 전체가 얼마나 오르내릴지는 맞히지 않고 시나리오(가정)로 받는다. ② 확률은 이 회사가 시장과 다르게 움직이는 부분에만 붙인다.
  이렇게 하면 같은 검증(실제 계산 경로 그대로 · 시장 움직임은 실제 값을 넣음)에서 20거래일까지는 약 5%p, 120거래일까지는 약 10%p 안으로 맞는다(EVIDENCE).
- 그 오차에 맞춰 거칠게만 보인다(J11): 20거래일까지 10%p 단위, 120거래일까지 20%p 단위, 그 뒤는 확률을 보이지 않는다. 「35%」 같은 촘촘한 숫자는 근거가 없다.
- 정규분포를 가정하지 않는다(정규분포는 20거래일에서도 7%p 어긋남). 사본 회사들의 실제 과거 경로(시장 대비 하루 수익률 ÷ 그 직전 60거래일 변동성)를 그대로 다시 쓴다.

지키는 것: 시점 규율(기준 날짜 뒤의 경로는 쓰지 않음) · 난수 없음(같은 입력이면 같은 결과) · 방향 판단 없음(「추정」 배지).
"""
import math

from . import price_src as _PS   # v0.39.3 가격 출처(금융위 + KIS 보충, 연구용 스위치)

LB = 60                    # 변동성을 재는 직전 거래일 수
STEP = 5                   # 과거 경로를 뜨는 간격(거래일)
JUMP = math.log(1.31)      # 가격제한폭(±30%)을 넘는 하루 변동 = 액면분할·감자 등 → 그 구간은 쓰지 않음
MIN_NAMES = 100            # 시장 평균을 낼 최소 회사 수
N_PATHS = 3000             # 되쓰는 과거 경로 수(고정 간격으로 고름)
H_FINE, H_COARSE = 20, 120  # 20거래일까지는 10%p 단위, 120거래일까지는 20%p 단위, 그 뒤는 확률을 보이지 않음
EVIDENCE = {5: 6.4, 20: 5.2, 40: 8.5, 60: 9.5, 120: 7.7}   # 한 해씩 빼고 맞춰 본 최대 오차(%p, 2022~2026 다섯 해 가운데 가장 나쁜 해) — backtest() 로 다시 계산, tests/test_v038_prob.py 가 실제 사본으로 확인

_LIB = {}
_SER = {}


def daily(series):
    """series = {종목: [(날짜, 종가), …]} → (회사별 {날짜: 하루 로그수익률}, 시장 {날짜: 회사 평균})."""
    R, agg = {}, {}
    for t, s in series.items():
        rr = {}
        for i in range(1, len(s)):
            a, b = s[i - 1][1], s[i][1]
            if a and b and a > 0 and b > 0:
                x = math.log(b / a); rr[s[i][0]] = x
                if abs(x) <= JUMP:
                    agg.setdefault(s[i][0], []).append(x)
        R[t] = rr
    return R, {d: sum(v) / len(v) for d, v in agg.items() if len(v) >= MIN_NAMES}


def _excess(s, rr, mkt):
    """한 회사의 날짜 순서대로 (날짜, 하루 수익률, 시장 대비 수익률). 값이 없거나 시장 평균이 없는 날은 None."""
    if not s:
        return []
    out = [(s[0][0], None, None)]
    for i in range(1, len(s)):
        d = s[i][0]; r = rr.get(d)
        out.append((d, r, (r - mkt[d]) if r is not None and d in mkt else None))
    return out


def sigma(series, ticker, last, R=None, mkt=None):
    """기준 날짜(last)까지 직전 60거래일의 시장 대비 하루 수익률 표준편차. 못 구하면 None(자료 부족·분할 등으로 끊긴 구간)."""
    import statistics
    if R is None:
        R, mkt = daily(series)
    s = [x for x in series.get(ticker) or [] if x[0] <= last]
    if len(s) < LB + 1:
        return None
    e = _excess(s, R[ticker], mkt)[-LB:]
    if any(x[2] is None or abs(x[1]) > JUMP for x in e):
        return None
    sg = statistics.stdev(x[2] for x in e)
    return sg if sg > 0 else None


def windows(series, last, hmax, R=None, mkt=None):
    """기준 날짜까지 끝나는 과거 경로 전부: [(시작일, 종목, 표준화한 시장 대비 하루 수익률 hmax개)]. 종목·날짜 순(고정)."""
    import statistics
    if R is None:
        R, mkt = daily(series)
    out = []
    for t in sorted(series):
        s = [x for x in series[t] if x[0] <= last]
        e = _excess(s, R[t], mkt)
        for i in range(LB, len(e) - hmax, STEP):
            w = e[i - LB + 1:i + 1]; f = e[i + 1:i + 1 + hmax]
            if any(x[2] is None or abs(x[1]) > JUMP for x in w) or any(x[2] is None or abs(x[1]) > JUMP for x in f):
                continue
            sg = statistics.stdev(x[2] for x in w)
            if sg > 0:
                out.append((e[i][0], t, [x[2] / sg for x in f]))
    return out


def library(series, last, hmax, key=None):
    """되쓸 과거 경로 묶음(numpy 배열 n × hmax)과 그 출처. key(사본 해시 등)를 주면 기억해 둔다."""
    import numpy as np
    ck = (key, last, hmax)
    if key is not None and ck in _LIB:
        return _LIB[ck]
    W = windows(series, last, hmax)
    if len(W) < 500:
        lib = None
    else:
        idx = [round(k * (len(W) - 1) / (N_PATHS - 1)) for k in range(N_PATHS)] if len(W) > N_PATHS else list(range(len(W)))
        lib = {'u': np.array([W[i][2] for i in idx], dtype=float), 'n': len(idx), 'pool': len(W), 'from': min(w[0] for w in W), 'to': max(w[0] for w in W),
               'companies': len({w[1] for w in W}), 'hmax': hmax}
    if key is not None:
        _LIB.clear() if len(_LIB) > 6 else None
        _LIB[ck] = lib
    return lib


def paths(lib, sg, h, market_total=0.0):
    """이 회사의 h거래일 누적 로그수익률 경로(n × h). market_total = 그 기간 시장 전체의 누적 로그수익률(시나리오, 날마다 고르게 나눔)."""
    import numpy as np
    if lib is None or sg is None or h < 1 or h > lib['hmax']:
        return None
    return np.cumsum(sg * lib['u'][:, :h] + market_total / h, axis=1)


def share(values, test):
    """경로들 가운데 test 가 참인 비율(0~1)."""
    import numpy as np
    return float(np.mean(test(values)))


def shown(p, h):
    """화면에 보일 확률 글. 20거래일까지 10%p 단위, 120거래일까지 20%p 단위, 그 뒤는 보이지 않음(None)."""
    if p is None or h > H_COARSE:
        return None
    step = 10 if h <= H_FINE else 20
    v = int(round(p * 100 / step) * step)
    return f'{step // 2}% 미만' if v == 0 else f'{100 - step // 2}% 넘음' if v == 100 else f'약 {v}%'


def evidence(h):
    """이 기간의 확률이 과거에 얼마나 맞았는지 한 줄."""
    k = next((x for x in sorted(EVIDENCE) if h <= x), None)
    if k is None:
        return None
    return f"과거 검증: 사본 회사들의 지난 5년에서 한 해씩 빼고 맞춰 봤을 때 {k}거래일 뒤 기준 최대 {EVIDENCE[k]}%p 어긋남(시장 전체 움직임은 실제 값을 넣고 봄)"


def series_from_snapshot(snapshot=''):
    """엔진 사본의 금융위 시세 → {종목: [(날짜, 종가)]} 와 사본 해시."""
    from . import market as M
    root = M.resolve(snapshot); man = M.load_manifest(root); out = {}
    if _SER.get('key') == man['_manifest_sha256']:
        return _SER['series'], _SER['key']
    for t in sorted(M.companies(root, man)):
        try:
            rows, _ = M.read_rows(root, man, 'price_daily', t)
        except M.SnapshotError:
            continue
        s = sorted((str(r['trade_date'])[:10], float(r['close'])) for r in rows if _PS.ok(r.get('source')) and r.get('close') not in (None, ''))
        if s:
            out[t] = s
    _SER.update(key=man['_manifest_sha256'], series=out)
    return out, man['_manifest_sha256']


def base_price(pr):
    """기준주가 꼴의 값: min((최근 20거래일 평균 + 최근 5거래일 평균 + 마지막 날) ÷ 3, 마지막 날). pr = (n × h) 가격 경로."""
    last = pr[:, -1]
    return __import__('numpy').minimum((pr[:, -20:].mean(1) + pr[:, -5:].mean(1) + last) / 3, last)


def backtest(series, horizons=(5, 20, 40, 60, 120), years=None, every=4, kinds=('close', 'base'), hmax=None):
    """한 해씩 빼고 맞춰 보기: 그 해를 뺀 과거 경로로 그 해의 실제 결과가 예측 분포의 어디에 놓였는지(PIT)를 모아, 명목 분위와 실제 비율의 차이를 낸다.
    시장 움직임은 실제 값을 넣는다(시나리오가 맞았을 때 확률이 맞는지를 보는 검증). 반환 {(기간, 종류, 해): {'n', 'coverage', 'max_err'}}."""
    import numpy as np
    Q = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
    hmax = hmax or max(horizons)
    R, mkt = daily(series)
    W = windows(series, '9999-12-31', hmax, R, mkt)
    U = np.array([w[2] for w in W]); Y = np.array([w[0][:4] for w in W])
    pit = {}
    for y in (years or sorted(set(Y.tolist()))):
        pool = U[Y != y]
        lib = pool[np.round(np.linspace(0, len(pool) - 1, N_PATHS)).astype(int)]
        for t in sorted(series):
            e = _excess(series[t], R[t], mkt)
            for i in range(LB, len(e) - hmax, STEP * every):
                if e[i][0][:4] != y:
                    continue
                w = e[i - LB + 1:i + 1]; f = e[i + 1:i + 1 + hmax]
                if any(x[2] is None or abs(x[1]) > JUMP for x in w) or any(x[2] is None or abs(x[1]) > JUMP for x in f):
                    continue
                sg = float(np.std([x[2] for x in w], ddof=1))
                if sg <= 0:
                    continue
                real = np.cumsum([x[1] for x in f]); mk = np.cumsum([mkt[x[0]] for x in f])
                for h in horizons:
                    sim = np.cumsum(sg * lib[:, :h] + mk[h - 1] / h, axis=1)
                    if 'close' in kinds:
                        pit.setdefault((h, 'close', y), []).append(float(np.mean(sim[:, -1] <= real[h - 1])))
                    if 'base' in kinds and h >= 20:
                        pit.setdefault((h, 'base', y), []).append(float(np.mean(base_price(np.exp(sim)) <= base_price(np.exp(real[None, :h]))[0])))
    out = {}
    for k, v in pit.items():
        a = np.array(v); cov = [float(np.mean(a <= q)) for q in Q]
        out[k] = {'n': len(v), 'coverage': [round(c * 100, 1) for c in cov], 'max_err': round(max(abs(c - q) for c, q in zip(cov, Q)) * 100, 1)}
    return out
