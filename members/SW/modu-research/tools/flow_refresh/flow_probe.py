"""수급 KIS 독립(Plan B) 1단계 — 점검만 한다(아무것도 쓰지 않음, PM 2026-11-16).
KIS 두 가지 조회로 받은 투자자별 순매수가, 지금 사본(네이버 수집값)과 겹치는 날에 얼마나 같은지 회사 몇 곳으로 대조한다.
 - 주식현재가 투자자 (FHKST01010900): 개인·외국인·기관계 순매수 수량, 최근 약 30거래일
 - 주식현재가 일자별 (FHKST01010400): 외국인 소진율(hts_frgn_ehrt)·거래량, 최근 약 30거래일
결과는 같은 폴더 probe-result.txt 에 남긴다. 키 값은 어디에도 쓰지 않는다."""
import json, sys, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / 'modu-research-nodes'))
from mrn import market as M, surge as SG   # noqa: E402

KST = timezone(timedelta(hours=9))
PICK = ['005930', '000660', '035420', '005380', '068270', '105560', '000080', '035720']
LOG = []


def say(s):
    LOG.append(s); print(s, flush=True)


def get(kis, path, tr_id, params):
    tok = kis.token()
    kis.sleep(SG.SPACING); kis._count()
    st, js = kis.http('GET', SG.SERVER + path + '?' + urllib.parse.urlencode(params),
                      {'authorization': 'Bearer ' + tok, 'appkey': kis.key, 'appsecret': kis.secret, 'tr_id': tr_id, 'custtype': 'P'}, None)
    if st != 200 or str((js or {}).get('rt_cd')) != '0':
        raise SG.KisError('kis_' + str((js or {}).get('msg_cd') or st), f"KIS 조회 실패(HTTP {st} {(js or {}).get('msg_cd', '')} {(js or {}).get('msg1', '')})")
    out = js.get('output')
    return out if isinstance(out, list) else ([out] if out else [])


def dkey(s):
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}'


def main():
    root = M.resolve(''); man = M.load_manifest(root)
    say(f'사본 {root.name} · 점검 회사 {len(PICK)}곳 · {datetime.now(KST):%Y-%m-%d %H:%M}')
    cfg = SG.config()
    if not (cfg['key'] and cfg['secret']):
        say('KIS 키가 없어 점검하지 않아요.'); return 2
    kis = SG.Kis(cfg['key'], cfg['secret'])
    fields = [('individual_net_qty', 'prsn_ntby_qty', 'inv'), ('foreign_net_qty', 'frgn_ntby_qty', 'inv'),
              ('institution_net_qty', 'orgn_ntby_qty', 'inv'), ('foreign_net_qty', 'frgn_ntby_qty', 'day'),
              ('foreign_hold_pct', 'hts_frgn_ehrt', 'day'), ('volume', 'acml_vol', 'day')]
    tally = {f'{a}<-{c}:{b}': [0, 0] for a, b, c in fields}
    first = True
    for t in PICK:
        try:
            rows, _ = M.read_rows(root, man, 'investor_flow_daily', t)
        except Exception as e:
            say(f'{t}: 사본 없음 {e}'); continue
        snap = {r['trade_date'][:10]: r for r in rows}
        try:
            inv = {dkey(r['stck_bsop_date']): r for r in get(kis, '/uapi/domestic-stock/v1/quotations/inquire-investor', 'FHKST01010900',
                                                              {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t}) if r.get('stck_bsop_date')}
            day = {dkey(r['stck_bsop_date']): r for r in get(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-price', 'FHKST01010400',
                                                              {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t, 'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '1'}) if r.get('stck_bsop_date')}
        except Exception as e:
            say(f'{t}: KIS 실패 {e}'); continue
        if first:
            say(f'  [응답 항목 이름] 투자자: {sorted(next(iter(inv.values())).keys()) if inv else "없음"}')
            say(f'  [응답 항목 이름] 일자별: {sorted(next(iter(day.values())).keys()) if day else "없음"}')
            first = False
        both = sorted(set(snap) & set(inv))
        say(f'{t}: 사본 마지막 {max(snap)} · KIS 투자자 {min(inv) if inv else "-"}~{max(inv) if inv else "-"} ({len(inv)}일) · 일자별 {len(day)}일 · 겹치는 날 {len(both)}일')
        for d in both[-5:]:
            s = snap[d]; parts = []
            for a, b, c in fields:
                src = inv if c == 'inv' else day
                if d not in src:
                    continue
                kv, sv = src[d].get(b), s.get(a)
                try:
                    same = abs(float(kv) - float(sv)) < (0.005 if a == 'foreign_hold_pct' else 0.5)
                except (TypeError, ValueError):
                    same = False
                k = f'{a}<-{c}:{b}'; tally[k][0] += same; tally[k][1] += 1
                if not same:
                    parts.append(f'{a} 사본 {sv} / KIS({c}) {kv}')
            say(f'   {d}: ' + ('모두 같음' if not parts else ' | '.join(parts)))
    say('— 항목별 일치 (같은 날 수 / 대조한 날 수) —')
    for k, (a, n) in tally.items():
        say(f'  {k}: {a}/{n}')
    say(f'KIS 호출 {kis.calls}회')
    return 0


if __name__ == '__main__':
    code = 1
    try:
        code = main()
    except Exception as e:
        say(f'멈춤: {type(e).__name__}: {str(e)[:300]}')
    finally:
        (HERE / 'probe-result.txt').write_text('\n'.join(LOG) + '\n', encoding='utf-8')
    sys.exit(code)
