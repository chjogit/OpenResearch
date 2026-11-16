"""v0.20 기대 부채 체온계(사본 전체) + 검증 관문 — KIRI 시간자본론 지표의 PC 도구.

실행:  .venv\\Scripts\\python.exe -X utf8 -m mrn.edi_market            (최신 사본)
       .venv\\Scripts\\python.exe -X utf8 -m mrn.edi_market --snapshot 20261107T005213+0900
결과:  data/edi_market/<사본>/  market.json · validation.json · companies.csv · report.md

앱 화면(답 카드)과 같은 계산(mrn.edi)·같은 사본 해시 대조(mrn.market)를 쓴다. 판단·매매 신호가 아니라 기록이며,
검증 관문을 통과하지 못하면 국면에 의미를 붙이지 않는다(report.md 맨 위에 결과를 적는다).
"""
import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path

from . import edi as E
from . import price_src as _PS   # v0.39.3 가격 출처(금융위 + KIS 보충, 연구용 스위치)
from .market import resolve, load_manifest, read_rows, companies, ROOT

FIN_SECTORS = {'기타금융', '보험', '증권', '은행'}
DECISIVE = ('price_ahead', 'earn_led', 'mixed', 'price_led', 'both_down', 'deeper', 'in_step', 'small')
FWD = 126          # 앞으로 약 6개월(거래일)
MOM = 126          # 지난 약 6개월 수익률 (모멘텀 통제)
RECENT_DAYS = 120  # 체온계: 이 날짜에서 120일 안에 끝난 구간만 「최근 국면」으로 센다
PASS_SHARE = 2 / 3


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load(snapshot='', r=0.09, g_lt=0.02, g=0.08, log=print):
    root = resolve(snapshot)
    man = load_manifest(root)
    cos = companies(root, man)
    out = {}
    for t, c in sorted(cos.items()):
        if c.get('market') != 'KR':
            continue
        try:
            pr, _ = read_rows(root, man, 'price_daily', t)
            ff, _ = read_rows(root, man, 'financial_fact', t)
        except Exception:
            continue
        rows = sorted((x for x in pr if _PS.ok(x.get('source')) and _f(x.get('close')) and _f(x.get('market_cap'))), key=lambda x: x['trade_date'])
        if len(rows) < 260:
            continue
        qt = E.dart_quarters(ff)
        if len(qt) < 4:
            continue
        pts = E.series(rows, qt, r, g_lt, g, 0)
        if len(pts) < 2:
            continue
        mc = {x['trade_date']: _f(x['market_cap']) for x in rows}
        out[t] = {'name': c.get('name'), 'sector': c.get('krx_sector'), 'fin': c.get('krx_sector') in FIN_SECTORS,
                  'pts': pts, 'mcap': mc, 'closes': [(x['trade_date'], _f(x['close'])) for x in rows], 'windows': E.windows(pts, g)}
    log(f'회사 {len(out)}곳 계산 (사본 {root.name})')
    return root, man, out


def _wmedian(vals):
    """[(값, 가중치)] → 가중 중앙값."""
    vals = sorted(v for v in vals if v[0] is not None and v[1])
    tot = sum(w for _, w in vals)
    if not tot:
        return None
    acc = 0
    for v, w in vals:
        acc += w
        if acc >= tot / 2:
            return v
    return vals[-1][0]


def _month_ends(dates):
    by = {}
    for d in dates:
        by[d[:7]] = max(by.get(d[:7], d), d)
    return [by[k] for k in sorted(by)]


def thermometer(data, exclude_fin=False):
    all_dates = sorted({p['date'] for c in data.values() for p in c['pts']})
    ends = _month_ends(all_dates)
    idx = {t: {p['date']: p for p in c['pts']} for t, c in data.items()}
    rows = []
    for D in ends:
        lo = (date.fromisoformat(D) - timedelta(days=7)).isoformat()
        edi_w, edi_e, cap_all, cap_in = [], [], 0.0, 0.0
        ph_cap = {}
        for t, c in data.items():
            if exclude_fin and c['fin']:
                continue
            p = idx[t].get(D)
            if not p:
                cand = [d for d in idx[t] if lo <= d <= D]
                p = idx[t][max(cand)] if cand else None
            if not p:
                continue
            m = c['mcap'].get(p['date'])
            if not m:
                continue
            cap_all += m
            if p['EDI_norm'] is not None and not p.get('unstable_norm') and p['age'] <= E.STALE_DAYS:
                edi_w.append((p['EDI_norm'], m)); edi_e.append((p['EDI_norm'], 1)); cap_in += m
            rec = [w for w in c['windows'] if w['phase'] != 'open' and w['end'] <= D and w['end'] >= (date.fromisoformat(D) - timedelta(days=RECENT_DAYS)).isoformat()]
            ph = rec[-1]['phase'] if rec else 'none'
            ph_cap[ph] = ph_cap.get(ph, 0) + m
        if not cap_all:
            continue
        rows.append({'date': D, 'edi_cap_median': _wmedian(edi_w), 'edi_eq_median': _wmedian(edi_e), 'n': len(edi_w),
                     'coverage_cap': cap_in / cap_all, 'phase_cap_share': {k: v / cap_all for k, v in ph_cap.items()}})
    return rows


def _fwd(closes, i):
    """i일 종가에서 FWD 거래일 뒤 수익률과 그 사이 최대 낙폭."""
    if i + FWD >= len(closes):
        return None, None
    p0 = closes[i][1]
    peak, mdd = p0, 0.0
    for _, p in closes[i:i + FWD + 1]:
        peak = max(peak, p); mdd = min(mdd, p / peak - 1)
    return closes[i + FWD][1] / p0 - 1, mdd


def observations(data):
    obs = []
    for t, c in data.items():
        pos = {d: k for k, (d, _) in enumerate(c['closes'])}
        pidx = {p['date']: p for p in c['pts']}
        for w in c['windows']:
            if w['phase'] in ('open', 'held', 'split'):
                continue
            i = pos.get(w['end'])
            if i is None or i < MOM:
                continue
            fr, mdd = _fwd(c['closes'], i)
            if fr is None:
                continue
            p = pidx.get(w['end'])
            lr = [math.log(c['closes'][k][1] / c['closes'][k - 1][1]) for k in range(i - MOM + 1, i + 1)]
            mu = sum(lr) / len(lr)
            vol = math.sqrt(sum((x - mu) ** 2 for x in lr) / (len(lr) - 1)) * math.sqrt(252)
            obs.append({'vol': vol, 'ticker': t, 'end': w['end'], 'q': f"{w['end'][:4]}Q{(int(w['end'][5:7]) - 1) // 3 + 1}", 'phase': w['phase'],
                        'edi': p['EDI_norm'] if p and not p.get('unstable_norm') else None, 'mom': c['closes'][i][1] / c['closes'][i - MOM][1] - 1,
                        'fwd_ret': fr, 'fwd_mdd': mdd, 'fin': c['fin']})
    return obs


def _rank(xs):
    o = sorted(range(len(xs)), key=lambda k: xs[k]); r = [0.0] * len(xs)
    for k, i in enumerate(o):
        r[i] = k
    return r


def _spearman(x, y):
    if len(x) < 10:
        return None
    rx, ry = _rank(x), _rank(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry)); sxx = sum((a - mx) ** 2 for a in rx); syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx and syy else None


def _ols_dummy(y, mom, d, vol=None):
    """y = b0 + b1·mom (+ b3·vol) + b2·d 의 b2."""
    import numpy as np
    cols = [np.ones(len(y)), mom, d] + ([vol] if vol is not None else [])
    X = np.column_stack(cols)
    try:
        b = np.linalg.lstsq(X, np.array(y), rcond=None)[0]
    except Exception:
        return None
    return float(b[2])


def _gate(per_q, want_sign):
    """분기별 값(per_q: [(q, v)]) → 통과 여부. 부호 일치 분기 비율 ≥ 2/3, 앞·뒤 절반 모두 같은 방향."""
    vals = [(q, v) for q, v in per_q if v is not None]
    if len(vals) < 6:
        return {'pass': False, 'why': f'쓸 수 있는 분기 {len(vals)}개 — 6개 미만', 'quarters': len(vals)}
    hit = [1 if (v > 0) == (want_sign > 0) else 0 for _, v in vals]
    h = len(vals) // 2
    first, second = hit[:h], hit[h:]
    share = sum(hit) / len(hit)
    ok = share >= PASS_SHARE and sum(first) / len(first) > 0.5 and sum(second) / len(second) > 0.5
    return {'pass': ok, 'share': round(share, 3), 'first_half': round(sum(first) / len(first), 3), 'second_half': round(sum(second) / len(second), 3),
            'quarters': len(vals), 'median': round(sorted(v for _, v in vals)[len(vals) // 2], 4)}


def validate(obs):
    qs = sorted({o['q'] for o in obs})
    res = {}
    # H1: 구간 끝 EDI가 높을수록 이후 6개월 최대 낙폭이 깊은가 (분기별 순위상관, 음수 기대)
    per = []
    for q in qs:
        xs = [o for o in obs if o['q'] == q and o['edi'] is not None]
        per.append((q, _spearman([o['edi'] for o in xs], [o['fwd_mdd'] for o in xs])))
    ctl = []
    for q in qs:
        xs = [o for o in obs if o['q'] == q and o['edi'] is not None]
        if len(xs) < 20:
            ctl.append((q, None)); continue
        rk = lambda key: [v / (len(xs) - 1) for v in _rank([o[key] for o in xs])]       # 분기 안 순위(0~1)로 바꿔 극단값 영향 줄임
        ctl.append((q, _ols_dummy(rk('fwd_mdd'), rk('mom'), rk('edi'), rk('vol'))))
    g_raw, g_ctl = _gate(per, -1), _gate(ctl, -1)
    res['H1_edi_vs_drawdown'] = {'question': '구간이 끝날 때 EDI가 높을수록 이후 6개월 최대 낙폭이 더 깊었나 (분기별 순위상관이 음수, 지난 6개월 수익률·변동성 통제 포함)',
                                 'raw': {'per_quarter': per, **g_raw}, 'momentum_controlled': {'per_quarter': ctl, **g_ctl}, 'pass': g_raw['pass'] and g_ctl['pass']}
    # H2: 「기대 차입」 vs 「건강한 상환」 — 이후 6개월 수익률 (모멘텀 통제 후 차이가 음수 기대)
    def contrast(a, b, y, want, label):
        raw, ctl = [], []
        for q in qs:
            A = [o for o in obs if o['q'] == q and o['phase'] == a]; B = [o for o in obs if o['q'] == q and o['phase'] == b]
            if len(A) < 5 or len(B) < 5:
                raw.append((q, None)); ctl.append((q, None)); continue
            raw.append((q, sum(o[y] for o in A) / len(A) - sum(o[y] for o in B) / len(B)))
            S = A + B
            ctl.append((q, _ols_dummy([o[y] for o in S], [o['mom'] for o in S], [1.0 if o['phase'] == a else 0.0 for o in S], [o['vol'] for o in S])))
        return {'question': label, 'raw': {'per_quarter': raw, **_gate(raw, want)}, 'momentum_controlled': {'per_quarter': ctl, **_gate(ctl, want)},
                'pass': _gate(raw, want)['pass'] and _gate(ctl, want)['pass']}
    res['H2_borrow_vs_healthy'] = contrast('price_ahead', 'earn_led', 'fwd_ret', -1, '「기대 차입」 구간 뒤 6개월 수익률이 「건강한 상환」 구간 뒤보다 낮았나 (지난 6개월 수익률·변동성 통제 포함)')
    res['H3_forced_vs_healthy'] = contrast('price_led', 'earn_led', 'fwd_mdd', -1, '「강제 상환」 구간 뒤 6개월 최대 낙폭이 「건강한 상환」 구간 뒤보다 깊었나 (지난 6개월 수익률·변동성 통제 포함)')
    res['overall'] = {k: v['pass'] for k, v in res.items()}
    res['n_obs'] = len(obs); res['quarters'] = qs
    res['phase_counts'] = {k: sum(1 for o in obs if o['phase'] == k) for k in DECISIVE}
    return res


CAVEATS = [
    '대상은 지금 사본에 있는 국내 상장사(팀이 고른 목록)입니다. 그동안 상장폐지된 회사가 없어 과거 결과가 좋게 보일 수 있습니다(생존 편향).',
    '정정 공시가 있던 보고서는 정정일이 공개일로 잡힙니다(늦게 잡히는 쪽, 미래정보 없음). 대신 그 사이 구간은 「재무가 오래됨」으로 보류될 수 있습니다.',
    '우선주 수를 모르므로 보통주 수만 썼습니다. EDI 수준은 우선주가 있는 회사에서 낮게 나오지만, 구간 안의 변화(국면)는 영향을 받지 않습니다.',
    '자본·순이익은 비지배지분을 포함한 연결 값입니다. 금융업(기타금융·보험·증권·은행)은 결과에 함께 넣고, 뺀 결과도 따로 냅니다.',
    'ROE가 장기성장률(2%)에 가깝거나 아래인 회사·날짜는 V를 계산할 수 없어 체온계에서 빠집니다(시가총액 기준 포함 비율을 함께 적음).',
    '같은 분기의 회사들은 시장 전체 움직임을 함께 받으므로, 관측치를 모두 합친 유의확률 대신 분기별 부호가 얼마나 일관됐는지로 봅니다.',
    'V와 EDI는 자기자본비용 9%·장기성장 2%·g 8% 가정 아래의 계산값이며 적정주가·목표주가·매매 신호가 아닙니다.',
]


def run(snapshot='', out_dir=None, log=print):
    root, man, data = load(snapshot, log=log)
    th = thermometer(data); th_x = thermometer(data, exclude_fin=True)
    obs = observations(data)
    val = validate(obs)
    out = Path(out_dir) if out_dir else ROOT / 'data' / 'edi_market' / root.name
    out.mkdir(parents=True, exist_ok=True)
    latest = []
    for t, c in data.items():
        p = c['pts'][-1]
        done = [w for w in c['windows'] if w['phase'] != 'open']
        op = c['windows'][-1] if c['windows'] and c['windows'][-1]['phase'] == 'open' else None
        latest.append({'ticker': t, 'name': c['name'], 'sector': c['sector'], 'financial': c['fin'], 'date': p['date'], 'close': p['P'],
                       'market_cap': c['mcap'].get(p['date']), 'V_norm': p['V_norm'], 'EDI_norm': p['EDI_norm'], 'EDI_ttm': p['EDI_ttm'], 'EDI_book': p['EDI_book'],
                       'unstable': p.get('unstable_norm'), 'last_phase': done[-1]['phase'] if done else None,
                       'last_phase_kiri': E.PHASES[done[-1]['phase']][1] if done else None,
                       'last_share_V': done[-1].get('share_V') if done else None, 'open_since': op['start'] if op else None,
                       'open_price_chg': (op['P1'] / op['P0'] - 1) if op else None})
    meta = {'snapshot': root.name, 'manifest_sha256': man['_manifest_sha256'], 'companies': len(data),
            'assumptions': {'cost_of_equity': 0.09, 'long_growth': 0.02, 'edi_growth': 0.08, 'share_lead': E.SHARE_LEAD, 'min_years': E.MIN_YEARS,
                            'stale_days': E.STALE_DAYS, 'stable_gap': E.STABLE_GAP, 'recent_days': RECENT_DAYS, 'fwd_days': FWD},
            'phase_names': {k: {'app': v[0], 'kiri': v[1]} for k, v in E.PHASES.items()}, 'caveats': CAVEATS}
    (out / 'market.json').write_text(json.dumps({'meta': meta, 'thermometer': th, 'thermometer_ex_fin': th_x, 'latest': latest}, ensure_ascii=False, default=float), encoding='utf-8')
    (out / 'validation.json').write_text(json.dumps({'meta': meta, **val}, ensure_ascii=False, default=float), encoding='utf-8')
    with open(out / 'companies.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=list(latest[0].keys())); w.writeheader(); w.writerows(latest)
    (out / 'report.md').write_text(report(meta, th, th_x, val), encoding='utf-8')
    log(f'저장: {out}')
    return out, meta, th, th_x, val, latest


def report(meta, th, th_x, val):
    ok = val['overall']
    lines = [f"# 기대 부채 체온계 · 검증 관문 — 사본 {meta['snapshot']}", '',
             '## 검증 관문 결과 (맨 먼저 읽기)', '',
             f"관측 {val['n_obs']}개 구간, 분기 {len(val['quarters'])}개. 통과 = 분기별 부호가 2/3 이상 같은 방향이고 앞·뒤 절반에서 모두 과반, 지난 6개월 수익률·변동성을 통제해도 같은 방향.", '']
    for k, v in val.items():
        if not k.startswith('H'):
            continue
        lines.append(f"- **{k}** — {v['question']}: {'통과' if v['pass'] else '미통과'}")
        if 'share' in v:
            lines.append(f"  - 같은 방향 분기 비율 {v['share']} (앞 절반 {v['first_half']}, 뒤 절반 {v['second_half']}), 분기 {v['quarters']}개, 분기별 중앙값 {v['median']}")
        for sub in ('raw', 'momentum_controlled'):
            if sub in v:
                s = v[sub]
                lines.append(f"  - {'원래' if sub == 'raw' else '지난 6개월 수익률·변동성 통제'}: " + (f"같은 방향 {s.get('share')} (앞 {s.get('first_half')}, 뒤 {s.get('second_half')}), 분기 {s['quarters']}개, 중앙값 {s.get('median')}" if 'share' in s else s['why']))
    lines += ['', '통과하지 못한 가설의 국면은 「기록」으로만 보여 주고, 앞으로의 방향을 시사하는 말을 붙이지 않습니다.', '',
              '## 체온계 (최근 6개월)', '', '| 월말 | 시총가중 EDI 중앙값 | 동일가중 | 포함 시총 비율 | 금융업 제외 |', '|---|---|---|---|---|']
    ex = {r['date']: r for r in th_x}
    for r in th[-6:]:
        x = ex.get(r['date'], {})
        f = lambda v: '-' if v is None else f'{v:+.1f}년'
        lines.append(f"| {r['date']} | {f(r['edi_cap_median'])} | {f(r['edi_eq_median'])} | {r['coverage_cap']*100:.0f}% | {f(x.get('edi_cap_median'))} |")
    lines += ['', '## 읽을 때 주의', ''] + [f'- {c}' for c in meta['caveats']]
    return '\n'.join(lines) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='기대 부채 체온계 + 검증 관문')
    ap.add_argument('--snapshot', default='')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    run(a.snapshot, a.out)
