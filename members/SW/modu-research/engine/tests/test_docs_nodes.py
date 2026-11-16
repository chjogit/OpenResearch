"""v0.14: T02 사업보고서 문장 검색 → N04 경쟁·점유율 발췌 (원문이 있는 PC에서만)."""
import os, tempfile, unittest
from pathlib import Path
from mrn import nodes as N
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order

SRC = os.environ.get('MODU_NODES_DART_FULL') or str(Path(__file__).resolve().parents[2] / '_sources' / 'dart_full')
HAVE = os.path.isdir(SRC)


@unittest.skipUnless(HAVE, 'dart_full sources not available')
class DocsNodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = {k: os.environ.get(k) for k in ('MODU_NODES_DART_FULL', 'MODU_NODES_RAG_DIR')}
        os.environ['MODU_NODES_DART_FULL'] = SRC
        os.environ['MODU_NODES_RAG_DIR'] = os.path.join(self.tmp.name, 'rag')
        self.store = Store(self.tmp.name)

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_share_table_lines_and_hashes(self):
        doc = {'name': 'x', 'cutoff': '2026-11-06T16:00:00+09:00',
               'nodes': [{'id': 't02', 'type': 'T02', 'config': {'company': '000660', 'preset': 'competition', 'k': 20}}, {'id': 'n04', 'type': 'N04', 'config': {}}],
               'edges': [{'from_node': 't02', 'from_port': 'docs', 'to_node': 'n04', 'to_port': 'docs'}]}
        w = WorkflowDoc.model_validate(doc)
        self.assertEqual(blocking(validate(w, N.check_assumptions)), [])
        rid = Engine(self.store).start('o', w.model_dump(), topo_order(w), background=False)
        n = {x['node_id']: x for x in self.store.get_run('o', rid)['nodes']}
        self.assertEqual(n['t02']['status'], 'succeeded', n['t02']['reason'])
        docs = self.store.get_packet(n['t02']['output_packet'])['payload']
        self.assertTrue(all(len(h['chunk_sha256']) == 64 and h['doc_sha256'] and h['rcept_no'] for h in docs['hits']))
        p = self.store.get_packet(n['n04']['output_packet'])['payload']
        rows = p['tables'][0]['rows']
        self.assertTrue(any('DRAM' in r[1] and '%' in r[1] for r in rows))

    def test_cutoff_before_report_holds(self):
        doc = {'name': 'x', 'cutoff': '2026-02-01T16:00:00+09:00',
               'nodes': [{'id': 't02', 'type': 'T02', 'config': {'company': '000660'}}], 'edges': []}
        w = WorkflowDoc.model_validate(doc)
        rid = Engine(self.store).start('o', w.model_dump(), topo_order(w), background=False)
        n = self.store.get_run('o', rid)['nodes'][0]
        self.assertEqual(n['status'], 'held')            # 2025 사업보고서(2026-03 접수)는 2026-02 기준시점에 쓸 수 없음
