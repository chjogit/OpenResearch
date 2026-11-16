"""가격 사본 갱신 (PM 결정 2026-11-15, 연구용 · 재배포 계약 전).
최신 가격 사본(Neon 공용 DB의 금융위 시세)에 한국투자증권(KIS) 일별 시세로 빈 날을 채운 「새 사본」을 만든다.

지키는 것
- 원래 사본은 건드리지 않는다. 새 사본 폴더를 만든 뒤 마지막에 LATEST.txt 만 바꾼다(되돌리기 = LATEST.txt 를 예전 이름으로).
- 회사마다 KIS 일별 시세(원주가 — 금융위와 같은 기준)를 받아, 먼저 「이미 있는 최근 5거래일 종가」와 원 단위까지 같은지 대조한다.
  하나라도 다르면 그 회사는 채우지 않는다. 대조에 실패한 회사가 20%를 넘으면 아무것도 바꾸지 않는다(응답 형식이 바뀌었을 수 있음).
- 채운 행은 source='kis'. 시가총액 = 마지막 행의 (시가총액 ÷ 종가) × 새 종가(그 사이 주식 수가 같다는 가정).
- 코스피·코스닥 지수(^KS11·^KQ11)도 같은 방식(겹치는 날 차이 0.1% 안이어야 채움).
- 새 파일·목록은 sha256 을 새로 적고(manifest.json · manifest.sha256), 엔진은 늘 하던 대로 해시를 대조해 읽는다.
- 키는 엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET(환경 변수)만. 키 값은 화면·파일·기록 어디에도 쓰지 않는다.
쓰는 법: (엔진 가상환경 python) price_refresh.py [--dry] [--auto]
  --dry  : 받아서 대조만 하고 아무것도 쓰지 않음      --auto : 이미 최신이면 KIS를 부르지 않고 끝냄(시연 켜기에서 씀)"""
import copy, hashlib, json, os, shutil, sys, time, urllib.parse
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ENGINE = ROOT / 'modu-research-nodes'
sys.path.insert(0, str(ENGINE))
from mrn import market as M, surge as SG   # noqa: E402

KST = timezone(timedelta(hours=9))
OVERLAP = 5
FAIL_RATIO = 0.20
INDEX = {'^KS11': ('0001', '코스피'), '^KQ11': ('1001', '코스닥')}
NOTE = ' + 한국투자증권 일별 시세(kis) 보충(연구용·재배포 계약 전)'
LOG = []


def say(s):
    LOG.append(s); print(s, flush=True)


def expected_last(now):
    d = now.date()
    if d.weekday() >= 5 or (now.hour, now.minute) < (16, 0):
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()   # 휴장일은 모름 → KIS가 그날 행을 안 주면 채울 것이 없을 뿐


def kis_get(kis, path, tr_id, params):
    """surge.Kis 의 토큰·간격·호출 수를 그대로 쓰고 output2(목록)를 받는다."""
    tok = kis.token()
    kis.sleep(SG.SPACING); kis._count()
    st, js = kis.http('GET', SG.SERVER + path + '?' + urllib.parse.urlencode(params),
                      {'authorization': 'Bearer ' + tok, 'appkey': kis.key, 'appsecret': kis.secret, 'tr_id': tr_id, 'custtype': 'P'}, None)
    if st != 200 or str((js or {}).get('rt_cd')) != '0':
        raise SG.KisError('kis_' + str((js or {}).get('msg_cd') or st), f"KIS 조회 실패(HTTP {st} {(js or {}).get('msg_cd', '')})")
    return js.get('output2') or []


def ymd(s):
    return s.replace('-', '')


def daily_stock(kis, t, start, end):
    out, hi = {}, end
    for _ in range(5):   # 한 번에 최대 100건 — 모자라면 앞으로 나눠 받음
        rows = kis_get(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice', 'FHKST03010100',
                       {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t, 'FID_INPUT_DATE_1': ymd(start), 'FID_INPUT_DATE_2': ymd(hi),
                        'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '1'})   # 1 = 원주가(금융위와 같은 기준)
        got = [r for r in rows if r.get('stck_bsop_date') and (r.get('stck_clpr') or '0') not in ('0', '')]
        for r in got:
            d = f"{r['stck_bsop_date'][:4]}-{r['stck_bsop_date'][4:6]}-{r['stck_bsop_date'][6:8]}"
            out[d] = r
        if len(rows) < 100 or not got:
            break
        oldest = min(out); hi = (datetime.fromisoformat(oldest) - timedelta(days=1)).date().isoformat()
        if hi < start:
            break
    return out


def daily_index(kis, code, start, end):
    rows = kis_get(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice', 'FHKUP03500100',
                   {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': code, 'FID_INPUT_DATE_1': ymd(start), 'FID_INPUT_DATE_2': ymd(end), 'FID_PERIOD_DIV_CODE': 'D'})
    out = {}
    for r in rows:
        if r.get('stck_bsop_date') and r.get('bstp_nmix_prpr'):
            d = r['stck_bsop_date']; out[f'{d[:4]}-{d[4:6]}-{d[6:8]}'] = r
    return out


def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def line(r):
    return json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n'


def plan_stock(t, rows, k, now_iso):
    """→ (새 행 목록, 문제) . rows = 사본의 이 회사 행(출처 무관, 날짜순)."""
    have = sorted(rows, key=lambda r: r['trade_date'])
    good = [r for r in have if r.get('source') in ('fsc', 'kis')]
    if not good:
        return [], '사본에 금융위 시세가 없음'
    tail = good[-OVERLAP:]
    both = [r for r in tail if r['trade_date'][:10] in k]
    if not both:
        return [], 'KIS 응답에 겹치는 날이 없어 대조할 수 없음'
    for r in both:
        if int(Decimal(str(r['close']))) != int(k[r['trade_date'][:10]]['stck_clpr']):
            return [], f"{r['trade_date'][:10]} 종가가 다름(사본 {r['close']} · KIS {k[r['trade_date'][:10]]['stck_clpr']})"
    last = good[-1]; lastd = last['trade_date'][:10]
    shares = None
    try:
        if last.get('market_cap') and Decimal(str(last['close'])):
            shares = Decimal(str(last['market_cap'])) / Decimal(str(last['close']))
    except Exception:
        shares = None
    new = []
    for d in sorted(x for x in k if x > lastd):
        r = k[d]; c = Decimal(r['stck_clpr'])
        vol = int(r.get('acml_vol') or 0)
        new.append({'ticker': t, 'trade_date': d, 'open': str(int(Decimal(r.get('stck_oprc') or c))), 'high': str(int(Decimal(r.get('stck_hgpr') or c))),
                    'low': str(int(Decimal(r.get('stck_lwpr') or c))), 'close': str(int(c)),
                    'volume': vol if isinstance(last.get('volume'), int) else str(vol), 'trade_value': str(int(Decimal(r.get('acml_tr_pbmn') or 0))),
                    'market_cap': str(int((shares * c).quantize(Decimal(1), rounding=ROUND_HALF_UP))) if shares is not None else None,
                    'source': 'kis', 'collected_at': now_iso})
    return new, None


def main(argv):
    dry, auto = '--dry' in argv, '--auto' in argv
    now = datetime.now(KST); now_iso = datetime.now(timezone.utc).isoformat()
    root = M.resolve(''); man = M.load_manifest(root)
    base = root.name; exp = expected_last(now)
    pd = man['tables']['price_daily']; parts = pd.get('parts') or {}
    say(f'기준 사본 {base} · 회사 {len(parts)}곳 · 채워야 할 마지막 거래일 {exp}')
    rows_of, stale = {}, []
    for t in sorted(parts):
        rows, _ = M.read_rows(root, man, 'price_daily', t)   # 해시·행 수 대조
        rows_of[t] = rows
        last = max((r['trade_date'][:10] for r in rows if r.get('source') in ('fsc', 'kis')), default='')
        if last and last < exp:
            stale.append(t)
    if auto and not stale:
        say('이미 최신이에요. KIS를 부르지 않고 끝냅니다.'); return 0
    cfg = SG.config()
    if not (cfg['key'] and cfg['secret']):
        say('KIS 키가 없어 갱신하지 않아요(엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'); return 2
    kis = SG.Kis(cfg['key'], cfg['secret'])
    add, fails = {}, {}
    for i, t in enumerate(stale, 1):
        good = sorted((r for r in rows_of[t] if r.get('source') in ('fsc', 'kis')), key=lambda r: r['trade_date'])
        start = good[-OVERLAP]['trade_date'][:10] if len(good) >= OVERLAP else good[0]['trade_date'][:10]
        try:
            k = daily_stock(kis, t, start, now.date().isoformat())
        except Exception as e:
            fails[t] = str(e)[:120]; continue
        new, why = plan_stock(t, rows_of[t], k, now_iso)
        if why:
            fails[t] = why
        elif new:
            add[t] = new
        if i % 50 == 0:
            say(f'  … {i}/{len(stale)}곳 확인')
    say(f'KIS 일별 시세: 확인 {len(stale)}곳 · 채울 회사 {len(add)}곳 · 행 {sum(map(len, add.values()))}개 · 대조 실패 {len(fails)}곳 · KIS 호출 {kis.calls}회')
    for t, why in list(fails.items())[:15]:
        say(f'  대조 실패 {t}: {why}')
    if stale and len(fails) / len(stale) > FAIL_RATIO:
        say(f'대조 실패가 {len(fails)}/{len(stale)}곳으로 20%를 넘어 아무것도 바꾸지 않았어요.'); return 3
    # 지수
    idx_rows, imeta = M.read_table(root, man, 'market_index_daily')
    idx_add, idx_note = [], []
    for sym, (code, name) in INDEX.items():
        mine = sorted((r for r in idx_rows if r['symbol'] == sym), key=lambda r: r['trade_date'])
        if not mine:
            continue
        lastd = mine[-1]['trade_date'][:10]
        if lastd >= exp:
            continue
        try:
            k = daily_index(kis, code, mine[-OVERLAP]['trade_date'][:10], now.date().isoformat())
        except Exception as e:
            idx_note.append(f'{name}: {str(e)[:80]}'); continue
        both = [r for r in mine[-OVERLAP:] if r['trade_date'][:10] in k]
        bad = [r for r in both if abs(Decimal(k[r['trade_date'][:10]]['bstp_nmix_prpr']) / Decimal(str(r['close'])) - 1) > Decimal('0.001')]
        if not both or bad:
            idx_note.append(f'{name}: 겹치는 날 값이 0.1% 넘게 달라 채우지 않음' if bad else f'{name}: 겹치는 날이 없어 채우지 않음'); continue
        for d in sorted(x for x in k if x > lastd):
            r = k[d]; c = r['bstp_nmix_prpr']
            idx_add.append({'symbol': sym, 'name': name, 'trade_date': d, 'open': r.get('bstp_nmix_oprc') or c, 'high': r.get('bstp_nmix_hgpr') or c,
                            'low': r.get('bstp_nmix_lwpr') or c, 'close': c, 'volume': int(r.get('acml_vol') or 0), 'source': 'kis', 'collected_at': now_iso})
    say(f'지수: 채울 행 {len(idx_add)}개' + (f' · {"; ".join(idx_note)}' if idx_note else ''))
    if not add and not idx_add:
        say('채울 새 거래일이 없어요(휴장일이거나 이미 최신). 사본을 바꾸지 않았어요.'); return 0
    if dry:
        say('--dry: 아무것도 쓰지 않았어요.'); return 0
    # 새 사본 쓰기
    stamp = now.strftime('%Y%m%dT%H%M%S+0900')
    dst = root.parent / stamp
    tmp = root.parent / (stamp + '.part')
    if tmp.exists():
        shutil.rmtree(tmp)
    newman = copy.deepcopy({k: v for k, v in man.items() if not k.startswith('_')})
    for src in root.rglob('*'):
        rel = src.relative_to(root)
        out = tmp / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True); continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel.name in ('manifest.json', 'manifest.sha256'):
            continue
        try:
            os.link(src, out)        # 바뀌지 않는 파일은 하드링크(공간 절약). 안 되면 복사
        except OSError:
            shutil.copyfile(src, out)
    np = newman['tables']['price_daily']
    for t, new in add.items():
        part = np['parts'][t]; f = tmp / part['file']
        data = (root / part['file']).read_bytes() + ''.join(map(line, new)).encode('utf-8')
        f.unlink(); f.write_bytes(data)
        part['rows'] += len(new); part['sha256'] = sha(f)
    np['rows'] = np.get('rows', 0) + sum(map(len, add.values()))
    if NOTE not in np.get('note', ''):
        np['note'] = np.get('note', '') + NOTE
    if idx_add:
        im = newman['tables']['market_index_daily']; f = tmp / im['file']
        data = (root / im['file']).read_bytes() + ''.join(map(line, idx_add)).encode('utf-8')
        f.unlink(); f.write_bytes(data)
        im['rows'] += len(idx_add); im['sha256'] = sha(f)
        if NOTE not in im.get('note', ''):
            im['note'] = im.get('note', '') + NOTE
    newman.setdefault('refresh', []).append({'at': now.isoformat(timespec='seconds'), 'base': base, 'tool': 'price_refresh v1', 'source': 'kis',
                                             'added_price_rows': sum(map(len, add.values())), 'companies': len(add), 'added_index_rows': len(idx_add),
                                             'overlap_check': f'최근 {OVERLAP}거래일 종가 원 단위 일치', 'failed': fails, 'kis_calls': kis.calls})
    mp = tmp / 'manifest.json'
    mp.write_text(json.dumps(newman, ensure_ascii=False), encoding='utf-8')
    (tmp / 'manifest.sha256').write_bytes(f'{sha(mp)}  manifest.json\n'.encode())
    tmp.rename(dst)
    # 새 사본을 엔진 방식 그대로 다시 읽어 본 뒤에만 LATEST 를 바꿈
    m2 = M.load_manifest(dst)
    for t in add:
        M.read_rows(dst, m2, 'price_daily', t)
    M.read_table(dst, m2, 'market_index_daily')
    lt = root.parent / 'LATEST.txt'; (root.parent / 'LATEST.txt.part').write_text(stamp + '\n', encoding='utf-8')
    os.replace(root.parent / 'LATEST.txt.part', lt)
    say(f'새 사본 {stamp} 를 만들고 LATEST 를 바꿨어요(예전 사본 {base} 는 그대로). 되돌리기: LATEST.txt 를 {base} 로.')
    return 0


if __name__ == '__main__':
    code = 1
    try:
        code = main(sys.argv[1:])
    except Exception as e:
        say(f'멈춤: {type(e).__name__}: {str(e)[:200]}')
    finally:
        (HERE / 'last-result.txt').write_text(datetime.now(KST).strftime('%Y-%m-%d %H:%M') + f' (끝 코드 {code})\n' + '\n'.join(LOG) + '\n', encoding='utf-8')
    sys.exit(code)
