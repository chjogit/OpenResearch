"""증권사 보고서 일괄 등록 · 스캔 · 자동 승인 (v0.22, 자동 승인 규칙 v2).

    python -m mrn.broker_auto run --from 2026-08-08 --to 2026-11-08   # 등록 → 스캔 → 규칙 통과분 자동 승인 → 표본 30건
    python -m mrn.broker_auto run --from ... --to ... --dry-run       # DB 사본으로 돌려 바뀌는 값 목록만 만든다(실제 DB는 그대로)
    python -m mrn.broker_auto revert                                  # 자동 승인한 것만(v1·v2) 전부 '제안' 상태로 되돌림
    python -m mrn.broker_auto rename [--apply]                        # 파일 이름에 회사명 넣기: 기본은 계획만, --apply로 실행
    python -m mrn.broker_auto status                                  # 자동/사람 승인 현황

원칙
- 사람이 이미 승인·거절·수정한 값은 건드리지 않는다(상태가 'proposed'인 것만 자동 승인).
- 자동 승인은 reviewer='auto-rule-v1'로 남기고, 한 번에 되돌릴 수 있다.
- 규칙을 통과하지 못한 보고서는 '제안'으로 남아 사람이 앱에서 본다.
- 표본 30건(sample30.csv)을 원문과 대조해 틀린 비율을 먼저 확인한 뒤 결과를 쓴다.
"""
import argparse
import csv
import json
import os
import random
import re
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path

from . import broker

RULE = 'auto-rule-v2'
AUTO_PREFIX = 'auto-rule-'
ROOT = Path(__file__).resolve().parents[1]
KST = timezone(timedelta(hours=9))
RULE_TEXT = {
    'R1': '파일 해시가 등록 기록과 같고 스캔 상태가 정상',
    'R2': '분석 대상 종목(유니버스) 안',
    'R3': '보고서 날짜가 지정 기간 안',
    'R4': '표의 과거 실적 열이 공시 원문 값과 일치(단위·열 위치 확정)',
    'R5': '값이 상식 범위(매출 > 0, |영업이익| < 매출)',
    'R6': '전망 연도가 보고서 연도 ~ +3년',
    'R7': "행 이름이 정확히 '매출액'(또는 '순매출액')·'영업이익' (조정영업이익 등은 사람 확인)",
    'R8': '보고서 안 다른 표(공시와 맞는 표)와 같은 연도 값이 1% 넘게 다르지 않음',
}


def data_dir():
    return Path(os.environ.get('MODU_NODES_DATA_DIR') or ROOT / 'data')


def store():
    from .store import Store
    return Store(str(data_dir()))


def universe_tickers():
    from .market import universe
    return {c['ticker'] for c in universe()['companies']}


# ---------------------------------------------------------------- 1. 등록
def load_meta():
    p = broker.inbox_dir() / '_bulk_meta.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'files': {}}


def register_bulk(meta, tickers, lo, hi):
    """받은 보고서함의 PDF 중 일괄 수집 기록(_bulk_meta.json)에 있는 것을 등록한다. 이미 등록된 것(같은 해시)은 건너뛴다."""
    out = {'registered': 0, 'already': 0, 'skipped': 0, 'errors': []}
    for fname, m in sorted(meta.get('files', {}).items()):
        if not (broker.inbox_dir() / fname).exists():
            continue
        if m.get('ticker') not in tickers or not (lo <= (m.get('date') or '') <= hi):
            out['skipped'] += 1
            continue
        form = {'file': fname, 'ticker': m['ticker'], 'report_date': m['date'], 'broker': m['broker'], 'title': m.get('title', ''),
                'opinion': m.get('opinion', ''), 'target_price': m.get('target_price', ''), 'source_url': m.get('research_url', ''),
                'basis': '자동 등록(네이버페이증권 리서치 목록 · 종목코드/날짜/증권사는 목록 기준)'}
        try:
            broker.register(form)
            out['registered'] += 1
        except ValueError as e:
            if '이미 등록' in str(e):
                out['already'] += 1
            else:
                out['errors'].append({'file': fname, 'error': str(e)})
    return out


# ---------------------------------------------------------------- 2. 스캔
def corpus_facts():
    """앱의 facts_for(실행 없음)와 같은 저장 공식 원문 대조값 + 모든 회사의 공시 API 연간 값."""
    facts = {}
    try:
        from .nodes import _fact
        from .official import load_corpus
        for comp in load_corpus()['companies']:
            doc = comp['documents'][0]
            for y in comp['years']:
                for m in y['inputs']:
                    f = _fact(comp, doc, y, m)
                    if f:
                        facts[f['fact_id']] = f          # 'ticker:연도:지표' — scan()이 찾는 키와 같다
    except Exception:
        pass
    return {**broker.filing_facts(exclude=()), **facts}   # 공식 원문이 있으면 그것을 우선


# ---------------------------------------------------------------- 3. 규칙
def judge(rep, cands, tickers, lo, hi):
    """보고서 하나가 자동 승인 규칙 v1을 통과하는지. (통과 여부, 못 맞춘 규칙 목록)"""
    miss = []
    if rep.get('status') != 'ok' or rep.get('manifest_sha_match') is not True:
        miss.append('R1')
    if rep.get('ticker') not in tickers:
        miss.append('R2')
    d = str(rep.get('report_date') or '')
    d = f'{d[:4]}-{d[4:6]}-{d[6:8]}' if re.fullmatch(r'\d{8}', d) else d
    if not (lo <= d <= hi):
        miss.append('R3')
    if rep.get('past_check') != 'match':
        miss.append('R4')
    by_fy = {}
    for c in cands:
        by_fy.setdefault(c['fiscal_year'], {})[c['metric']] = Decimal(c['value_mn'])
    if not cands or any(('revenue' in v and v['revenue'] <= 0) or
                        ('revenue' in v and 'operatingProfit' in v and abs(v['operatingProfit']) >= v['revenue'])
                        for v in by_fy.values()):
        miss.append('R5')
    if rep.get('label_exact') is False:
        miss.append('R7')
    if rep.get('internal_mismatch'):
        miss.append('R8')
    try:
        ry = int(d[:4])
        if any(not (ry <= int(fy) <= ry + 3) for fy in by_fy):
            miss.append('R6')
    except ValueError:
        miss.append('R6')
    return not miss, miss


def _snapshot(st):
    with st.connect() as db:
        return {r['id']: dict(r) for r in db.execute('SELECT id, file, state, reviewer, data FROM broker_candidates')}


def run(lo, hi, sample_n=30, seed=None, do_register=True, dry_run=False):
    out = data_dir() / 'broker_auto' / (datetime.now(KST).strftime('%Y%m%dT%H%M%S') + ('_dryrun' if dry_run else ''))
    out.mkdir(parents=True, exist_ok=True)
    if dry_run:                                   # 실제 DB를 복사해 거기서만 돌린다
        import shutil
        from .store import Store
        shutil.copy2(data_dir() / 'nodes.sqlite', out / 'nodes.sqlite')
        st = Store(str(out))
        do_register = False
    else:
        st = store()
    before = _snapshot(st)
    tickers = universe_tickers()
    reg = register_bulk(load_meta(), tickers, lo, hi) if do_register else {}
    reports, cands = broker.scan(corpus_facts())
    up = st.broker_upsert(RULE, reports, cands)
    _, stored = st.broker_reports()
    by_file = {}
    for c in stored:
        by_file.setdefault(c['file'], []).append(c)
    rows, approved_ids = [], []
    for rep in reports:
        cs = [c for c in by_file.get(rep['file'], []) if c['state'] != 'stale']
        ok, miss = judge(rep, cs, tickers, lo, hi)
        n = 0
        if not ok:                                # 이전 자동 승인(v1)이 v2를 못 넘으면 '제안'으로 되돌린다. 사람 결정은 그대로.
            with st.connect() as db:
                prev = [r['id'] for r in db.execute("SELECT id FROM broker_candidates WHERE file=? AND state='approved' AND reviewer LIKE ?",
                                                    (rep['file'], AUTO_PREFIX + '%'))]
            for i in prev:
                st.broker_review(RULE, i, 'reset', note='자동 승인 규칙 v2 미충족: ' + ','.join(miss))
        if ok:
            for c in cs:
                if c['state'] == 'proposed':
                    st.broker_review(RULE, c['id'], 'approve', note='자동 승인 규칙 v1: ' + ' · '.join(RULE_TEXT.values()))
                    approved_ids.append(c['id'])
                    n += 1
        rows.append({'file': rep['file'], 'ticker': rep.get('ticker') or '', 'broker': rep.get('broker', ''), 'report_date': rep.get('report_date', ''),
                     'status': rep.get('status', ''), 'past_check': rep.get('past_check', ''), 'decision': 'auto' if ok else 'human',
                     'missed_rules': ','.join(miss), 'auto_approved_now': n, 'candidates': len(cs)})
    after = _snapshot(st)
    changes = []
    for cid in sorted(set(before) | set(after)):
        b0, a0 = before.get(cid), after.get(cid)
        vb = json.loads(b0['data'])['value_mn'] if b0 else ''
        va = json.loads(a0['data'])['value_mn'] if a0 else ''
        sb, sa = (b0 or {}).get('state', '(없음)'), (a0 or {}).get('state', '(없음)')
        if vb != va or sb != sa:
            d = json.loads((a0 or b0)['data'])
            changes.append({'file': (a0 or b0)['file'], 'id': cid, 'metric': d.get('metric_label', ''), 'year': d.get('year_label', ''),
                            'value_before': vb, 'value_after': va, 'state_before': sb, 'state_after': sa,
                            'reviewer_before': (b0 or {}).get('reviewer') or '', 'reviewer_after': (a0 or {}).get('reviewer') or '',
                            'row_label': d.get('row_label', ''), 'human_decision_affected': bool(b0 and b0.get('reviewer') and not str(b0['reviewer']).startswith(AUTO_PREFIX) and sb != sa)})
    with open(out / 'changes.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(changes[0]) if changes else ['file'])
        w.writeheader(); w.writerows(changes)
    with open(out / 'reports.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ['file'])
        w.writeheader(); w.writerows(rows)
    with st.connect() as db:                                   # 이번 실행 + 이전 실행에서 자동 승인된 것 전체가 표본 모집단
        auto_ids = {r['id'] for r in db.execute("SELECT id FROM broker_candidates WHERE reviewer LIKE ? AND state='approved'", (AUTO_PREFIX + '%',))}
    pool = [c for c in stored if c['id'] in auto_ids]
    rnd = random.Random(seed if seed is not None else 20261108)
    sample = rnd.sample(pool, min(sample_n, len(pool)))
    with open(out / 'sample30.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['번호', '파일', '증권사', '보고서일', '지표', '연도', '원문 표기', '원문 단위', '환산값(백만원)', '쪽', '인용', '대조 결과(맞음/틀림)', '틀린 이유'])
        for i, c in enumerate(sample, 1):
            w.writerow([i, c['file'], c['broker'], c['report_date'], c['metric_label'], c['year_label'], c['value_original'], c['unit_original'],
                        c['value_mn'], c['page'], c['quote'], '', ''])
    miss_count = {}
    for r in rows:
        for m in filter(None, r['missed_rules'].split(',')):
            miss_count[m] = miss_count.get(m, 0) + 1
    summary = {'rule': RULE, 'rules': RULE_TEXT, 'window': [lo, hi], 'universe': len(tickers), 'register': reg, 'scan': up,
               'reports': len(rows), 'auto_reports': sum(r['decision'] == 'auto' for r in rows),
               'human_reports': sum(r['decision'] == 'human' for r in rows), 'missed_rule_counts': miss_count,
               'auto_approved_candidates_now': len(approved_ids), 'auto_approved_candidates_total': len(pool), 'sample': len(sample), 'out': str(out),
               'dry_run': dry_run, 'extractor': broker.EXTRACTOR,
               'changes': {'total': len(changes), 'value_changed': sum(c['value_before'] != c['value_after'] for c in changes),
                           'approved_to_proposed': sum(c['state_before'] == 'approved' and c['state_after'] == 'proposed' for c in changes),
                           'proposed_to_approved': sum(c['state_before'] in ('proposed', '(없음)') and c['state_after'] == 'approved' for c in changes),
                           'human_decisions_affected': sum(c['human_decision_affected'] for c in changes)},
               'next': 'sample30.csv의 각 줄을 PDF 원문과 대조해 「대조 결과」를 채우세요. 틀림이 2건(약 7%) 이하면 그대로 사용, 넘으면 revert 후 규칙 보완.'}
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding='utf-8')
    return summary


def revert():
    st = store()
    with st.connect() as c:
        ids = [r['id'] for r in c.execute("SELECT id FROM broker_candidates WHERE reviewer LIKE ? AND state='approved'", (AUTO_PREFIX + '%',))]
    for i in ids:
        st.broker_review(RULE, i, 'reset', note='자동 승인 되돌림')
    return {'reverted': len(ids)}


def status():
    st = store()
    with st.connect() as c:
        rows = c.execute("SELECT state, CASE WHEN reviewer LIKE ? THEN 'auto' WHEN reviewer IS NULL THEN '-' ELSE 'human' END who, COUNT(*) n "
                         "FROM broker_candidates GROUP BY state, who ORDER BY state, who", (AUTO_PREFIX + '%',)).fetchall()
    return [dict(r) for r in rows]


def rename(apply=False):
    """보관 파일 이름에 회사명 넣기. apply=False면 계획(rename_plan.csv)만. 파일은 지우지 않고 이름만 바꾸며 manifest를 함께 고친다."""
    import shutil
    from .market import company_name
    d = broker.broker_dir()
    man = broker._manifest_raw(d)
    plan, names = [], {f['파일명'] for f in man.get('files', [])}
    for f in man.get('files', []):
        t = broker.report_ticker(f)
        if not t or not f.get('sha256') or not (d / f['파일명']).exists():
            plan.append({'old': f['파일명'], 'new': '', 'reason': '종목코드·해시·파일 중 없음 — 그대로 둠'}); continue
        try:
            nm = company_name(t)
        except Exception:
            nm = t
        new = broker.report_filename(f['보고서일'], t, nm, f.get('증권사', ''), f['sha256'])
        if new == f['파일명']:
            continue
        if new in names or (d / new).exists():
            plan.append({'old': f['파일명'], 'new': '', 'reason': f'같은 이름 {new}이 이미 있음 — 그대로 둠'}); continue
        names.add(new)
        plan.append({'old': f['파일명'], 'new': new, 'reason': ''})
    out = data_dir() / 'broker_auto' / ('rename_' + datetime.now(KST).strftime('%Y%m%dT%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)
    with open(out / 'rename_plan.csv', 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.DictWriter(fh, fieldnames=['old', 'new', 'reason']); w.writeheader(); w.writerows(plan)
    todo = [p for p in plan if p['new']]
    res = {'planned': len(todo), 'kept': len(plan) - len(todo), 'plan': str(out / 'rename_plan.csv'), 'applied': False}
    if not apply:
        return res
    mp = d / 'manifest.json'
    shutil.copy2(mp, out / 'manifest.json.before-rename')
    by_old = {p['old']: p['new'] for p in todo}
    done = 0
    for f in man['files']:
        new = by_old.get(f['파일명'])
        if not new:
            continue
        (d / f['파일명']).rename(d / new)
        f['이전 파일명'] = f['파일명']
        f['파일명'] = new
        done += 1
    tmp = d / 'manifest.json.tmp'
    tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(mp)
    res.update(applied=True, renamed=done, manifest_backup=str(out / 'manifest.json.before-rename'),
               next='앱의 「PDF 다시 스캔」(또는 run --no-register)으로 새 이름을 반영하세요. 승인은 파일 해시 기준이라 유지됩니다.')
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m mrn.broker_auto')
    sub = ap.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('run')
    r.add_argument('--from', dest='lo', required=True)
    r.add_argument('--to', dest='hi', required=True)
    r.add_argument('--sample', type=int, default=30)
    r.add_argument('--no-register', action='store_true')
    r.add_argument('--dry-run', action='store_true')
    rn = sub.add_parser('rename')
    rn.add_argument('--apply', action='store_true')
    sub.add_parser('revert')
    sub.add_parser('status')
    a = ap.parse_args(argv)
    if a.cmd == 'run':
        res = run(a.lo, a.hi, a.sample, do_register=not a.no_register, dry_run=a.dry_run)
    elif a.cmd == 'rename':
        res = rename(a.apply)
    elif a.cmd == 'revert':
        res = revert()
    else:
        res = status()
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
