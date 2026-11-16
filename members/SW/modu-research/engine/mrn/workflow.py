"""Workflow document model and pre-run validation.

An edge is a data-transfer relation only (output port -> input port). It does not
mean approval, trust, or correctness. Execution order is derived separately.
"""
from typing import Any
from pydantic import Field
from .util import Contract, instant
from .specs import SPECS, with_defaults

MAX_NODES = 64


class NodeDoc(Contract):
    id: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,40}$')
    type: str = Field(max_length=8)
    x: float = 0
    y: float = 0
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeDoc(Contract):
    from_node: str
    from_port: str
    to_node: str
    to_port: str


class WorkflowDoc(Contract):
    name: str = Field(min_length=1, max_length=100)
    cutoff: str = ''
    nodes: list[NodeDoc] = Field(default_factory=list, max_length=MAX_NODES)
    edges: list[EdgeDoc] = Field(default_factory=list, max_length=256)
    viewport: dict[str, float] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)       # v0.15: 쉬운 화면 카드·회사 등 (계산에 쓰지 않음)


def issue(code, message, fix, nodes=(), edge=None, severity='error'):
    return {'code': code, 'severity': severity, 'message': message, 'fix': fix, 'nodes': list(nodes), 'edge': edge}


def out_port(type_, name):
    return next((p for p in SPECS[type_]['outputs'] if p['name'] == name), None)


def in_port(type_, name):
    return next((p for p in SPECS[type_]['inputs'] if p['name'] == name), None)


def topo_order(doc):
    """Return node ids in execution order, or raise ValueError('cycle', ids)."""
    deps = {n.id: set() for n in doc.nodes}
    for e in doc.edges:
        if e.to_node in deps and e.from_node in deps:
            deps[e.to_node].add(e.from_node)
    order, done = [], set()
    pending = [n.id for n in doc.nodes]
    while pending:
        ready = [n for n in pending if deps[n] <= done]
        if not ready:
            raise ValueError('cycle', pending)
        for n in ready:
            order.append(n)
            done.add(n)
        pending = [n for n in pending if n not in done]
    return order


def effective_cutoff(doc, node):
    return (node.config.get('cutoff') or doc.cutoff or '').strip()


def validate(doc: WorkflowDoc, check_assumptions=None):
    """Return a list of issues. Any 'error' blocks execution."""
    out = []
    ids = [n.id for n in doc.nodes]
    nodes = {n.id: n for n in doc.nodes}
    if not doc.nodes:
        out.append(issue('empty', '노드가 없습니다.', '왼쪽 라이브러리에서 노드를 추가하세요.'))
    if len(ids) != len(set(ids)):
        out.append(issue('duplicate_node', '같은 ID의 노드가 둘 이상입니다.', '노드를 삭제하고 다시 추가하세요.'))
    for n in doc.nodes:
        if n.type not in SPECS:
            out.append(issue('unknown_node_type', f'알 수 없는 노드 종류 {n.type}', '노드를 삭제하세요.', [n.id]))
    if out:
        return out

    seen_inputs = {}
    for i, e in enumerate(doc.edges):
        a, b = nodes.get(e.from_node), nodes.get(e.to_node)
        if a is None or b is None:
            out.append(issue('dangling_edge', '없는 노드를 가리키는 연결선입니다.', '연결선을 삭제하세요.', edge=i))
            continue
        op, ip = out_port(a.type, e.from_port), in_port(b.type, e.to_port)
        if op is None or ip is None:
            out.append(issue('unknown_port', '없는 포트에 연결돼 있습니다. 연결 방향은 출력(오른쪽) → 입력(왼쪽)입니다.', '연결선을 삭제하고 다시 연결하세요.', [a.id, b.id], i))
            continue
        if ip['type'] != 'Any' and op['type'] != ip['type']:
            if b.type == 'N06':
                out.append(issue('N06_requires_N05', 'N06은 N05(기업별 거시 노출)의 결과만 받을 수 있습니다.', 'N05 출력 포트를 N06 입력에 연결하세요.', [a.id, b.id], i))
            else:
                out.append(issue('type_mismatch', f"자료형 불일치: {a.type}의 {op['label']}({op['type']}) → {b.type}의 {ip['label']}({ip['type']})",
                                 f"{b.type} 입력에는 {ip['type']} 자료형을 내보내는 노드를 연결하세요.", [a.id, b.id], i))
            continue
        key = (e.to_node, e.to_port)
        seen_inputs.setdefault(key, []).append(i)
        if len(seen_inputs[key]) > 1 and not ip['multiple']:
            out.append(issue('port_overfilled', f"{b.type}의 '{ip['label']}' 입력은 하나만 받을 수 있습니다.", '중복 연결선 하나를 삭제하세요.', [b.id], i))
        if e.from_node == e.to_node:
            out.append(issue('self_loop', '노드를 자기 자신에 연결할 수 없습니다.', '연결선을 삭제하세요.', [a.id], i))

    for n in doc.nodes:
        for p in SPECS[n.type]['inputs']:
            if p['required'] and (n.id, p['name']) not in seen_inputs:
                out.append(issue('missing_input', f"{n.type} {SPECS[n.type]['display_name']}: 필수 입력 '{p['label']}'({p['type']})이 연결되지 않았습니다.",
                                 f"{p['type']} 자료형을 내보내는 노드의 출력 포트를 연결하세요.", [n.id]))
        ins = SPECS[n.type]['inputs']
        if ins and any(p.get('auto') for p in ins) and not any(p['required'] for p in ins) \
                and not any((n.id, p['name']) in seen_inputs for p in ins):
            alt = ' 또는 '.join(f"'{p['label']}'({p['type']})" for p in ins if p.get('auto') or p['multiple'])
            out.append(issue('missing_input', f"{n.type} {SPECS[n.type]['display_name']}: 입력 {alt} 중 하나는 연결해야 합니다.",
                             '두 기준 기업은 T01, 다른 회사는 T11을 연결하세요.', [n.id]))

    try:
        topo_order(doc)
    except ValueError as e:
        stuck = e.args[1] if len(e.args) > 1 else []
        out.append(issue('cycle', '순환 연결이 있습니다. 실행 순서를 정할 수 없습니다.', '표시된 노드 사이의 연결선 하나를 삭제하세요.', stuck))

    # Cutoff: every official source in one run must share one valid reference time.
    sources = [n for n in doc.nodes if n.type == 'T01']
    cutoffs = {effective_cutoff(doc, n) for n in sources}
    if sources and '' in cutoffs:
        if len(cutoffs) > 1:
            out.append(issue('mixed_cutoff', '일부 T01만 기준시점이 지정돼 있습니다.', '모든 T01의 기준시점을 비우거나 같게 맞추세요.', [n.id for n in sources]))
        else:
            out.append(issue('cutoff_default', '기준시점이 비어 있어 실행 시각을 기준시점으로 씁니다.', '특정 시점으로 고정하려면 상단 기준시점을 입력하세요.',
                             [n.id for n in sources], severity='warning'))
    for c in cutoffs - {''}:
        try:
            instant(c)
        except ValueError:
            out.append(issue('cutoff_invalid', f'기준시점 형식 오류: {c}', '예: 2026-11-06T09:00:00+09:00 (시간대 포함)', [n.id for n in sources]))
    if len(cutoffs - {''}) > 1:
        out.append(issue('mixed_cutoff', '공식 원문 원천들의 기준시점이 서로 다릅니다.', '모든 T01의 기준시점을 비우거나 같게 맞추세요.', [n.id for n in sources]))

    # N02 scope must be covered by the connected N01 request.
    for n in doc.nodes:
        if n.type != 'N02':
            continue
        for e in doc.edges:
            if e.to_node == n.id and e.to_port == 'facts' and nodes.get(e.from_node) and nodes[e.from_node].type == 'N01':
                src = with_defaults('N01', nodes[e.from_node].config)
                ncfg = with_defaults('N02', n.config)
                comp, year = ncfg['company'], ncfg['base_year']
                if 'companies' in src and comp not in src['companies']:
                    out.append(issue('n02_scope', f'N02 기업 {comp}이 연결된 N01 조사 범위에 없습니다.', 'N01 설정에 해당 기업을 넣으세요.', [n.id, e.from_node]))
                if 'years' in src and year not in src['years']:
                    out.append(issue('n02_scope', f'N02 기준연도 {year}가 연결된 N01 조사 범위에 없습니다.', 'N01 설정에 해당 연도를 넣으세요.', [n.id, e.from_node]))
        for e in doc.edges:
            if e.to_node == n.id and e.to_port == 'assumptions' and check_assumptions and nodes.get(e.from_node):
                err = check_assumptions(nodes[e.from_node].config, n.config)
                if err:
                    out.append(issue('assumption_invalid', f'가정 입력 오류: {err}', 'T03 노드 설정에서 해당 값을 고치세요.', [e.from_node]))

    for n in doc.nodes:
        if SPECS[n.type]['implementation'] == 'not_connected':
            out.append(issue('not_connected_node', f"{n.type} {SPECS[n.type]['display_name']}은 미연결 노드입니다. 실행하면 '미연결'로 기록됩니다.",
                             '실행은 가능합니다. 결과에 값이 생기지 않습니다.', [n.id], severity='warning'))
    return out


def blocking(issues):
    return [i for i in issues if i['severity'] == 'error']
