"""Versioned, source-linked research snapshots; no DB or publication authority."""
import hashlib
import json
from copy import deepcopy

DOMAINS = {'industry_business_model', 'technical_analysis'}


def content_digest(report):
    data = {k: v for k, v in report.items() if k not in {'digest', 'checks', 'approvals'}}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def validate_report(r):
    def check(ok, msg):
        if not ok:
            raise ValueError(msg)

    def index(items, key):
        out = {}
        for item in items:
            check(bool(item[key]) and item[key] not in out, 'Duplicate/empty ' + key)
            out[item[key]] = item
        return out

    check(r['schemaVersion'] == '1.0', 'Unsupported schema')
    check(type(r['contentRevision']) is int and r['contentRevision'] > 0, 'Invalid revision')
    check(bool(r['reportId']) and bool(r['question']) and bool(r['asOf']), 'Missing scope')
    check(r['dataMode'] in {'synthetic', 'actual'}, 'Invalid mode')
    check(r['status'] in {'draft', 'complete', 'partial', 'failed'}, 'Invalid report status')
    docs = index(r['documents'], 'documentId')
    evidence = index(r['evidence'], 'evidenceId')
    claims = index(r['claims'], 'claimId')
    calcs = index(r['calculations'], 'calculationId')
    nodes = index(r['map']['nodes'], 'nodeId')
    index(r['map']['edges'], 'edgeId')
    index(r['objections'], 'objectionId')
    for doc in docs.values():
        check(bool(doc['version']) and bool(doc['sha256']), 'Missing document version/hash')
        check(doc['dataMode'] == r['dataMode'], 'Mixed source modes')
    for e in evidence.values():
        check(e['documentId'] in docs, 'Unknown document')
        check(e['documentVersion'] == docs[e['documentId']]['version'], 'Stale document')
        check(bool(e['location']) and bool(e['excerpt']), 'Missing location/excerpt')
        check(e['verificationStatus'] in {'unverified', 'location_checked', 'support_checked'},
              'Invalid evidence status')
    for c in calcs.values():
        check(bool(c['formula']) and bool(c['methodVersion']), 'Missing calculation method')
        check(bool(c['inputEvidenceIds']), 'Missing calculation input')
        check(all(e in evidence for e in c['inputEvidenceIds']), 'Unknown calculation evidence')
    for c in claims.values():
        check(c['domain'] in DOMAINS, 'Invalid domain')
        check(type(c['claimVersion']) is int and c['claimVersion'] > 0, 'Invalid claim version')
        check(c['kind'] in {'fact', 'interpretation', 'forecast'}, 'Invalid claim kind')
        check(bool(c['text']) and bool(c['horizon']), 'Missing claim scope')
        check(c['assessment'] in {'provisional', 'withheld'}, 'Invalid assessment')
        for link in c['evidenceLinks']:
            check(link['evidenceId'] in evidence, 'Unknown evidence')
            check(link['relation'] in {'supports', 'opposes', 'context'}, 'Invalid relation')
        check(all(cid in calcs for cid in c['calculationIds']), 'Unknown calculation')

    def claim_ref(ref):
        check(ref['claimId'] in claims, 'Unknown claim')
        check(ref['claimVersion'] == claims[ref['claimId']]['claimVersion'], 'Stale claim')

    for edge in r['map']['edges']:
        check(edge['from'] in nodes and edge['to'] in nodes, 'Unknown map node')
        claim_ref(edge)
    for result in r['agentResults']:
        check(result['domain'] in DOMAINS, 'Invalid result domain')
        check(result['status'] in {'example', 'not_run', 'complete', 'partial', 'failed'}, 'Invalid agent status')
        for ref in result['claims']:
            claim_ref(ref)
            check(claims[ref['claimId']]['domain'] == result['domain'], 'Wrong owner')
    for relation in r['analysisRelations']:
        for ref in relation['claims']:
            claim_ref(ref)
    for obj in r['objections']:
        claim_ref(obj['target'])
        check(obj['targetReportRevision'] == r['contentRevision'], 'Stale objection')
        check(obj['status'] in {'received', 'in_review', 'processed', 'reopened'}, 'Invalid objection status')
    check(r['digest'] == content_digest(r), 'Digest mismatch')


def seal_report(report):
    result = deepcopy(report)
    result['digest'] = content_digest(result)
    validate_report(result)
    return result


def revise_claim(report, claim_id, *, text, reason):
    """New snapshot; old objections remain in history, never automatically retargeted."""
    validate_report(report)
    if not text.strip() or not reason.strip():
        raise ValueError('Revision text and reason required')
    r = deepcopy(report)
    c = next(c for c in r['claims'] if c['claimId'] == claim_id)
    r['history'].append(deepcopy(report))
    r['parentDigest'] = report['digest']
    r['contentRevision'] += 1
    r['changeReason'] = reason
    c.update(text=text, claimVersion=c['claimVersion'] + 1, assessment='withheld',
             evidenceLinks=[], calculationIds=[], missingInformation=['Changed claim needs new evidence review'])
    for edge in r['map']['edges']:
        if edge['claimId'] == claim_id:
            edge.update(claimVersion=c['claimVersion'], status='needs_review')
    for result in r['agentResults']:
        for ref in result['claims']:
            if ref['claimId'] == claim_id:
                ref['claimVersion'] = c['claimVersion']
                result['status'] = 'not_run'
    r.update(analysisRelations=[], objections=[], checks=[], approvals=[], status='draft')
    return seal_report(r)


def agent_view(report, domain):
    """Private input view, NOT an authorized public sharing snapshot."""
    validate_report(report)
    if domain not in DOMAINS:
        raise ValueError('Unsupported domain')
    result = deepcopy({k: report[k] for k in (
        'reportId', 'contentRevision', 'digest', 'dataMode', 'question', 'asOf',
        'documents', 'evidence', 'calculations', 'analysisRelations')})
    result['claims'] = deepcopy([c for c in report['claims'] if c['domain'] == domain])
    return result


def attach_agent_context(context, report):
    """Opt-in adapter for existing CH and persona message builders; original context unchanged."""
    result = deepcopy(context)
    for key, domain in [('industry_bm_data', 'industry_business_model'),
                        ('technical_data', 'technical_analysis')]:
        view = agent_view(report, domain)
        view['source'] = 'structured research snapshot ' + report['digest']
        result[key] = view
    return result
