"""v0.29: 네이버 데이터랩 검색어 트렌드 — 과거 검색량 소급 (네티즌 반응-주가 프레임워크 T2). AI 모델 호출 0회.

받기 (PC에서: _tools\\datalab\\run-datalab.cmd → python -m mrn.datalab fetch)
- 키는 환경 변수에서만 읽는다(local-env.cmd). 화면·로그·저장 파일에 남기지 않는다.
  · 새 키(NAVER API HUB, 네이버 클라우드 콘솔에서 발급): NAVER_HUB_ID / NAVER_HUB_SECRET → https://naverapihub.apigw.ntruss.com/search-trend/v1/search
  · 옛 키(개발자센터, 2026-07-31 이전 발급분만, 2027-06-30까지): NAVER_CLIENT_ID / NAVER_CLIENT_SECRET → https://openapi.naver.com/v1/datalab/search
- 회사마다 요청 1번: 검색어 묶음 = 「회사명 주가」 · 「회사명주가」 · 종목코드 (투자자 검색만 잡으려고 「주가」를 붙임). timeUnit=date.
- 결과는 _sources\\datalab\\<받은 시각>\\ 에 회사별 jsonl + manifest.json + manifest.sha256 + LATEST.txt. 원 응답 해시도 남긴다.
- 중간에 끊겨도 다시 실행하면 이어서 받는다(같은 폴더의 progress). 하루·달 호출 한도에 걸리면 멈추고 알려 준다.

읽기·가공 (앱)
- 데이터랩 값은 「요청 안의 최댓값 = 100」 상대값이라 회사끼리 크기를 비교하지 않는다. 회사 자신의 평소 대비 로그 차이(ASVI)만 쓴다.
  로그 차이에서는 요청마다 다른 기준값이 상쇄되므로, 미래의 최댓값이 과거 배수를 바꾸지 않는다.
- 거래일 t 의 검색량 = 직전 거래일 다음 날 ~ t 까지 달력일 값의 평균(주말·휴일 검색을 다음 거래일에 넣음).
- 평소 = 그날 이전 40거래일 중앙값(최소 20일). 시장 감안 = 같은 날 모든 회사 ASVI 중앙값을 뺌.
- 0이 너무 많은 회사(30% 넘게 0)는 검색이 적어 보류.
- 데이터랩 하루 값이 언제 공개되는지 확인되지 않아, 예측 관계는 엄격하게 「다다음 거래일」로 판정하고 「다음 거래일」은 참고로만 보인다.
"""
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUB_URL = 'https://naverapihub.apigw.ntruss.com/search-trend/v1/search'
LEGACY_URL = 'https://openapi.naver.com/v1/datalab/search'
DEFAULT_FROM = '2023-01-02'
ZERO_MAX = 0.30
BASE_MIN, BASE_MAX = 20, 40


class DatalabError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def datalab_dir():
    return Path(os.environ.get('MODU_NODES_DATALAB_DIR') or ROOT.parent / '_sources' / 'datalab')


def _sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- 받기
def credentials(env=None):
    """(방식, url, 헤더). 값은 돌려주되 어디에도 적지 않는다. 키가 없으면 DatalabError."""
    env = env if env is not None else os.environ
    if env.get('NAVER_HUB_ID') and env.get('NAVER_HUB_SECRET'):
        return 'hub', HUB_URL, {'X-NCP-APIGW-API-KEY-ID': env['NAVER_HUB_ID'], 'X-NCP-APIGW-API-KEY': env['NAVER_HUB_SECRET'], 'Content-Type': 'application/json'}
    if env.get('NAVER_CLIENT_ID') and env.get('NAVER_CLIENT_SECRET'):
        return 'legacy', LEGACY_URL, {'X-Naver-Client-Id': env['NAVER_CLIENT_ID'], 'X-Naver-Client-Secret': env['NAVER_CLIENT_SECRET'], 'Content-Type': 'application/json'}
    raise DatalabError('no_key', '데이터랩 키가 없습니다. local-env.cmd 에 NAVER_HUB_ID·NAVER_HUB_SECRET(새 키) 또는 NAVER_CLIENT_ID·NAVER_CLIENT_SECRET(옛 키)을 넣어 주세요.')


def keywords(name, ticker):
    n = (name or '').strip()
    return [f'{n} 주가', f'{n}주가', ticker] if n else [ticker]


def body(name, ticker, start, end):
    return {'startDate': start, 'endDate': end, 'timeUnit': 'date', 'keywordGroups': [{'groupName': ticker, 'keywords': keywords(name, ticker)}]}


def http_post(url, headers, payload, timeout=30):
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def parse(raw):
    """응답 → [(날짜, ratio)]. ratio 는 요청 안 최댓값 100 기준 상대값. 빠진 날은 0으로 채우지 않는다(그대로 비움)."""
    j = json.loads(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    res = j.get('results') or []
    if not res:
        return []
    return [(str(x['period'])[:10], float(x['ratio'])) for x in res[0].get('data') or []]


def fetch(companies, out_root=None, start=DEFAULT_FROM, end=None, post=http_post, env=None, sleep=0.12, log=print):
    """companies: [(ticker, name)]. 이어받기를 지원한다. 끝나면 manifest 를 쓰고 LATEST 를 바꾼다. 돌려줌: 스냅숏 폴더."""
    mode, url, headers = credentials(env)
    end = end or (date.today() - timedelta(days=1)).isoformat()
    root = Path(out_root or datalab_dir())
    root.mkdir(parents=True, exist_ok=True)
    work = root / '_in_progress'
    work.mkdir(exist_ok=True)
    meta_p = work / 'progress.json'
    meta = json.loads(meta_p.read_text(encoding='utf-8')) if meta_p.exists() else {'start': start, 'end': end, 'done': {}, 'failed': {}, 'mode': mode,
                                                                                 'started_at': datetime.now(timezone.utc).isoformat()}
    if (meta['start'], meta['end']) != (start, end):
        raise DatalabError('progress_mismatch', f"받던 중인 기간({meta['start']}~{meta['end']})과 달라요. _in_progress 폴더를 지우거나 같은 기간으로 다시 실행하세요.")
    for i, (t, nm) in enumerate(companies):
        if t in meta['done']:
            continue
        payload = body(nm, t, start, end)
        st, raw = post(url, headers, payload)
        if st == 429:
            meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            raise DatalabError('quota', f'호출 한도에 걸렸어요({i}/{len(companies)}까지 받음). 한도가 풀린 뒤 다시 실행하면 이어서 받아요.')
        if st in (401, 403):
            raise DatalabError('auth', f'키가 거절됐어요(HTTP {st}). {mode} 방식 키·검색어 트렌드 사용 설정을 확인해 주세요.')
        if st != 200:
            meta['failed'][t] = f'HTTP {st}'
            log(f'  {t} {nm}: 실패 HTTP {st}')
            continue
        rows = parse(raw)
        recs = [{'ticker': t, 'name': nm, 'date': d, 'ratio': r} for d, r in rows]
        p = work / f'{t}.jsonl'
        p.write_text(''.join(json.dumps(x, ensure_ascii=False, sort_keys=True) + '\n' for x in recs), encoding='utf-8', newline='\n')
        meta['done'][t] = {'rows': len(recs), 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'keywords': keywords(nm, t)}
        meta_p.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
        log(f'  [{len(meta["done"])}/{len(companies)}] {t} {nm}: {len(recs)}일')
        time.sleep(sleep)
    stamp = datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%dT%H%M%S+0900')
    snap = root / stamp
    snap.mkdir()
    parts, total = {}, 0
    for t, info in meta['done'].items():
        src = work / f'{t}.jsonl'
        dst = snap / 'search' / f'{t}.jsonl'
        dst.parent.mkdir(exist_ok=True)
        dst.write_bytes(src.read_bytes())
        parts[t] = {'file': f'search/{t}.jsonl', 'rows': info['rows'], 'sha256': _sha(dst), 'raw_sha256': info['raw_sha256'], 'keywords': info['keywords']}
        total += info['rows']
    man = {'tool': 'mrn.datalab', 'tool_version': 1, 'mode': meta['mode'], 'start': start, 'end': end, 'fetched_at': datetime.now(timezone.utc).isoformat(),
           'time_unit': 'date', 'value': 'ratio (요청 안 최댓값 100 기준 상대값, 회사마다 따로 요청)', 'failed': meta['failed'],
           'tables': {'search': {'partitioned': True, 'parts': parts, 'rows': total, 'source_grade': 'official_api:naver_datalab'}}}
    mp = snap / 'manifest.json'
    mp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    (snap / 'manifest.sha256').write_text(_sha(mp) + '  manifest.json\n', encoding='utf-8')
    (root / 'LATEST.txt').write_text(stamp + '\n', encoding='utf-8')
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    log(f'끝: {len(parts)}개 회사, {total:,}행 → {snap}')
    return snap


# ---------------------------------------------------------------- 읽기
def resolve(snapshot=''):
    d = datalab_dir()
    name = (snapshot or '').strip()
    if not name or name == 'latest':
        lp = d / 'LATEST.txt'
        if not lp.exists():
            return None
        name = lp.read_text(encoding='utf-8').strip()
    root = d / name
    return root if (root / 'manifest.json').exists() else None


def load(snapshot=''):
    """→ (manifest, {ticker: {date: ratio}}) 또는 (None, {}). 해시가 다르면 DatalabError(쓰지 않음)."""
    root = resolve(snapshot)
    if root is None:
        return None, {}
    mp = root / 'manifest.json'
    want = (root / 'manifest.sha256').read_text(encoding='utf-8').split()[0]
    if _sha(mp) != want:
        raise DatalabError('manifest_changed', '데이터랩 사본 목록의 해시가 기록과 달라요. 쓰지 않습니다.')
    man = json.loads(mp.read_text(encoding='utf-8'))
    man['_manifest_sha256'] = want
    man['_snapshot'] = root.name
    out = {}
    for t, part in man['tables']['search']['parts'].items():
        p = root / part['file']
        if _sha(p) != part['sha256']:
            raise DatalabError('table_changed', f'데이터랩 {t} 파일의 해시가 목록과 달라요. 쓰지 않습니다.')
        out[t] = {r['date']: float(r['ratio']) for r in map(json.loads, p.read_text(encoding='utf-8').splitlines()) if r.get('date')}
    return man, out


def by_trading_day(series, cal, last):
    """{달력일: ratio} → {거래일: 평균 ratio}. 거래일 t = 직전 거래일 다음 날 ~ t. last 뒤 날짜는 쓰지 않는다."""
    out = {}
    days = sorted(d for d in series if d <= last)
    if not days:
        return out
    import bisect
    acc = {}
    for d in days:
        i = bisect.bisect_left(cal, d)
        if i >= len(cal):
            continue
        acc.setdefault(cal[i], []).append(series[d])
    return {t: sum(v) / len(v) for t, v in acc.items()}


def asvi(att):
    """{거래일: 검색량} → {거래일: ln(오늘) − ln(이전 40거래일 중앙값)}. 이전 기록 20일 미만이면 비움. 0은 최솟값의 절반으로 대신."""
    ds = sorted(att)
    pos = [v for v in att.values() if v > 0]
    if not pos:
        return {}
    eps = min(pos) / 2
    out = {}
    import bisect
    win = []                                        # 직전 BASE_MAX 거래일 값(정렬 유지) — 이동 중앙값
    for k, d in enumerate(ds):
        n = len(win)
        if n >= BASE_MIN:
            med = win[n // 2] if n % 2 else (win[n // 2 - 1] + win[n // 2]) / 2
            out[d] = math.log(max(att[d], eps)) - math.log(max(med, eps))
        bisect.insort(win, att[d])
        if len(win) > BASE_MAX:
            win.pop(bisect.bisect_left(win, att[ds[k - BASE_MAX]]))
    return out


def zero_share(series):
    v = list(series.values())
    return sum(1 for x in v if x <= 0) / len(v) if v else 1.0


# ---------------------------------------------------------------- 명령줄
def _companies_from_neon():
    from .market import companies, load_manifest, resolve as nres
    root = nres('')
    man = load_manifest(root)
    cos = companies(root, man)
    return [(t, c.get('name') or t) for t, c in sorted(cos.items()) if c.get('market') in (None, 'KR') and len(t) == 6 and t.isdigit()]


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog='python -m mrn.datalab')
    sub = ap.add_subparsers(dest='cmd', required=True)
    f = sub.add_parser('fetch', help='데이터랩 검색어 트렌드 받기')
    f.add_argument('--from', dest='start', default=DEFAULT_FROM)
    f.add_argument('--to', dest='end', default=None)
    f.add_argument('--only', default='', help='쉼표로 구분한 종목코드만')
    sub.add_parser('status', help='받아 둔 사본 확인')
    a = ap.parse_args(argv)
    if a.cmd == 'status':
        man, data = load()
        if not man:
            print('받아 둔 데이터랩 사본이 없어요.')
            return 0
        print(f"사본 {man['_snapshot']} · {man['start']}~{man['end']} · 회사 {len(data)}곳 · 방식 {man['mode']} · 실패 {len(man.get('failed') or {})}곳")
        return 0
    cos = _companies_from_neon()
    if a.only:
        keep = set(a.only.split(','))
        cos = [c for c in cos if c[0] in keep]
    print(f'데이터랩 검색어 트렌드 받기: {len(cos)}개 회사, {a.start} ~ {a.end or "어제"} (회사마다 요청 1번)')
    try:
        fetch(cos, start=a.start, end=a.end)
    except DatalabError as e:
        print('멈춤:', e)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
