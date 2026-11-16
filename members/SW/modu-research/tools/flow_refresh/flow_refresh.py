"""수급 사본 갱신 — Plan B: 철현님 Neon 없이 PM 키로 (PM 결정 2026-11-16, 연구용 · 재배포 계약 전).
최신 사본의 투자자별 순매수(investor_flow_daily, 네이버 수집값)에 한국투자증권(KIS) 조회값으로 빈 날을 채운 「새 사본」을 만든다.

쓰는 KIS 조회 두 가지 (점검 2026-11-16: 8곳 × 5일, 아래 다섯 항목 모두 40/40 일치)
 - 주식현재가 투자자 FHKST01010900 → 개인·외국인·기관계 순매수 수량(prsn/frgn/orgn_ntby_qty)
 - 주식현재가 일자별 FHKST01010400 → 외국인 소진율(hts_frgn_ehrt = 사본의 보유율) · 거래량(acml_vol)
   (일자별의 frgn_ntby_qty 는 사본과 정의가 달라 쓰지 않음: 0/40)
지키는 것 (가격 갱신과 같은 방식)
- 원래 사본은 건드리지 않는다. 새 사본 폴더를 만든 뒤 마지막에 LATEST.txt 만 바꾼다(되돌리기 = LATEST.txt 를 예전 이름으로).
- 회사마다 사본의 최근 5거래일 순매수 3종·거래량이 주 단위까지 같아야 채운다.
  외국인 보유율은 KIS 소진율과 0.01%p 안(반올림 차이)일 때만 채우고, 외국인 한도 종목처럼 다르면 비워 둔다(2026-11-16 실행: 30곳).
  하나라도 다르거나 겹치는 날이 없으면(공백이 KIS 약 30거래일보다 김) 그 회사는 채우지 않는다. 실패 20% 넘으면 아무것도 안 바꾼다.
- 오늘 자료는 장 마감(16시) 뒤에만 넣는다(KIS 당일 수급은 장 종료 후 제공). 중간에 빈 날이 생기면 거기서 멈춘다(구멍 없음).
- 채운 행은 source='kis_investor'. 엔진은 출처에 「한국투자증권 투자자별 매매(kis) n거래일 보충」을 붙인다(v0.39.5).
- 키는 엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET(환경 변수)만. 키 값은 화면·파일·기록 어디에도 쓰지 않는다.
쓰는 법: (엔진 가상환경 python) flow_refresh.py [--dry] [--auto]"""
import copy, json, os, shutil, sys, urllib.parse
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'modu-research-nodes'))
sys.path.insert(0, str(ROOT / '_tools' / 'price_refresh'))
from mrn import market as M, surge as SG   # noqa: E402
import price_refresh as PR                 # noqa: E402  (expected_last · sha · line 를 같이 씀)

KST = PR.KST
OVERLAP = 5
FAIL_RATIO = 0.20
TABLE = 'investor_flow_daily'
NOTE = ' + 한국투자증권 투자자별 매매(kis_investor) 보충(연구용·재배포 계약 전)'
NETS = (('individual_net_qty', 'prsn_ntby_qty'), ('foreign_net_qty', 'frgn_ntby_qty'), ('institution_net_qty', 'orgn_ntby_qty'))
LOG = []


def say(s):
    LOG.append(s); print(s, flush=True)


def get(kis, path, tr_id, params):
    tok = kis.token()
    kis.sleep(SG.SPACING); kis._count()
    st, js = kis.http('GET', SG.SERVER + path + '?' + urllib.parse.urlencode(params),
                      {'authorization': 'Bearer ' + tok, 'appkey': kis.key, 'appsecret': kis.secret, 'tr_id': tr_id, 'custtype': 'P'}, None)
    if st != 200 or str((js or {}).get('rt_cd')) != '0':
        raise SG.KisError('kis_' + str((js or {}).get('msg_cd') or st), f"KIS 조회 실패(HTTP {st} {(js or {}).get('msg_cd', '')})")
    out = js.get('output')
    return out if isinstance(out, list) else ([out] if out else [])


def _d(s):
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}'


def fetch(kis, t):
    """→ (투자자 {날짜: 행}, 일자별 {날짜: 행})"""
    inv = get(kis, '/uapi/domestic-stock/v1/quotations/inquire-investor', 'FHKST01010900', {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t})
    day = get(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-price', 'FHKST01010400',
              {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t, 'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '1'})
    return ({_d(r['stck_bsop_date']): r for r in inv if r.get('stck_bsop_date')},
            {_d(r['stck_bsop_date']): r for r in day if r.get('stck_bsop_date')})


def _int(x):
    return int(Decimal(str(x).strip() or '0'))


def plan(t, rows, inv, day, exp, now_iso):
    """→ (새 행 목록, 문제). rows = 사본의 이 회사 행."""
    have = sorted(rows, key=lambda r: r['trade_date'])
    if not have:
        return [], '사본에 수급 행이 없음'
    tail = have[-OVERLAP:]
    both = [r for r in tail if r['trade_date'][:10] in inv and r['trade_date'][:10] in day]
    if not both:
        return [], 'KIS 응답에 겹치는 날이 없어 대조할 수 없음(공백이 KIS 약 30거래일보다 김)'
    for r in both:
        d = r['trade_date'][:10]; k, y = inv[d], day[d]
        for a, b in NETS:
            if _int(r.get(a)) != _int(k.get(b)):
                return [], f'{d} {a} 다름(사본 {r.get(a)} · KIS {k.get(b)})'
        if r.get('volume') not in (None, '') and _int(r['volume']) != _int(y.get('acml_vol')):
            return [], f"{d} 거래량 다름(사본 {r['volume']} · KIS {y.get('acml_vol')})"
    # 외국인 보유율: KIS 소진율(한도 대비)과 0.01%p 안(반올림 차이)이면 같은 값으로 봄.
    # 외국인 한도가 있는 종목(통신·전력·항공 등)은 소진율 ≠ 보유율 → 보유율은 비워 둠(추정해서 넣지 않음). 순매수·거래량은 그대로 채움
    hold_ok = True
    for r in both:
        hp = r.get('foreign_hold_pct')
        if hp not in (None, '') and abs(Decimal(str(hp)) - Decimal(str(day[r['trade_date'][:10]].get('hts_frgn_ehrt') or '0'))) > Decimal('0.0101'):
            hold_ok = False
    last = have[-1]['trade_date'][:10]
    hp_str = isinstance(have[-1].get('foreign_hold_pct'), str)
    new = []
    for d in sorted(x for x in inv if last < x <= exp):
        if d not in day:
            break                     # 두 조회 중 하나라도 빈 날이면 거기서 멈춤(구멍 없음)
        k, y = inv[d], day[d]
        hp = Decimal(str(y.get('hts_frgn_ehrt') or '0')).quantize(Decimal('0.0001'))
        new.append({'ticker': t, 'trade_date': d,
                    'individual_net_qty': _int(k.get('prsn_ntby_qty')), 'foreign_net_qty': _int(k.get('frgn_ntby_qty')),
                    'institution_net_qty': _int(k.get('orgn_ntby_qty')),
                    'foreign_hold_pct': (f'{hp:.4f}' if hp_str else float(hp)) if hold_ok else None, 'volume': _int(y.get('acml_vol')),
                    'source': 'kis_investor', 'collected_at': now_iso})
    plan.hold_blank = not hold_ok   # 알림용(보유율을 비운 회사)
    return new, None


def main(argv):
    dry, auto = '--dry' in argv, '--auto' in argv
    now = datetime.now(KST); now_iso = datetime.now(timezone.utc).isoformat()
    root = M.resolve(''); man = M.load_manifest(root)
    base = root.name; exp = PR.expected_last(now)
    tb = man['tables'][TABLE]; parts = tb.get('parts') or {}
    say(f'기준 사본 {base} · 수급 회사 {len(parts)}곳 · 채워야 할 마지막 거래일 {exp}')
    rows_of, stale = {}, []
    for t in sorted(parts):
        rows, _ = M.read_rows(root, man, TABLE, t)   # 해시·행 수 대조
        rows_of[t] = rows
        last = max((r['trade_date'][:10] for r in rows), default='')
        if last and last < exp:
            stale.append(t)
    if auto and not stale:
        say('수급 사본이 이미 최신이에요. KIS를 부르지 않고 끝냅니다.'); return 0
    cfg = SG.config()
    if not (cfg['key'] and cfg['secret']):
        say('KIS 키가 없어 갱신하지 않아요(엔진 local-env.cmd 의 KIS_APP_KEY·KIS_APP_SECRET).'); return 2
    kis = SG.Kis(cfg['key'], cfg['secret'])
    add, fails, blank = {}, {}, []
    for i, t in enumerate(stale, 1):
        try:
            inv, day = fetch(kis, t)
        except Exception as e:
            fails[t] = str(e)[:120]; continue
        new, why = plan(t, rows_of[t], inv, day, exp, now_iso)
        if why:
            fails[t] = why
        elif new:
            add[t] = new
            if getattr(plan, 'hold_blank', False):
                blank.append(t)
        if i % 50 == 0:
            say(f'  … {i}/{len(stale)}곳 확인')
    say(f'KIS 투자자별 매매: 확인 {len(stale)}곳 · 채울 회사 {len(add)}곳 · 행 {sum(map(len, add.values()))}개 · 대조 실패 {len(fails)}곳 · KIS 호출 {kis.calls}회')
    for t, why in list(fails.items())[:15]:
        say(f'  대조 실패 {t}: {why}')
    if blank:
        say(f'  외국인 한도 종목 등 보유율이 KIS 소진율과 달라 보유율만 비운 회사 {len(blank)}곳(순매수·거래량은 채움): {", ".join(blank[:20])}')
    if stale and len(fails) / len(stale) > FAIL_RATIO:
        say(f'대조 실패가 {len(fails)}/{len(stale)}곳으로 20%를 넘어 아무것도 바꾸지 않았어요.'); return 3
    if not add:
        say('채울 새 거래일이 없어요(휴장일이거나 이미 최신). 사본을 바꾸지 않았어요.'); return 0
    if dry:
        say('--dry: 아무것도 쓰지 않았어요.'); return 0
    stamp = now.strftime('%Y%m%dT%H%M%S+0900')
    dst = root.parent / stamp
    if dst.exists():
        say(f'같은 이름의 사본 {stamp} 가 이미 있어요. 1분 뒤 다시 실행해 주세요.'); return 4
    tmp = root.parent / (stamp + '.part')
    if tmp.exists():
        shutil.rmtree(tmp)
    newman = copy.deepcopy({k: v for k, v in man.items() if not k.startswith('_')})
    for src in root.rglob('*'):
        rel = src.relative_to(root); out = tmp / rel
        if src.is_dir():
            out.mkdir(parents=True, exist_ok=True); continue
        out.parent.mkdir(parents=True, exist_ok=True)
        if rel.name in ('manifest.json', 'manifest.sha256'):
            continue
        try:
            os.link(src, out)
        except OSError:
            shutil.copyfile(src, out)
    nt = newman['tables'][TABLE]
    for t, new in add.items():
        part = nt['parts'][t]; f = tmp / part['file']
        data = (root / part['file']).read_bytes() + ''.join(map(PR.line, new)).encode('utf-8')
        f.unlink(); f.write_bytes(data)
        part['rows'] += len(new); part['sha256'] = PR.sha(f)
    nt['rows'] = nt.get('rows', 0) + sum(map(len, add.values()))
    if NOTE not in nt.get('note', ''):
        nt['note'] = nt.get('note', '') + NOTE
    newman.setdefault('refresh', []).append({'at': now.isoformat(timespec='seconds'), 'base': base, 'tool': 'flow_refresh v1', 'source': 'kis_investor',
                                             'added_flow_rows': sum(map(len, add.values())), 'companies': len(add),
                                             'overlap_check': f'최근 {OVERLAP}거래일 순매수 3종·거래량 주 단위 일치(보유율은 0.01%p 안일 때만 채움)',
                                             'hold_blank': blank, 'failed': fails, 'kis_calls': kis.calls})
    mp = tmp / 'manifest.json'
    mp.write_text(json.dumps(newman, ensure_ascii=False), encoding='utf-8')
    (tmp / 'manifest.sha256').write_bytes(f'{PR.sha(mp)}  manifest.json\n'.encode())
    tmp.rename(dst)
    m2 = M.load_manifest(dst)
    for t in add:
        M.read_rows(dst, m2, TABLE, t)
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
