"""Shared input snapshot for both Agents, and a save guard that refuses failed verifications.

One read-only REPEATABLE READ transaction loads both Agents' inputs per company. The snapshot file can be
loaded by either notebook so both results carry the same report digest. Snapshot files contain stored DB
text: keep them in private_outputs/ and never commit them.
"""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sh_agents.data_inventory import Inventory, open_connection
from sh_agents.neon_agents import ALLOWED_SOURCES, load_company, serial, to_report
from sh_agents.research_contract import seal_report

SNAPSHOT_VERSION = 'shared-snapshot-1'
MOCK_NOTICE = '모의 입력: 실제 회사·시세 자료가 아닙니다. 코드 동작 확인용입니다.'


def snapshot_digest(snapshot):
    data = {k: v for k, v in snapshot.items() if k != 'digest'}
    return hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
                                     allow_nan=False).encode()).hexdigest()


def _seal(snapshot):
    snapshot = serial(snapshot)
    snapshot['digest'] = snapshot_digest(snapshot)
    return snapshot


def fetch_snapshot(tickers, start, end, *, market='KR', expected_role='agent_reader',
                   price_metadata_by_source=None, sources=ALLOWED_SOURCES):
    with open_connection(expected_role) as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        inv = Inventory(conn)
        companies = inv.companies(tickers, market)
        missing = set(tickers) - {c['ticker'] for c in companies}
        if missing:
            raise ValueError('종목 마스터 미등록: ' + ', '.join(sorted(missing)))
        bundles = [load_company(conn, inv, c, start, end, 'shared', sources=sources) for c in companies]
    return _seal({'snapshotVersion': SNAPSHOT_VERSION, 'dataMode': 'actual',
                  'createdAt': datetime.now(UTC).isoformat(), 'market': market, 'tickers': list(tickers),
                  'start': str(start), 'end': str(end), 'isolation': 'REPEATABLE READ READ ONLY',
                  'sources': list(sources), 'priceMetadataBySource': price_metadata_by_source or {},
                  'bundles': bundles})


def mock_snapshot(end='2026-10-28', days=30):
    """Clearly labelled synthetic input that exercises the same conversion and checks as real data."""
    from datetime import date, timedelta
    last = date.fromisoformat(end)
    trading = []
    d = last
    while len(trading) < days:
        if d.weekday() < 5:
            trading.append(d)
        d -= timedelta(days=1)
    trading.reverse()
    prices = []
    for n, day in enumerate(trading):
        close = 100 + (n % 7) - 3 + n * 0.5
        prices.append({'trade_date': day.isoformat(), 'open': close - 0.5, 'high': close + 1.5,
                       'low': close - 1.5, 'close': close, 'volume': 1000 + 25 * (n % 5), 'source': 'mock'})
    body = ('목 차\nI. 회사의 개요 ........ 1\nII. 사업의 내용 ........ 5\nIII. 재무에 관한 사항 ........ 30\n'
            'I. 회사의 개요\n모의 회사는 시험용으로 만든 가상의 회사입니다.\n'
            'II. 사업의 내용\n1. 사업의 개요\n모의 회사는 부품을 제조하여 완성품 업체에 공급합니다. '
            + '모의 문장입니다. ' * 40 + '\n'
            '2. 주요 제품 및 서비스\n주요 고객은 완성품 업체이며 경쟁사와 가격 경쟁을 합니다.\n'
            '3. 원재료 및 생산설비\n주요 원재료는 외부 공급업체에서 매입합니다.\n'
            'III. 재무에 관한 사항\n재무 내용은 이 모의 원문에 포함하지 않습니다.')
    meta = {'doc_id': 9001, 'source': 'mock', 'title': '사업보고서 (2025.12) [모의]',
            'url': 'https://example.invalid/mock-report', 'published_at': (last - timedelta(days=200)).isoformat()}
    chunks = [{**meta, 'chunk_id': 90010 + n, 'chunk_idx': n, 'content': line}
              for n, line in enumerate(body.split('\n'))]
    bundle = {'company': {'company_id': 0, 'ticker': 'MOCK01', 'name': '모의 기업', 'market': 'KR'},
              'start': trading[0].isoformat(), 'end': end, 'retrievedAt': f'{end}T00:00:00+00:00',
              'domain': 'shared', 'prices': prices, 'financials': [], 'chunks': chunks,
              'loadChecks': [{'table': t, 'status': 'ok', 'rows': n, 'domain': dom} for t, n, dom in [
                  ('core.price_daily', len(prices), 'technical_analysis'),
                  ('core.financial_quarter', 0, 'industry_business_model'),
                  ('rag.document', 1, 'industry_business_model'),
                  ('rag.chunk doc_id=9001', len(chunks), 'industry_business_model')]],
              'documentSelection': {'rule': '사업보고서 > 반기보고서 > 분기보고서 > IR', 'maxDocuments': 3,
                                    'candidates': 1, 'skipped': [],
                                    'selected': [{**{k: meta[k] for k in ['doc_id', 'title', 'source',
                                                                          'published_at']},
                                                  'documentKind': 'annual', 'priority': 0}]},
              'notice': MOCK_NOTICE}
    return _seal({'snapshotVersion': SNAPSHOT_VERSION, 'dataMode': 'synthetic', 'notice': MOCK_NOTICE,
                  'createdAt': f'{end}T00:00:00+00:00', 'market': 'KR', 'tickers': ['MOCK01'],
                  'start': bundle['start'], 'end': end, 'isolation': 'none (mock)', 'sources': ['mock'],
                  'priceMetadataBySource': {'mock': {'adjustment': 'unadjusted',
                                                     'sourceDescription': '모의 입력: 비조정 가격으로 생성'}},
                  'bundles': [bundle], 'mockTradingDates': [d.isoformat() for d in trading]})


def verify_snapshot(snapshot):
    if snapshot.get('snapshotVersion') != SNAPSHOT_VERSION:
        raise ValueError('지원하지 않는 스냅샷 형식입니다.')
    if snapshot.get('digest') != snapshot_digest(snapshot):
        raise ValueError('스냅샷 digest 불일치: 파일이 변경되었거나 손상되었습니다.')
    return snapshot


def reports_from_snapshot(snapshot):
    """Same snapshot -> same reports and digests for both Agents."""
    verify_snapshot(snapshot)
    reports = []
    for bundle in snapshot['bundles']:
        report = to_report(bundle, snapshot.get('priceMetadataBySource'), data_mode=snapshot['dataMode'])
        report['snapshotDigest'] = snapshot['digest']
        reports.append(seal_report(report))
    return reports


def save_snapshot(snapshot, folder):
    verify_snapshot(snapshot)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
    path = folder / f'snapshot_{stamp}_{snapshot["digest"][:12]}.json'
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    return path


def load_snapshot(path=None, folder=None):
    """Load a given file, or the newest snapshot_*.json in folder. Digest is verified."""
    if path is None:
        files = sorted(Path(folder).glob('snapshot_*.json')) if folder else []
        if not files:
            raise FileNotFoundError('저장된 공통 스냅샷이 없습니다. 먼저 Neon 조회 모드로 스냅샷을 만드세요.')
        path = files[-1]
    return verify_snapshot(json.loads(Path(path).read_text(encoding='utf-8'))), Path(path)


def save_results(folder, domain, payload, verifications):
    """Refuse to save when any Verifier result failed; returns (path or None, message)."""
    failed = [v for v in verifications if v.get('status') == 'failed']
    if failed:
        return None, f'저장 차단: Verifier failed {len(failed)}건. 오류를 수정하고 처음부터 다시 실행하세요.'
    if not verifications:
        return None, '저장 안 함: Verifier 결과가 없습니다.'
    folder = Path(folder) / domain
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime('%Y%m%d_%H%M%S')
    path = folder / f'results_{stamp}.json'
    path.write_text(json.dumps({**payload, 'verifications': verifications}, ensure_ascii=False, indent=2,
                               allow_nan=False), encoding='utf-8')
    return path, '저장 완료: ' + path.name
