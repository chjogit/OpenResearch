"""v0.12: T09·N03 비교기업, T10·N06 이 가정이라면."""
import hashlib, json, os, tempfile, unittest
from mrn import nodes as N
from mrn.market import peer_role
from mrn.engine import Engine
from mrn.store import Store
from mrn.workflow import WorkflowDoc, validate, blocking, topo_order

CUT = '2026-11-06T16:00:00+09:00'


def _h(p):
    with open(p, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _w(p, text, nl='\n'):
    with open(p, 'w', encoding='utf-8', newline=nl) as f:
        f.write(text)


def snapshot(root, tables):
    name = '20261106T200000+0900'; d = os.path.join(root, name); os.makedirs(d)
    meta = {}
    for t, recs in tables.items():
        p = os.path.join(d, t + '.jsonl'); _w(p, ''.join(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n' for r in recs))
        meta[t] = {'file': t + '.jsonl', 'rows': len(recs), 'sha256': _h(p), 'source_grade': 'x', 'query': 't', 'note': ''}
    mp = os.path.join(d, 'manifest.json'); _w(mp, json.dumps({'asof_kst': name, 'tables': meta}))
    _w(os.path.join(d, 'manifest.sha256'), _h(mp) + '  manifest.json\n'); _w(os.path.join(root, 'LATEST.txt'), name + '\n')
    return d


QE = ['2024-09-30', '2024-12-31', '2025-03-31', '2025-06-30', '2025-09-30', '2025-12-31', '2026-03-31', '2026-06-30', '2026-09-30']


def fin(t, rev, op, ni, a=200.0, l=50.0, e=150.0, cur='KRW', src='dart'):
    out = []
    for i, pe in enumerate(QE):
        g = 1.0 if i < 4 else 2.0          # 뒤 4분기는 매출 2배
        for m, v in (('revenue', rev * g), ('operating_income', op * g), ('net_income', ni * g), ('assets', a), ('liabilities', l), ('equity', e)):
            out.append({'ticker': t, 'period_end': pe, 'fiscal_year': int(pe[:4]), 'fiscal_q': 1 + (int(pe[5:7]) - 1) // 3, 'metric': m, 'amount': str(v), 'currency': cur, 'source': src})
    return out


def peer_tables():
    members = [('005930', '삼성전자', '264', 'KR'), ('MU', 'Micron', '3674', 'US'), ('000990', 'DB하이텍', '2611', 'KR'),
               ('042700', '한미반도체', '29271', 'KR'), ('357780', '솔브레인', '204', 'KR')]
    pg = [{'base_ticker': '000660', 'peer_group_id': 1, 'method': 'manual:반도체', 'created_at': 'x', 'ticker': t, 'name': n, 'rank': i + 1, 'reason': '팀 선정'}
          for i, (t, n, _, _) in enumerate(members)]
    pg += [{'base_ticker': '000660', 'peer_group_id': 2, 'method': 'krx_sector:전기·전자', 'created_at': 'x', 'ticker': 'LGES', 'name': 'LG에너지솔루션', 'rank': 1, 'reason': '업종'}]
    pc = [{'company_id': i, 'market': m, 'ticker': t, 'name': n, 'sector': s, 'krx_sector': None} for i, (t, n, s, m) in enumerate(members + [('000660', 'SK하이닉스', '2612', 'KR')])]
    fq = fin('000660', 100, 60, 80) + fin('005930', 100, 30, 25) + fin('MU', 100, 70, 50, cur='USD', src='sec_edgar') + fin('000990', 100, 10, 8) + fin('042700', 100, 40, 30)
    pp = [{'ticker': t, 'trade_date': '2026-11-05', 'close': '1', 'volume': 1, 'market_cap': str(c), 'source': 'fsc'} for t, c in (('000660', 900), ('005930', 1200), ('000990', 5))]
    return {'peer_group': pg, 'peer_company': pc, 'peer_financial_quarter': fq, 'peer_price_daily': pp}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.neon = os.path.join(self.tmp.name, 'neon'); os.makedirs(self.neon)
        self.old = os.environ.get('MODU_NODES_NEON_DIR'); os.environ['MODU_NODES_NEON_DIR'] = self.neon
        self.store = Store(os.path.join(self.tmp.name, 'db')); self.engine = Engine(self.store)

    def tearDown(self):
        if self.old is None: os.environ.pop('MODU_NODES_NEON_DIR', None)
        else: os.environ['MODU_NODES_NEON_DIR'] = self.old
        self.tmp.cleanup()

    def run_doc(self, d):
        w = WorkflowDoc.model_validate(d)
        self.assertEqual(blocking(validate(w, N.check_assumptions)), [])
        run = self.store.get_run('me', self.engine.start('me', w.model_dump(), topo_order(w), background=False))
        return run, {n['node_id']: n for n in run['nodes']}

    def pay(self, n):
        return self.store.get_packet(n['output_packet'])['payload']


class Peers(Base):
    def test_roles(self):
        self.assertEqual(peer_role({'ticker': 'MU', 'market': 'US', 'sector': '3674'}), 'chip')
        self.assertEqual(peer_role({'ticker': 'LRCX', 'market': 'US', 'sector': '3559'}), 'equipment')
        self.assertEqual(peer_role({'ticker': '042700', 'market': 'KR', 'sector': '29271'}), 'equipment')
        self.assertEqual(peer_role({'ticker': '357780', 'market': 'KR', 'sector': '204'}), 'materials')
        self.assertEqual(peer_role({'ticker': '005930', 'market': 'KR', 'sector': '264'}), 'chip')

    def test_n03_ranks_lag_and_notes(self):
        snapshot(self.neon, peer_tables())
        d = {'name': 'p', 'cutoff': CUT, 'nodes': [{'id': 't09', 'type': 'T09', 'config': {'company': '000660', 'snapshot': ''}}, {'id': 'n03', 'type': 'N03', 'config': {}}],
             'edges': [{'from_node': 't09', 'from_port': 'peers', 'to_node': 'n03', 'to_port': 'peers'}]}
        run, n = self.run_doc(d)
        self.assertEqual(n['t09']['status'], 'succeeded', n['t09']['reason'])
        tp = self.pay(n['t09'])
        self.assertEqual(tp['group']['method'], 'manual:반도체')               # 업종 자동 묶음은 쓰지 않음
        self.assertEqual(tp['financial_cutoff'], '2026-09-22')                # 16시 기준이면 11-06 확정, − 45일
        self.assertTrue(all(r['period_end'] <= '2026-09-22' for r in tp['financials']['000660']))   # 9월 말 분기는 아직 미공개로 봄
        p = self.pay(n['n03']); F = {f['name']: f for f in p['findings']}
        om = F['영업이익률(최근 4분기)']
        self.assertEqual(om['value'], 60.0); self.assertEqual(om['rank'], 2); self.assertEqual(om['of'], 4)   # MU 70 > 하이닉스 60 > 삼성 30 > DB 10
        self.assertEqual(F['매출 성장률(최근 4분기, 전년 대비)']['value'], 100.0)
        self.assertIn('참고: 순이익률 > 영업이익률', F)
        self.assertIn('3곳 중 2위', F['시가총액 순위 (국내 비교기업)']['claim'])
        self.assertIn('한미반도체', F['순위에서 뺀 비교기업']['claim']); self.assertIn('솔브레인', F['순위에서 뺀 비교기업']['claim'])
        txt = json.dumps(p, ensure_ascii=False)
        for bad in ('매수', '매도', '저평가', '고평가'):
            self.assertNotIn(bad, txt)


class Scen(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(N._scen('환율 ±5%, USD 세전손익 ±435,059백만원'), {'shock': 5.0, 'unit': '%', 'impact_mn': 435059.0, 'symmetric': True})
        self.assertEqual(N._scen('환율 ±10%, USD 세전손익 ±1,210,371백만원')['impact_mn'], 1210371.0)
        self.assertEqual(N._scen('금리 +1%p, 금융자산 +76,243 / 부채 −33,597 / 합계 +42,646백만원')['impact_mn'], 42646.0)
        r = N._scen('금리 +100bp, 향후 1년 세전순이익 −41,875백만원 (다른 변수 일정)')
        self.assertEqual((r['shock'], r['unit'], r['impact_mn']), (1.0, '%p', -41875.0))
        self.assertIsNone(N._scen('민감도 공시 없음'))


class N06Scenario(Base):
    def test_scaled_impacts(self):
        ser = [{'series_id': 'ECOS_USDKRW', 'name': '원/달러', 'source': 'ecos', 'frequency': 'D', 'unit': None},
               {'series_id': 'ECOS_BASE_RATE', 'name': '기준금리', 'source': 'ecos', 'frequency': 'M', 'unit': None}]
        obs = [{'series_id': 'ECOS_USDKRW', 'obs_date': '2025-12-30', 'value': '1400', 'source': 'ecos', 'collected_at': 'x'},
               {'series_id': 'ECOS_USDKRW', 'obs_date': '2026-11-05', 'value': '1470', 'source': 'ecos', 'collected_at': 'x'},
               {'series_id': 'ECOS_BASE_RATE', 'obs_date': '2025-12-01', 'value': '2.5', 'source': 'ecos', 'collected_at': 'x'},
               {'series_id': 'ECOS_BASE_RATE', 'obs_date': '2026-08-01', 'value': '3.0', 'source': 'ecos', 'collected_at': 'x'},
               {'series_id': 'ECOS_BASE_RATE', 'obs_date': '2026-10-01', 'value': '9.9', 'source': 'ecos', 'collected_at': 'x'}]   # 공개 시차로 아직 안 보임
        snapshot(self.neon, {'macro_series': ser, 'macro_obs': obs})
        d = {'name': 'm', 'cutoff': CUT, 'nodes': [{'id': 't01', 'type': 'T01', 'config': {}}, {'id': 'n05', 'type': 'N05', 'config': {}},
                                                  {'id': 't10', 'type': 'T10', 'config': {'snapshot': ''}}, {'id': 'n06', 'type': 'N06', 'config': {}}],
             'edges': [{'from_node': 't01', 'from_port': 'corpus', 'to_node': 'n05', 'to_port': 'corpus'},
                       {'from_node': 'n05', 'from_port': 'exposure', 'to_node': 'n06', 'to_port': 'exposure'},
                       {'from_node': 't10', 'from_port': 'macro', 'to_node': 'n06', 'to_port': 'macro'}]}
        run, n = self.run_doc(d)
        self.assertEqual(n['n06']['status'], 'succeeded', n['n06']['reason'])
        F = {f['name']: f for f in self.pay(n['n06'])['findings'] if 'name' in f}
        self.assertEqual(F['삼성전자 환율 영향 (이 가정이라면)']['value'], 435059)          # +5% / 5% 충격
        self.assertEqual(F['SK하이닉스 환율 영향 (이 가정이라면)']['value'], round(1210371 * 5 / 10))
        self.assertEqual(F['삼성전자 금리 영향 (이 가정이라면)']['value'], 21323)            # +0.5%p (9.9는 공개 시차로 제외)
        self.assertEqual(F['SK하이닉스 금리 영향 (이 가정이라면)']['value'], round(-41875 * 0.5))
        self.assertEqual(F['삼성전자 환율 영향 (이 가정이라면)']['kind'], 'derived')

    def test_without_t10_stays_partial(self):
        d = {'name': 'm', 'cutoff': CUT, 'nodes': [{'id': 't01', 'type': 'T01', 'config': {}}, {'id': 'n05', 'type': 'N05', 'config': {}}, {'id': 'n06', 'type': 'N06', 'config': {}}],
             'edges': [{'from_node': 't01', 'from_port': 'corpus', 'to_node': 'n05', 'to_port': 'corpus'},
                       {'from_node': 'n05', 'from_port': 'exposure', 'to_node': 'n06', 'to_port': 'exposure'}]}
        run, n = self.run_doc(d)
        self.assertEqual(n['n06']['status'], 'partial')
        self.assertIn('T10', n['n06']['reason'])


if __name__ == '__main__':
    unittest.main()
