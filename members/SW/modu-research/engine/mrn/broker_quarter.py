"""v0.24 미리 보기: 증권사 보고서의 ① 분기 전망(매출액·영업이익) ② 연간 순이익 전망 추출 + ③ 분기 「전망 성적표」.

원칙 (v0.21 일괄 받기와 같음)
- 먼저 미리 보기: DB는 건드리지 않고 CSV만 만든다. 표본 30건을 PDF와 대조해 틀림이 2건 이하일 때만 다음 단계(저장)로 간다.
- 표의 과거 열이 공시(DART 정기보고서)와 맞는 단위로만 숫자를 확정한다. 안 맞으면 「사람 확인」으로 남긴다.
- 분기 열 머리글의 꼬리표: E·F = 전망, P = 잠정 실적(전망 아님), A·없음 = 실적. 전망은 E·F만 쓴다.
- 성적표의 「공시 전날까지」 기준일 = 그 분기 첫 잠정실적 공시일(없으면 DART 정기보고서 접수일). 그날 이후 보고서는 채점하지 않는다.
- 실제값은 DART 정기보고서 분기값만 쓴다. 증권사 표의 P(잠정) 숫자는 실제값으로 쓰지 않는다.
- 목표주가·투자의견은 다루지 않는다.
"""
import csv
import gzip
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

from .broker import NUM, UNIT_MULT, _num, _units_near, broker_dir, load_manifest, report_ticker

EXTRACTOR_Q = 'q1'
QTOK = r'[1-4]Q\d{2}[AEFP]?'
QHEAD = re.compile(r'((?:' + QTOK + r'\s+){3,}' + QTOK + r')((?:\s+20\d\d[AEFP]?)*)')
YHEAD = re.compile(r'((?:20\d\d[AEFP]?\s+){2,}20\d\d[AEFP]?)')
Q_LABELS = {'revenue': ['매출액', '순매출액'], 'operatingProfit': ['영업이익']}
# 순이익은 두 가지를 섞지 않는다: 연결 당기순이익(비지배 포함, EDI가 쓰는 값) / 지배주주순이익
NI_SETS = {'netIncome': ['당기순이익', '순이익', '연결순이익'],
           'netIncomeOwners': ['지배주주순이익', '지배주주 순이익', '지배순이익', '지배주주지분순이익', '지배지분순이익']}
NI_ACCOUNT = {'netIncome': 'ifrs-full_ProfitLoss', 'netIncomeOwners': 'ifrs-full_ProfitLossAttributableToOwnersOfParent'}
FORECAST_TAG = ('E', 'F')


def qparse(tok):
    """'3Q26E' → (2026, 3, 'E')."""
    m = re.fullmatch(r'([1-4])Q(\d{2})([AEFP]?)', tok)
    return (2000 + int(m.group(2)), int(m.group(1)), m.group(3)) if m else None


def _row_first(after, labels, n):
    """행 이름 정확 일치(앞에 한글이 붙지 않음) 뒤의 숫자 n개를 왼쪽부터. 칸이 모자라면 None(열이 밀릴 수 있어 쓰지 않음)."""
    for kor in labels:
        rm = re.search(r'(?<![가-힣])(' + re.escape(kor) + r')(?![가-힣])[^0-9\-\(]{0,12}((?:' + NUM + r'\s+){' + str(n - 1) + r',}' + NUM + ')', after)
        if rm:
            vals = rm.group(2).split()
            if len(vals) < n:
                return None
            return vals[:n], rm.group(0), rm.group(1)
    return None


def find_q_tables(pages):
    """분기 열이 4개 이상인 표(뒤에 연간 열이 붙어도 됨)에서 매출액·영업이익 행."""
    out = []
    for pno, raw in enumerate(pages, 1):
        flat = re.sub(r'\s+', ' ', raw)
        for hm in QHEAD.finditer(flat):
            qcols = hm.group(1).split()
            ycols = hm.group(2).split()
            keys = [q[:4] for q in qcols]
            if len(set(keys)) != len(keys):
                continue                                              # 같은 분기가 두 번 → 비교표
            cols = qcols + ycols
            after = flat[hm.end(): hm.end() + 2500]
            rows, quotes = {}, {}
            for metric, labels in Q_LABELS.items():
                hit = _row_first(after, labels, len(cols))
                if not hit:
                    continue
                vals, q, _ = hit
                rows[metric] = {c: (_num(v), v) for c, v in zip(qcols, vals[:len(qcols)]) if _num(v) is not None}
                quotes[metric] = (hm.group(0).strip() + ' … ' + q.strip())[:240]
            if rows and any(qparse(c)[2] in FORECAST_TAG for c in qcols):
                out.append({'page': pno, 'cols': qcols, 'units': _units_near(flat, hm.start()), 'rows': rows, 'quote': quotes})
    return out


def _qchecks(table, unit, actual):
    """표의 실적 분기 열(꼬리표 A·없음)을 DART 분기값과 대조. P(잠정)는 대조하지 않는다."""
    mult = UNIT_MULT[unit]
    out = []
    for metric, row in table['rows'].items():
        for col, (val, raw) in row.items():
            y, q, tag = qparse(col)
            if tag in FORECAST_TAG or tag == 'P':
                continue
            a = actual.get((y, q, metric))
            if a is None:
                continue
            out.append({'col': col, 'metric': metric, 'broker_mn': format(val * mult, 'f'), 'dart_mn': format(a, 'f'),
                        'match': abs(val * mult - a) <= max(mult / 2 + 1, abs(a) * Decimal('0.005'))})
    return out


def choose_q(tables, actual):
    best = None
    for t in tables:
        for rank, unit in enumerate(t['units']):
            ch = _qchecks(t, unit, actual)
            ok = len(ch) >= 2 and all(c['match'] for c in ch)
            score = (1 if ok else 0, len(ch), -rank, -t['page'])
            if best is None or score > best[0]:
                best = (score, t, unit, ch, 'match' if ok else ('mismatch' if ch else 'not_available'))
    return best[1:] if best else (None, None, [], 'no_table')


def find_ni(pages, labels):
    """연간 표의 순이익 행 (연도 머리글 + 정확한 행 이름)."""
    out = []
    for pno, raw in enumerate(pages, 1):
        flat = re.sub(r'\s+', ' ', raw)
        for hm in YHEAD.finditer(flat):
            years = hm.group(1).split()
            if len({y[:4] for y in years}) != len(years):
                continue
            after = flat[hm.end(): hm.end() + 3000]
            for kor in labels:
                rm = re.search(r'(?<![가-힣])(' + re.escape(kor) + r')(?![가-힣])[^0-9\-\(]{0,12}((?:' + NUM + r'\s+){' + str(len(years) - 1) + r',}' + NUM + ')', after)
                if rm:
                    vals = rm.group(2).split()
                    vals = vals[-len(years):] if len(vals) > len(years) else vals     # 연간 열은 오른쪽 (분기 열이 앞에 있을 수 있음)
                    row = {y: (_num(v), v) for y, v in zip(years, vals) if _num(v) is not None}
                    if row:
                        out.append({'page': pno, 'years': years, 'units': _units_near(flat, hm.start()), 'row': row,
                                    'label': rm.group(1), 'quote': (hm.group(1) + ' … ' + rm.group(0))[:240]})
                    break
    return out


def choose_ni(tables, annual_ni, base_year=2025):
    best = None
    for t in tables:
        for rank, unit in enumerate(t['units']):
            mult = UNIT_MULT[unit]
            ch = []
            for y, (val, raw) in t['row'].items():
                fy = int(y[:4])
                if re.search(r'[EF]$', y) or fy > base_year or fy not in annual_ni:
                    continue
                a = annual_ni[fy]
                ch.append({'year': fy, 'broker_mn': format(val * mult, 'f'), 'dart_mn': format(a, 'f'),
                           'match': abs(val * mult - a) <= max(mult / 2 + 1, abs(a) * Decimal('0.005'))})
            ok = bool(ch) and all(c['match'] for c in ch)
            # 표본 대조(v0.24)에서 「순이익」만 적힌 행은 지배주주 몫일 수 있었다 → 「당기순이익」처럼 분명한 행 이름을 먼저 고른다
            lab = 0 if t['label'] in ('당기순이익', '연결순이익') or t['label'] in NI_SETS['netIncomeOwners'] else 1
            score = (1 if ok else 0, -lab, len(ch), -rank, -t['page'])
            if best is None or score > best[0]:
                best = (score, t, unit, ch, 'match' if ok else ('mismatch' if ch else 'not_available'))
    return best[1:] if best else (None, None, [], 'no_table')


# ---------------------------------------------------------------- 실제값 · 기준일 (Neon 사본, 읽기 전용)
RC_Q = {'11013': 1, '11012': 2, '11014': 3, '11011': 4}
ACC_Q = {'ifrs-full_Revenue': 'revenue', 'dart_OperatingIncomeLoss': 'operatingProfit'}


def dart_actuals(ff_rows):
    """DART 정기보고서 → {(연도, 분기, 지표): 백만원}(분기 단독값) · {연도: 지배주주순이익 백만원} · {(연도, 분기): 접수일}.
    1~3분기는 그 보고서의 당기(3개월) 값, 4분기는 사업보고서 연간값 − 3분기 누적값. 연결(CFS) 우선."""
    best, filed = {}, {}
    ni = {}
    for r in ff_rows:
        q = RC_Q.get(str(r.get('report_code')))
        if not q or r.get('amount') in (None, ''):
            continue
        y = int(r['fiscal_year'])
        rc = str(r.get('rcept_no') or '')
        if len(rc) >= 8 and rc[:8].isdigit():
            d = f'{rc[:4]}-{rc[4:6]}-{rc[6:8]}'
            filed[(y, q)] = min(filed.get((y, q), d), d)
        for nk, acc in NI_ACCOUNT.items():
            if q == 4 and r.get('account_id') == acc and r.get('fs_div') == 'CFS' and r.get('sj_div') in ('IS', 'CIS'):
                ni.setdefault(nk, {}).setdefault(y, Decimal(str(r['amount'])) / Decimal(1000000))
        m = ACC_Q.get(r.get('account_id'))
        if not m:
            continue
        k = (y, q, m, r.get('fs_div'))
        if k not in best:
            best[k] = r
    out = {}
    for (y, q, m, fs) in list(best):
        if fs != 'CFS' and (y, q, m, 'CFS') in best:
            continue
        r = best[(y, q, m, fs)]
        a = Decimal(str(r['amount']))
        if q == 4:
            p3 = best.get((y, 3, m, fs))
            if not p3 or p3.get('amount_ytd') in (None, ''):
                continue
            a = a - Decimal(str(p3['amount_ytd']))
        out[(y, q, m)] = a / Decimal(1000000)
    return out, ni, filed


def prelim_dates(disclosures):
    """잠정실적 공시일 목록(오름차순). 「영업(잠정)실적」·「잠정실적」 제목만."""
    return sorted({str(r.get('rcept_dt'))[:10] for r in disclosures if '잠정' in (r.get('report_nm') or '') and '실적' in (r.get('report_nm') or '')})


Q_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _minus_days(d, n):
    from datetime import timedelta
    return (date.fromisoformat(d[:10]) - timedelta(days=n)).isoformat()


def known_date(y, q, prelims, filed):
    """그 분기 실적이 처음 알려진 날 = 분기 말 뒤 첫 잠정실적 공시일과 정기보고서 접수일 중 이른 날."""
    end = date(y, *Q_END[q]).isoformat()
    cands = [d for d in prelims if d > end]
    if filed.get((y, q)):
        cands.append(filed[(y, q)])
    return min(cands) if cands else None


def scorecard(forecasts, actual, known):
    """forecasts: [{ticker, broker, report_date, fiscal_year, quarter, metric, value_mn}]
    → 회사·분기·지표·증권사마다 「실적이 알려지기 전날까지」 마지막 전망 하나 + 실제값 + 오차(%).
    known[(ticker, y, q)] = 실적이 처음 알려진 날. 그날 이후 보고서는 뺀다. 실제값이 아직 없으면 status='awaiting'."""
    last = {}
    for f in forecasts:
        k = (f['ticker'], f['fiscal_year'], f['quarter'])
        kd = known.get(k)
        if kd and f['report_date'] >= kd:
            continue                                                    # 실적이 알려진 뒤의 보고서는 전망이 아님
        key = k + (f['metric'], f['broker'])
        if key not in last or f['report_date'] > last[key]['report_date']:
            last[key] = f
    out = []
    for (t, y, q, m, b), f in sorted(last.items()):
        a = actual.get((t, y, q, m))
        row = {'ticker': t, 'period': f'{y}Q{q}', 'metric': m, 'broker': b, 'report_date': f['report_date'], 'forecast_mn': f['value_mn'],
               'known_date': known.get((t, y, q)) or '', 'actual_mn': '', 'error_pct': '', 'status': 'awaiting'}
        if a is not None and a != 0:
            fv = Decimal(str(f['value_mn']))
            row.update(actual_mn=format(a, 'f'), error_pct=format(((fv - a) / abs(a) * 100).quantize(Decimal('0.1')), 'f'), status='scored')
        out.append(row)
    return out


# ---------------------------------------------------------------- 미리 보기 (DB 쓰지 않음)
def _pages_cached(d, sha):
    p = d / '_textcache' / sha[:2] / f'{sha}.json.gz'
    if not p.exists():
        return None
    return json.loads(gzip.decompress(p.read_bytes()).decode('utf-8'))


def preview(out_dir, snapshot='', limit=None):
    import random
    from . import market as M
    d = broker_dir()
    man = load_manifest(d)
    root = M.resolve(snapshot)
    mf = M.load_manifest(root)
    qrows, nirows, reports = [], [], []
    cache = {}

    def facts(t):
        if t not in cache:
            try:
                ff, _ = M.read_rows(root, mf, 'financial_fact', t)
            except Exception:
                ff = []
            try:
                ds, _ = M.read_rows(root, mf, 'disclosure', t)
            except Exception:
                ds = []
            cache[t] = (*dart_actuals(ff), prelim_dates(ds))
        return cache[t]

    items = sorted(man.items())[:limit] if limit else sorted(man.items())
    for fname, meta in items:
        t = report_ticker(meta)
        pages = _pages_cached(d, meta.get('sha256', ''))
        rep = {'file': fname, 'ticker': t, 'broker': meta.get('증권사', ''), 'report_date': meta.get('보고서일', fname[:8])}
        if not t or pages is None:
            rep['q_status'] = rep['netIncome_status'] = rep['netIncomeOwners_status'] = 'no_text'
            reports.append(rep)
            continue
        act, ni, filed, pre = facts(t)
        qa = {(y, q, m): v for (y, q, m), v in act.items()}
        tq, uq, chq, stq = choose_q(find_q_tables(pages), qa)
        rep['q_status'] = stq
        if tq:
            for metric, row in tq['rows'].items():
                for col, (val, raw) in row.items():
                    y, q, tag = qparse(col)
                    if tag not in FORECAST_TAG or date(y, *Q_END[q]).isoformat() < _minus_days(rep['report_date'], 100):
                        continue
                    qrows.append({'file': fname, 'ticker': t, 'broker': rep['broker'], 'report_date': rep['report_date'], 'fiscal_year': y, 'quarter': q,
                                  'col': col, 'metric': metric, 'value_mn': format(val * UNIT_MULT[uq], 'f'), 'value_original': raw, 'unit': uq,
                                  'page': tq['page'], 'past_check': stq, 'checks': len(chq), 'quote': tq['quote'].get(metric, ''),
                                  'auto_ok': stq == 'match'})
        for nk, labels in NI_SETS.items():
            tn, un, chn, stn = choose_ni(find_ni(pages, labels), ni.get(nk, {}))
            rep[f'{nk}_status'] = stn
            if not tn:
                continue
            for y, (val, raw) in tn['row'].items():
                fy = int(y[:4])
                if not (re.search(r'[EF]$', y) or fy > 2025):
                    continue
                nirows.append({'file': fname, 'ticker': t, 'broker': rep['broker'], 'report_date': rep['report_date'], 'fiscal_year': fy, 'col': y,
                               'metric': nk, 'row_label': tn['label'], 'value_mn': format(val * UNIT_MULT[un], 'f'), 'value_original': raw,
                               'unit': un, 'page': tn['page'], 'past_check': stn, 'checks': len(chn), 'quote': tn['quote'], 'auto_ok': stn == 'match'})
        reports.append(rep)
    # 성적표 (자동 확인 통과한 분기 전망만)
    known, actual = {}, {}
    for t in {r['ticker'] for r in qrows}:
        act, ni, filed, pre = facts(t)
        for (y, q, m), v in act.items():
            actual[(t, y, q, m)] = v
        for (y, q) in {(r['fiscal_year'], r['quarter']) for r in qrows if r['ticker'] == t}:
            known[(t, y, q)] = known_date(y, q, pre, filed)
    sc = scorecard([r for r in qrows if r['auto_ok']], actual, known)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def wcsv(name, rows):
        with open(out / name, 'w', encoding='utf-8-sig', newline='') as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    wcsv('quarterly_forecasts.csv', qrows)
    wcsv('netincome_forecasts.csv', nirows)
    wcsv('scorecard.csv', sc)
    rnd = random.Random(20261109)
    wcsv('sample30_quarterly.csv', rnd.sample([r for r in qrows if r['auto_ok']], min(30, sum(r['auto_ok'] for r in qrows))))
    wcsv('sample30_netincome.csv', rnd.sample([r for r in nirows if r['auto_ok']], min(30, sum(r['auto_ok'] for r in nirows))))
    from collections import Counter
    summary = {
        'reports': len(reports),
        'quarterly': {'reports_by_status': dict(Counter(r.get('q_status') for r in reports)), 'forecasts': len(qrows),
                      'forecasts_auto_ok': sum(r['auto_ok'] for r in qrows), 'companies_auto_ok': len({r['ticker'] for r in qrows if r['auto_ok']}),
                      'by_period': dict(Counter(f"{r['fiscal_year']}Q{r['quarter']}" for r in qrows if r['auto_ok']))},
        'netincome': {nk: {'reports_by_status': dict(Counter(r.get(f'{nk}_status') for r in reports)),
                           'forecasts': sum(r['metric'] == nk for r in nirows), 'forecasts_auto_ok': sum(r['auto_ok'] and r['metric'] == nk for r in nirows),
                           'companies_auto_ok': len({r['ticker'] for r in nirows if r['auto_ok'] and r['metric'] == nk})} for nk in NI_SETS},
        'scorecard': {'rows': len(sc), 'scored': sum(r['status'] == 'scored' for r in sc), 'awaiting': sum(r['status'] == 'awaiting' for r in sc),
                      'by_period': dict(Counter((r['period'], r['status']) for r in sc).most_common()) if False else
                      {f"{p}:{s}": n for (p, s), n in Counter((r['period'], r['status']) for r in sc).items()}},
        'db_written': False,
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return summary


AUTO = 'auto-rule-q1'


def apply(data_dir, out_dir, owner='broker_quarter'):
    """미리 보기를 다시 만들고(같은 규칙), 그 행을 새 표 broker_forecasts_v2에 넣는다. 자동 확인 통과 = 승인(auto-rule-q1), 나머지 = 제안.
    이미 있는 행은 건드리지 않는다. 되돌리기: revert (auto-rule-q1 승인 행만 지움)."""
    from .store import Store
    s = preview(out_dir)
    rows = []
    man = load_manifest(broker_dir())
    for name in ('quarterly_forecasts.csv', 'netincome_forecasts.csv'):
        with open(Path(out_dir) / name, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                if name.startswith('netincome') and r['metric'] != 'netIncome':
                    continue                                  # 지배주주순이익은 공시 대조 자료가 모자라 아직 넣지 않음
                r['sha256'] = man.get(r['file'], {}).get('sha256', '')
                r['quarter'] = r.get('quarter', '')
                r['auto_ok'] = r['auto_ok'] == 'True'
                if r['sha256']:
                    rows.append(r)
    st = Store(str(data_dir))
    new = st.v2_forecasts_put(owner, rows, AUTO)
    return {'preview': s, 'rows': len(rows), 'new': new, 'counts': st.v2_counts()}


if __name__ == '__main__':
    import argparse
    import os
    from datetime import datetime
    ap = argparse.ArgumentParser(description='분기·순이익 전망: preview(미리 보기, DB에 안 씀) / apply(새 표에 넣기) / revert(자동 승인분 지우기) / status')
    ap.add_argument('cmd', choices=['preview', 'apply', 'revert', 'status'])
    ap.add_argument('--out', default='')
    ap.add_argument('--limit', type=int, default=None)
    a = ap.parse_args()
    root = Path(os.environ.get('MODU_NODES_DATA_DIR') or Path(__file__).resolve().parents[1] / 'data')
    out = a.out or str(root / 'broker_auto' / (f'quarter_{a.cmd}_' + datetime.now().strftime('%Y%m%dT%H%M%S')))
    if a.cmd == 'preview':
        print(json.dumps(preview(out, limit=a.limit), ensure_ascii=False, indent=1)); print('→', out)
    elif a.cmd == 'apply':
        r = apply(root, out)
        print(json.dumps({k: r[k] for k in ('rows', 'new', 'counts')}, ensure_ascii=False, indent=1)); print('→', out)
    else:
        from .store import Store
        st = Store(str(root))
        if a.cmd == 'revert':
            print('지운 자동 승인 행:', st.v2_forecasts_revert('broker_quarter', AUTO))
        print(json.dumps(st.v2_counts(), ensure_ascii=False, indent=1))
