"""Evidence gate (stage 2).

Anything the agent says leaves through here. Text is built only from output packets
(facts, approved forecasts, node calculations) using checker slots, then checked by the
numeric checker in conservative mode: a sentence with an unbound number (red), a value that
disagrees with the source (mismatch), an unverifiable judgement (model) or a trade word is
withheld, with the reason kept. The same gate is exposed for any other text (e.g. a future
AI-written note) via /api/agent/gate.
"""
from . import numeric

METRIC_LABEL = {'revenue': '매출액', 'operatingProfit': '영업이익', 'cfo': '영업활동현금흐름', 'assets': '자산총계', 'liabilities': '부채총계'}


def context(store, owner, run_id):
    """facts / externals / derived values bound to one run's packets."""
    run = store.get_run(owner, run_id)
    facts, externals, derived, packets = {}, {}, {}, {}
    for n in run['nodes']:
        if n['output_packet'] and n['status'] in ('succeeded', 'partial'):
            packets[n['node_id']] = (n, store.get_packet(n['output_packet'], owner))
    for nid, (n, pk) in packets.items():
        p = pk['payload']
        src = f"{nid} 출력 패킷 {n['output_packet'][:12]}"
        if n['node_type'] == 'N01':
            for f in p.get('facts', []):
                facts[f['fact_id']] = f
        elif n['node_type'] == 'T04':
            for f in p.get('forecasts', []):
                externals[f['id']] = f
        elif n['node_type'] == 'N02':
            derived[f'{nid}.per_share'] = {'value': p['per_share'], 'unit': '원', 'source': src + ' · 주당가치'}
            if p.get('terminal_weight_pct') is not None:
                derived[f'{nid}.tw'] = {'value': p['terminal_weight_pct'], 'unit': '%', 'source': src + ' · 말기가치 비중'}
            for a in p.get('forecast_applied') or []:
                derived[f"{nid}.g{a['fiscal_year']}"] = {'value': a['growth'], 'unit': '%', 'source': src + f" · {a['fiscal_year']} 성장률(계산)"}
                derived[f"{nid}.m{a['fiscal_year']}"] = {'value': a['margin'], 'unit': '%', 'source': src + f" · {a['fiscal_year']} 이익률(계산)"}
    return run, packets, facts, externals, derived


def summary_text(run, packets, externals=None):
    externals = externals or {}
    """Template sentences: every number is a slot bound to a packet."""
    lines = []
    rank = {'N01': 0, 'T04': 1, 'N02': 2}
    for nid, (n, pk) in sorted(packets.items(), key=lambda kv: rank.get(kv[1][0]['node_type'], 9)):
        p = pk['payload']
        if n['node_type'] == 'N01':
            by = {}
            for f in p.get('facts', []):
                by.setdefault((f['company'], f['company_name']), {}).setdefault(f['period'], {})[f['metric']] = f['fact_id']
            for (comp, name), years in by.items():
                y = max(years)
                parts = [f"{METRIC_LABEL[m]}은 {{{{fact:{years[y][m]}}}}}" for m in ('revenue', 'operatingProfit') if m in years[y]]
                if parts:
                    lines.append(f"{name} {y}년 공시 원문 기준 " + ', '.join(parts) + '입니다.')
        elif n['node_type'] == 'T04':
            fc = p.get('forecasts', [])
            if fc:
                b = fc[0]
                lines.append(f"{b['broker']} 보고서의 승인된 외부 전망을 썼습니다(확인된 사실이 아님).")
                for f in sorted(fc, key=lambda x: (x['fiscal_year'], x['metric'])):
                    if f['metric'] in ('revenue', 'operatingProfit'):
                        lines.append(f"{f['fiscal_year']}년 {METRIC_LABEL[f['metric']]} 외부 전망: {{{{ext:{f['id']}}}}}.")
        elif n['node_type'] == 'N02':
            applied = p.get('forecast_applied') or []
            ext0 = externals.get(applied[0].get('revenue_id')) if applied else None
            src = (f"{ext0['broker']} 전망 적용" if ext0 else '외부 전망 적용') if applied else '사용자 가정만'
            kind = '학습용 예시 가정 포함' if p.get('illustrative') else '사용자 가정'
            lines.append(f"가치평가({p.get('company_name', '')}, {str(p.get('method', '')).upper()}, {src}, {kind})의 주당가치 계산 결과는 {{{{val:{nid}.per_share}}}}입니다(이 가정에서의 계산이며 투자 권유가 아님).")
            try:
                tw = float(p.get('terminal_weight_pct') or 0)
            except (TypeError, ValueError):
                tw = 0
            if tw >= 60:
                lines.append(f"이 계산에서 말기가치 비중은 {{{{val:{nid}.tw}}}}이며, " + ('증권사 전망은 나머지 명시 기간에만 반영됩니다.' if applied else '결과가 정상화 FCFF 가정에 크게 좌우됩니다.'))
            for a in applied:
                lines.append(f"{a['fiscal_year']}년 성장률 {{{{val:{nid}.g{a['fiscal_year']}}}}}, 이익률 {{{{val:{nid}.m{a['fiscal_year']}}}}}은 위 전망에서 계산했습니다.")
    for n in run['nodes']:
        if n['status'] == 'partial':
            lines.append(f"{n['node_type']}은 일부 구현 결과입니다.")
        elif n['status'] == 'not_connected':
            lines.append(f"{n['node_type']}은 미연결 노드입니다.")
    return '\n'.join(lines)


def check(text, facts, externals, derived):
    r = numeric.analyze(text, facts, 'conservative', externals, derived=derived)
    published = [s for s in r['sentences'] if not ({'red', 'mismatch', 'model', 'hidden'} & set(s['tiers']))]
    return {'policy': r['policy'], 'published': [s['text'] for s in published], 'held': r['held'],
            'counts': r['counts'], 'bound': sum(1 for x in r['spans'] if x['category'].startswith('slot:') and x['tier'] in ('verified', 'external', 'computed')),
            'spans': [{k: x[k] for k in ('text', 'category', 'tier', 'detail')} for x in r['spans'] if x['tier'] != 'info']}


def run_summary(store, owner, run_id):
    run, packets, facts, externals, derived = context(store, owner, run_id)
    text = summary_text(run, packets, externals)
    out = check(text, facts, externals, derived)
    out['template'] = text
    return out
