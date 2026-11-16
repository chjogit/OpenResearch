"""Objection -> re-deliberation (stage 4, attribute ⑥ responsive).

A person disagrees with one input of a finished run. The objection is recorded with its
reason, applied to a copy of that run's workflow (same cutoff, so the comparison is fair),
re-run through the self-correcting agent and the evidence gate, and compared with the
original run. The original run is never modified.

What can be objected to:
  T03  an assumption value (a scalar under model.*, or shares)   -> new value
  T04  which approved report to use                              -> another scanned report
  N02  whether to apply the approved forecast                    -> yes/no
  N01  "this fact looks wrong"                                   -> re-verify against the source (values cannot be edited)
"""
import copy
import uuid
from decimal import Decimal, InvalidOperation

KINDS = {'T03': 'assumption', 'T04': 'forecast_choice', 'N02': 'forecast_use', 'N01': 'fact_recheck'}
T03_LABELS = {'rate': '할인율(%)', 'terminal_growth': '영구성장률(%)', 'terminal_fcff': '정상화 FCFF(백만원)', 'tax': '세율(%)',
              'depreciation': '감가상각(백만원)', 'capex': '투자(백만원)', 'delta_wc': '운전자본 증감(백만원)', 'growth': '성장률(%)',
              'margin': '영업이익률(%)', 'debt': '차입금(백만원)', 'excess_cash': '초과현금(백만원)', 'nonoperating_assets': '비영업자산(백만원)',
              'minority': '비지배지분(백만원)', 'preferred': '우선주(백만원)', 'other_claims': '기타 청구권(백만원)', 'cost_of_equity': '자기자본비용(%)'}


class ObjectionError(ValueError):
    pass


def _scalar_paths(obj, prefix=''):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out += _scalar_paths(v, f'{prefix}.{k}' if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += _scalar_paths(v, f'{prefix}.{i}')
    elif isinstance(obj, (str, int, float)):
        out.append((prefix, obj))
    return out


def fields_for(node, reports=None):
    """Objectionable fields of a node, with current values and labels."""
    t, cfg = node['type'], node.get('config') or {}
    if t == 'T03':
        out = []
        for path, v in _scalar_paths(cfg.get('model') or {}, 'model'):
            last = path.split('.')[-1]
            if last in ('discount_basis', 'terminal_reason'):
                continue
            parts = path.split('.')
            yr = f" ({int(parts[2]) + 1}년차)" if len(parts) > 3 and parts[1] == 'years' else ''
            out.append({'field': path, 'label': T03_LABELS.get(last, last) + yr, 'current': str(v)})
        out.append({'field': 'shares', 'label': '주식 수', 'current': str(cfg.get('shares', ''))})
        pri = {'model.rate': 0, 'model.cost_of_equity': 0, 'model.terminal_growth': 1, 'model.terminal_fcff': 2}
        return sorted(out, key=lambda x: (pri.get(x['field'], 3 if '.years.' in x['field'] else 4 if '.bridge.' in x['field'] else 5)))
    if t == 'T04':
        opts = [{'value': r['file'], 'label': f"{r.get('report_date')} {r.get('broker')}"} for r in (reports or [])]
        return [{'field': 'report', 'label': '적용할 보고서', 'current': cfg.get('report', ''), 'options': opts}]
    if t == 'N02':
        return [{'field': 'apply_forecast', 'label': '승인 전망 적용', 'current': cfg.get('apply_forecast', 'yes'), 'options': [{'value': 'yes', 'label': '적용'}, {'value': 'no', 'label': '적용 안 함'}]}]
    if t == 'N01':
        return [{'field': '', 'label': '사실 재확인 (원문 재대조)', 'current': ''}]
    return []


def apply(doc, node_id, field, value, reports=None):
    """Return (new_doc, change). Raises ObjectionError for anything not allowed."""
    doc = copy.deepcopy(doc)
    node = next((n for n in doc['nodes'] if n['id'] == node_id), None)
    if not node:
        raise ObjectionError('node_not_found')
    if node['type'] not in KINDS:
        raise ObjectionError('이 노드는 이의 제기 대상이 아닙니다.')
    allowed = {f['field']: f for f in fields_for(node, reports)}
    if field not in allowed:
        raise ObjectionError('이의를 제기할 수 없는 항목입니다.')
    before = allowed[field]['current']
    if node['type'] == 'N01':
        return doc, {'node': node_id, 'field': '', 'before': '', 'after': '', 'label': '사실 재확인'}
    value = str(value).strip()
    if 'options' in allowed[field] and value not in {o['value'] for o in allowed[field]['options']}:
        raise ObjectionError('선택지에 없는 값입니다.')
    if node['type'] == 'T03':
        try:
            Decimal(value.replace(',', ''))
        except (InvalidOperation, ValueError):
            raise ObjectionError('숫자로 적어 주세요 (예: 10.5).')
        value = value.replace(',', '')
        if field == 'shares':
            node['config']['shares'] = value
        else:
            parts = field.split('.')[1:]
            cur = node['config']['model']
            for p in parts[:-1]:
                cur = cur[int(p)] if isinstance(cur, list) else cur[p]
            last = parts[-1]
            if isinstance(cur, list):
                cur[int(last)] = value
            else:
                cur[last] = value
        # the other values keep their kind (e.g. learning example); the change is recorded in the note
        node['config']['assumptions_note'] = (node['config'].get('assumptions_note') or '') + f' / 이의 반영: {field}={value}'
    else:
        node['config'][field] = value
    if str(before) == value:
        raise ObjectionError('지금 값과 같습니다. 다른 값을 적어 주세요.')
    return doc, {'node': node_id, 'field': field, 'label': allowed[field]['label'], 'before': before, 'after': value}


def compare(store, owner, base_run_id, new_run_id):
    """Side-by-side of the original and re-deliberated runs (per-share, statuses, facts)."""
    def pick(run_id):
        run = store.get_run(owner, run_id)
        out = {'status': run['status'], 'nodes': {}, 'per_share': {}, 'facts': {}}
        for n in run['nodes']:
            out['nodes'][n['node_id']] = n['status']
            if n['output_packet'] and n['status'] in ('succeeded', 'partial'):
                p = store.get_packet(n['output_packet'], owner)['payload']
                if n['node_type'] == 'N02':
                    out['per_share'][n['node_id']] = p['per_share']
                if n['node_type'] == 'N01':
                    for f in p.get('facts', []):
                        out['facts'][f['fact_id']] = f['value']
        return out
    a, b = pick(base_run_id), pick(new_run_id)
    rows = []
    for nid in sorted(set(a['per_share']) | set(b['per_share'])):
        x, y = a['per_share'].get(nid), b['per_share'].get(nid)
        pct = None
        try:
            pct = f'{(Decimal(y) / Decimal(x) - 1) * 100:+.2f}' if x and y and Decimal(x) != 0 else None
        except (InvalidOperation, TypeError):
            pass
        rows.append({'node': nid, 'before': x, 'after': y, 'change_pct': pct})
    changed_facts = [k for k in set(a['facts']) & set(b['facts']) if str(a['facts'][k]) != str(b['facts'][k])]
    status_changes = [{'node': k, 'before': a['nodes'].get(k), 'after': b['nodes'].get(k)}
                      for k in sorted(set(a['nodes']) | set(b['nodes'])) if a['nodes'].get(k) != b['nodes'].get(k)]
    return {'per_share': rows, 'facts_compared': len(set(a['facts']) & set(b['facts'])), 'facts_changed': changed_facts,
            'status_changes': status_changes, 'before_status': a['status'], 'after_status': b['status']}


def new_id():
    return uuid.uuid4().hex
