"""v0.38 T2-3 시험용 표본 받기 — 사본(230개사) 밖 상장사의 실제 공시 원문을 「검증용으로만」 받는다. AI 모델 호출 0회.

왜: 감자(병합·액면 감액·유상)·전환사채(리픽싱)처럼 사본 안에 실례가 없거나 적은 종류는, 실제 원문 없이 계산을 만들면 검증할 수 없다.
- 근거 사본(_sources\\dart_docs)과 섞지 않는다: 따로 _sources\\dart_docs_samples 에 같은 형식(받은 그대로 + manifest 해시)으로 둔다.
  엔진의 답·확인서는 이 폴더를 읽지 않는다(시험과 양식 조사만 읽는다).
- 받는 법: 회사를 정하지 않고 기간(석 달씩)으로 공시 목록을 훑어, 종류 이름이 맞는 상장사(유가·코스닥) 공시만 받는다. 자회사·종속회사 공시는 뺀다.
- 키는 환경 변수에서만 읽고 어디에도 남기지 않는다(dartdocs와 같음). 다시 실행하면 받은 것은 건너뛴다.
쓰는 법: python -m mrn.dartsamples fetch --kinds capital_reduction --from 2025-01-01 [--limit 300]
"""
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import dartdocs as D

WINDOW_DAYS = 85                      # 회사를 정하지 않은 목록 조회는 석 달까지


def samples_dir():
    import os
    return Path(os.environ.get('MODU_NODES_DART_SAMPLES') or D.ROOT.parent / '_sources' / 'dart_docs_samples')


def windows(start, end):
    a, e = date.fromisoformat(start), date.fromisoformat(end)
    while a <= e:
        b = min(a + timedelta(days=WINDOW_DAYS), e)
        yield a.isoformat(), b.isoformat()
        a = b + timedelta(days=1)


def fetch(kinds, start, end=None, out_root=None, get=D.http_get, env=None, sleep=0.25, log=print, limit=None, skip_tickers=()):
    key = D.api_key(env)
    if not key:
        raise D.DartDocsError('no_key', 'DART 키가 없습니다. modu-research-nodes\\local-env.cmd 에 DART_API_KEY 를 넣어 주세요.')
    for k in kinds:
        if k not in D.KINDS:
            raise D.DartDocsError('bad_kind', f'{k}: 받는 종류 이름이 아닙니다({", ".join(D.KINDS)}).')
    end = end or datetime.now().date().isoformat()
    root = Path(out_root or samples_dir()); root.mkdir(parents=True, exist_ok=True)
    try:
        man = {k: v for k, v in D.load_manifest(root).items() if not k.startswith('_')}
    except D.DartDocsError as e:
        if e.code != 'no_docs':
            raise
        man = {'tool': 'mrn.dartsamples', 'tool_version': 1, 'origin': '금융감독원 OpenDART document.xml (받은 그대로, 고치지 않음) — 시험용 표본, 근거 사본 아님',
               'docs': {}, 'listed': {}, 'failed': {}}
    got = 0
    try:
        for a, b in windows(start, end):
            want = []
            pages = [0]

            def get_list(url, _g=get, _p=pages, _a=a, _b=b):          # 목록을 읽는 동안에도 살아 있음을 보이기(20쪽마다 한 줄) — 주소는 찍지 않음
                _p[0] += 1
                if _p[0] == 1 or _p[0] % 20 == 0:
                    log(f'  {_a} ~ {_b}: 공시 목록 읽는 중 … {_p[0]}쪽째')
                return _g(url)
            for ty in sorted({D.KINDS[k][0] for k in kinds}):
                for r in D.list_filings(key, None, ty, a, b, get_list):
                    k = D.classify(r.get('report_nm'))
                    if k in kinds and r.get('corp_cls') in ('Y', 'K') and (r.get('stock_code') or '').strip() and r['stock_code'].strip() not in skip_tickers:
                        want.append((r, k))
                time.sleep(sleep)
            new = 0
            for r, k in sorted(want, key=lambda x: x[0]['rcept_no']):
                no = r['rcept_no']
                if no in man['docs'] and (root / man['docs'][no]['file']).exists():
                    continue
                if limit is not None and got >= limit:
                    break
                try:
                    body, members = D.fetch_doc(key, no, get)
                except D.DartDocsError as e:
                    if e.code in ('dart_020', 'dart_010', 'dart_011', 'dart_012', 'network'):
                        raise
                    man['failed'][no] = {'ticker': r.get('stock_code'), 'report_nm': r.get('report_nm'), 'code': e.code, 'reason': str(e)}; continue
                (root / f'{no}.zip').write_bytes(body)
                dt = r['rcept_dt']
                man['docs'][no] = {'ticker': r['stock_code'].strip(), 'corp_code': r.get('corp_code'), 'name': r.get('corp_name'), 'market': r.get('corp_cls'),
                                   'report_nm': ' '.join((r.get('report_nm') or '').split()), 'rcept_dt': f'{dt[:4]}-{dt[4:6]}-{dt[6:8]}', 'kind': k, 'filer': r.get('flr_nm'),
                                   'remark': r.get('rm') or '', 'file': f'{no}.zip', 'bytes': len(body), 'sha256': D._sha(body), 'members': members,
                                   'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}', 'added_by': 'sample'}
                man['failed'].pop(no, None); got += 1; new += 1
                if new % 10 == 0:
                    log(f'  {a} ~ {b}: 원문 받는 중 … {new}건')
                if got % 20 == 0:
                    D._save_manifest(root, man)
                time.sleep(sleep)
            log(f'  {a} ~ {b}: 대상 {len(want)}건 · 새로 받음 {new}건')
            if limit is not None and got >= limit:
                log(f'  이번 실행 한도({limit}건)에 닿아 멈춤 — 다시 실행하면 이어서 받습니다.'); break
    finally:
        D._save_manifest(root, man)
    return got


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='python -m mrn.dartsamples')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch'); f.add_argument('--kinds', required=True); f.add_argument('--from', dest='start', required=True); f.add_argument('--to', dest='end', default=None)
    f.add_argument('--limit', type=int, default=None)
    g = sub.add_parser('fetch-snapshot', help='엔진 시세 사본에 있는 회사만, 회사마다 목록을 훑어 받는다(기간 제한 없음)')
    g.add_argument('--kinds', required=True); g.add_argument('--from', dest='start', required=True); g.add_argument('--to', dest='end', default=None)
    g.add_argument('--limit', type=int, default=None)
    sub.add_parser('status'); sub.add_parser('verify')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'fetch':
            kinds = [k.strip() for k in a.kinds.split(',') if k.strip()]
            print(f'시험용 표본 받기: 종류 {kinds}, {a.start} ~ {a.end or "오늘"} (상장사 전체, 자회사 공시 제외)')
            print(f'새로 받은 원문 {fetch(kinds, a.start, a.end, limit=a.limit, get=D.metered_get())}건.')
        if a.cmd == 'fetch-snapshot':                                   # v0.38 T2-4b
            kinds = [k.strip() for k in a.kinds.split(',') if k.strip()]
            for k in kinds:
                if k not in D.KINDS:
                    raise D.DartDocsError('bad_kind', f'{k}: 받는 종류 이름이 아닙니다({", ".join(D.KINDS)}).')
            cos = D._companies()
            print(f'시험용 표본 받기: 종류 {kinds}, {a.start} ~ {a.end or "오늘"} (엔진 시세 사본의 국내 회사 {len(cos)}곳, 회사마다 목록을 훑음)')
            print(f'새로 받은 원문 {D.fetch(cos, kinds, a.start, a.end, out_root=samples_dir(), limit=a.limit, get=D.metered_get())}건.')
        if a.cmd in ('fetch', 'fetch-snapshot', 'status'):
            s = D.status(samples_dir())
            print(f"표본: 원문 {s['docs']}건 · 회사 {s['companies']}곳 · {s['bytes'] / 1e6:,.1f}MB · 받지 못한 것 {s['failed']}건")
            for k, v in s['by_kind'].items():
                print(f"  {v['label']}: {v['docs']}건 ({v['companies']}곳)")
        if a.cmd in ('fetch', 'fetch-snapshot', 'verify'):
            v = D.verify_all(samples_dir()); print(f"해시 대조: {v['checked']}건 중 다른 것 {len(v['bad'])}건")
    except D.DartDocsError as e:
        print(f'멈춤: {e}'); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
