"""v0.28.2 실행 결과 요약 보정 — 멱등 패치. 사용: python patch_v0282.py <앱 폴더>"""
import sys, os
root = sys.argv[1]
def rw(rel, pairs, mark):
    p = os.path.join(root, rel); s = open(p, encoding='utf-8').read()
    if mark in s:
        print('skip', rel); return
    for a, b in pairs:
        assert s.count(a) == 1, (rel, a[:60], s.count(a))
        s = s.replace(a, b)
    open(p, 'w', encoding='utf-8').write(s); print('patched', rel)

# ① 계획 배치: 심층 노드의 선택 입력 중 같은 관점 자료는 자동으로 잇는다 (N06←T10, N04←T09)
rw('mrn/specs.py', [
 ("def plan_workflow(perspectives, name=None):",
  "PLAN_OPTIONAL = {('N06', 'macro'), ('N04', 'peers')}   # v0.28.2: 계획 배치 때 함께 잇는 선택 입력 (빈 「일부 확인」 방지)\n\n\ndef plan_workflow(perspectives, name=None):"),
 ("            if not inp['required'] and not inp.get('auto'):\n                continue",
  "            if not inp['required'] and not inp.get('auto') and (sid, inp['name']) not in PLAN_OPTIONAL:\n                continue"),
], 'PLAN_OPTIONAL')

# ① N08·N10: 같은 실행에 N11이 있어도 「함께 보지 않음」으로 읽히던 문구 → 일부러 하지 않는 것으로
rw('mrn/nodes.py', [
 ("'이상 변화의 원인 해석: 뉴스 노드(N11) 미연결'",
  "'이상 변화의 원인 해석: 하지 않음 — 그 시기 공시·뉴스는 「주요 사건·감성 현황」에서 함께 보세요'"),
 ("'원인 해석(왜 엇갈렸는지): 뉴스 노드(N11) 미연결'",
  "'원인 해석(왜 엇갈렸는지): 하지 않음 — 그 시기 공시·뉴스는 「주요 사건·감성 현황」에서 함께 보세요'"),
 # ② N12: 비교 기준 = 국내 회사 동일 가중(자기 제외), 하락장 기저(같은 기간 아무 날) 함께
 ("""    try:
        idx, isrc = index_series(ctx.cutoff, node['config'].get('snapshot') or '', '^KS11')
        idx = dict(idx)
    except SnapshotError:
        idx, isrc = {}, None
    import bisect
    cats""",
  """    from .reaction import equal_weight_ex
    mret, blabel = None, None
    try:                                                 # v0.28.2: 기본 비교 기준 = 국내 회사 동일 가중(자기 제외)
        mret, blabel = equal_weight_ex(ctx.cutoff, node['config'].get('snapshot') or '', px['company'])
    except SnapshotError:
        mret = None
    try:
        idx, isrc = index_series(ctx.cutoff, node['config'].get('snapshot') or '', '^KS11')
        idx = dict(idx)
    except SnapshotError:
        idx, isrc = {}, None
    if mret is None:
        blabel = '코스피(비공식 지수)'
    def mkt_cum(i, j):                                   # dates[i]..dates[j] 의 시장 누적 수익률
        if mret is not None:
            acc = 1.0
            for k in range(i, j + 1):
                if dates[k] not in mret:
                    return None
                acc *= 1 + mret[dates[k]]
            return acc - 1
        if idx.get(dates[j]) and idx.get(dates[i - 1]):
            return _f(idx[dates[j]]) / _f(idx[dates[i - 1]]) - 1
        return None
    import bisect
    cats"""),
 ("""                ex = None
                if idx.get(dates[j]) and idx.get(dates[i - 1]):
                    ex = r - (_f(idx[dates[j]]) / _f(idx[dates[i - 1]]) - 1)
                rec[f'r{h}']""",
  """                m = mkt_cum(i, j)
                ex = None if m is None else r - m
                rec[f'r{h}']"""),
 ("""    for k, rs in sorted(per.items(), key=lambda x: -len(x[1])):
        r5 = [r['r5'] for r in rs if r.get('r5') is not None]
        x5 = [r['x5'] for r in rs if r.get('x5') is not None]
        txt = f"{len(rs)}건, 5거래일 수익률 중앙값 {median(r5):+.2f}%" if r5 else f"{len(rs)}건"
        if x5:
            txt += f", 코스피 대비 {median(x5):+.2f}%p\"""",
  """    i0 = min(bisect.bisect_left(dates, r['t0']) for r in T)        # 같은 기간 아무 날이나 고른 5거래일 (하락장·상승장 기저)
    b5 = [close[i + 4] / close[i - 1] * 100 - 100 for i in range(max(i0, 1), len(dates) - 4)]
    bx5 = [x for x in ((close[i + 4] / close[i - 1] - 1 - m) * 100 for i in range(max(i0, 1), len(dates) - 4) for m in [mkt_cum(i, i + 4)] if m is not None)]
    base5 = median(b5) if len(b5) >= 20 else None
    if base5 is not None:
        F.append({'name': '기준선: 같은 기간 아무 날이나 고른 5거래일 수익률', 'kind': 'derived',
                  'claim': f"중앙값 {base5:+.2f}% ({len(b5)}개 날짜, {dates[max(i0, 1)]}부터)" + (f", {blabel} 대비 {median(bx5):+.2f}%p" if bx5 else '')
                           + ' — 공시 뒤 반응은 이 기준선과 견주어 보세요. 이 기간 전체가 오르거나 내린 영향이 섞여 있어요',
                  'formula': '기간 첫 공시일부터 마지막까지 모든 거래일을 0일로 두고 잰 5거래일 수익률의 중앙값'})
    else:
        held.append('기준선(같은 기간 아무 날 5거래일 수익률): 날짜가 20개 미만이라 계산하지 않음')
    for k, rs in sorted(per.items(), key=lambda x: -len(x[1])):
        r5 = [r['r5'] for r in rs if r.get('r5') is not None]
        x5 = [r['x5'] for r in rs if r.get('x5') is not None]
        txt = f"{len(rs)}건, 5거래일 수익률 중앙값 {median(r5):+.2f}%" if r5 else f"{len(rs)}건"
        if r5 and base5 is not None:
            txt += f" (기준선보다 {median(r5) - base5:+.2f}%p)"
        if x5:
            txt += f", {blabel} 대비 {median(x5):+.2f}%p\""""),
 ("'formula': '0일 = 접수일(장 마감 뒤 접수면 실제 반응은 다음 날). 수익률 = h거래일째 종가 / 0일 전날 종가 − 1. 코스피 대비 = 차이(비공식 지수)'}",
  "'formula': f'0일 = 접수일(장 마감 뒤 접수면 실제 반응은 다음 날). 수익률 = h거래일째 종가 / 0일 전날 종가 − 1. 시장 대비 = 같은 날들의 {blabel} 누적 수익률과의 차이'}"),
 ("'5일 코스피 대비 %p'", "'5일 시장 대비 %p'"),
 ("'hint': '같은 기간 다른 사건이 겹칠 수 있어 공시 때문에 움직였다고 볼 수 없습니다. 코스피는 비공식(야후) 지수입니다.'}",
  "'hint': f'같은 기간 다른 사건이 겹칠 수 있어 공시 때문에 움직였다고 볼 수 없습니다. 같은 날 나온 공시는 따로 세지만 서로 독립된 표본이 아닙니다. 시장 = {blabel}.'}"),
 ("""    if not isrc:
        held.append('코스피 대비: 지수 사본 없음')""",
  """    if mret is None and not isrc:
        held.append('시장 대비: 비교 기준을 만들 자료 없음')"""),
 ("'price_source': px['source'], 'index_source': isrc,", "'price_source': px['source'], 'index_source': isrc, 'benchmark_label': blabel,"),
], 'equal_weight_ex')

rw('mrn/reaction.py', [
 ("def build(cutoff='', snapshot='', bench=None):",
  '''_EW = {}


def equal_weight_ex(cutoff='', snapshot='', exclude=''):
    """v0.28.2 (N12): 사본 국내 회사 동일 가중 일별 수익률(자기 제외). 20곳 미만이면 SnapshotError."""
    cutoff = cutoff or datetime.now(timezone.utc).isoformat()
    root = resolve(snapshot)
    man = load_manifest(root)
    last = last_usable_date(cutoff)
    key = (man['_manifest_sha256'], last)
    if key not in _EW:
        cos = companies(root, man)
        parts = (man['tables'].get('price_daily') or {}).get('parts') or {}
        rets = {}
        for t in sorted(parts):
            c = cos.get(t, {})
            if c and c.get('market') not in (None, 'KR'):
                continue
            try:
                px, _ = read_rows(root, man, 'price_daily', t)
            except SnapshotError:
                continue
            px = [(r['trade_date'][:10], r['close']) for r in px if r.get('source') == 'fsc' and r['trade_date'][:10] <= last]
            if len(px) >= 30:
                rets[t] = returns(px)[1]
        tot, cnt = {}, {}
        for r in rets.values():
            for d, v in r.items():
                tot[d] = tot.get(d, 0.0) + v
                cnt[d] = cnt.get(d, 0) + 1
        _EW[key] = (rets, tot, cnt)
    rets, tot, cnt = _EW[key]
    me = rets.get(exclude, {})
    out = {d: (tot[d] - me.get(d, 0.0)) / (cnt[d] - (1 if d in me else 0)) for d in tot if cnt[d] - (1 if d in me else 0) >= 20}
    if not out:
        raise SnapshotError('few_companies', '비교 기준(국내 회사 평균)을 만들 회사가 20개보다 적습니다.')
    n = len(rets) - (1 if exclude in rets else 0)
    return out, f'국내 회사 {n}곳 동일 가중 평균(자기 제외)'


def build(cutoff='', snapshot='', bench=None):'''),
], 'def equal_weight_ex')

# ③ N01 계산값에 회사 이름·읽기 쉬운 단위, 가격·수급 자료 마지막 날
rw('mrn/easy.py', [
 ("""            for d in p.get('derived', []):
                items.append(_item(n['node_id'], t, f"{d['period']}년 {d['label']}", f"{d['value']} {d['unit']}", 'derived', d['formula'], d['value'], d['unit']))""",
  """            cname = {f['company']: f['company_name'] for f in p.get('facts', []) if f.get('company') and f.get('company_name')}
            for d in p.get('derived', []):
                who = cname.get(d.get('company')) or COMPANIES.get(d.get('company')) or ''
                val = _won(d['value'], d['unit']) if d['unit'] == '백만원' else f"{d['value']} {d['unit']}"
                items.append(_item(n['node_id'], t, f"{who} {d['period']}년 {d['label']}".strip(), val, 'derived', d['formula'], d['value'], d['unit']))"""),
 ("""    st = {n['node_id']: n for n in run['nodes']}
    name = None
    for n in run['nodes']:
        t = n['node_type']
        if not t.startswith('N'):""",
  """    st = {n['node_id']: n for n in run['nodes']}
    name = None
    through = {}                                          # v0.28.2: 가격·수급 자료의 마지막 거래일
    for n in run['nodes']:
        if n['node_type'] in ('T06', 'T07') and n.get('output_packet') and n['status'] in ('succeeded', 'partial'):
            try:
                rows = (get_packet(n['output_packet'])['payload'].get('rows') or [])
                if rows:
                    k = '가격' if n['node_type'] == 'T06' else '수급'
                    through[k] = max(through.get(k, ''), str(rows[-1]['trade_date'])[:10])
            except Exception:
                pass
    for n in run['nodes']:
        t = n['node_type']
        if not t.startswith('N'):"""),
 ("'relmap': relmap, 'forecast': fcast,", "'relmap': relmap, 'forecast': fcast, 'data_through': through,"),
], 'data_through')

ASOF = r'''
/* v0.28.2: 기준 시각을 한국 시각으로 — 장중이면 「그날 장은 아직 반영 안 됨」, 가격·수급 자료의 마지막 거래일 함께 */
function asofText(a){
  const cut = String(a.cutoff || '');
  let s;
  if (cut.length <= 10) s = `${cut} 장 마감까지 공개된 자료 기준`;
  else { const c = new Date(cut); if (isNaN(c)) s = `${cut.slice(0, 10)} 기준`;
    else { const k = new Date(c.getTime() + 9 * 3600e3).toISOString(), ds = k.slice(0, 10), hm = k.slice(11, 16);
      s = hm < '15:30' ? `${ds} ${hm}(한국 시각)까지 공개된 자료 기준 — 그날 장은 아직 반영 안 됨` : `${ds} 장 마감까지 공개된 자료 기준`; } }
  const t = a.data_through || {}, v = [...new Set(Object.values(t))];
  if (v.length === 1) s += ` · ${Object.keys(t).join('·')} 자료 마지막 거래일 ${v[0]}`;
  else if (v.length > 1) s += ' · ' + Object.entries(t).map(([x, d]) => `${x} 자료 마지막 거래일 ${d}`).join(', ');
  return s;
}
'''
rw('web/app.js', [
 ("function summaryHtml(a){", ASOF + "function summaryHtml(a){"),
 ("""<b>${esc(a.name || '')}</b> · ${esc((a.cutoff || '').slice(0, 10))} 장 마감까지 공개된 자료 기준<br>""",
  """<b>${esc(a.name || '')}</b> · ${esc(asofText(a))}<br>"""),
 ("""${a.name || ''} · ${(a.cutoff || '').slice(0, 10)} 장 마감까지 공개된 자료 기준`,""",
  """${a.name || ''} · ${asofText(a)}`,"""),
], 'function asofText')
rw('web/easy.js', [
 ("async function openAnswer(rid, opt={}){", ASOF + "async function openAnswer(rid, opt={}){"),
 ("""· <b>${esc(date)}</b> 장 마감까지 공개된 자료 기준</div>""", """· <b>${esc(asofText(a))}</b></div>"""),
], 'function asofText')
