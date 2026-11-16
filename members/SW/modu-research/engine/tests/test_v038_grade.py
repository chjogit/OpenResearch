"""v0.38 T2-2 공시 등급(제목만, 원문 호출 0): 규칙표 검사 · 대표 제목 · 정정 · 자회사 한 단계 낮춤 · 묶음 · 실제 사본 전체 분류."""
import glob
import json
import os
import tempfile
import unittest
from pathlib import Path

from mrn import dartdocs as D
from mrn import filing_grade as G

REAL = Path(__file__).resolve().parents[2] / '_sources' / 'neon' / '20261107T005213+0900' / 'disclosure'
CASES = [   # (제목, 등급, 상중하, 규칙)
    ('연결재무제표기준영업(잠정)실적(공정공시)', 1, None, 'prelim'),
    ('현금ㆍ현물배당결정', 1, None, 'dividend'),
    ('현금ㆍ현물배당을위한주주명부폐쇄(기준일)결정', 3, '하', 'dividend_record'),
    ('주요사항보고서(자기주식취득결정)', 1, None, 'buyback'),
    ('주요사항보고서(자기주식취득신탁계약해지결정)', 1, None, 'buyback_trust'),
    ('주식소각결정', 1, None, 'retire'),
    ('주요사항보고서(유상증자결정)', 1, None, 'rights_issue'),
    ('유상증자또는주식관련사채등의발행결과(자율공시)', 3, '하', 'rights_issue_notice'),
    ('매출액또는손익구조30%(대규모법인은15%)이상변경', 1, None, 'pl_change'),
    ('단일판매ㆍ공급계약체결', 2, None, 'contract'),
    ('단일판매ㆍ공급계약해지', 2, None, 'contract_cancel'),
    ('타법인주식및출자증권취득결정', 2, None, 'equity_invest'),
    ('연결재무제표기준영업실적등에대한전망(공정공시)', 2, None, 'outlook'),
    ('횡령ㆍ배임사실확인', 3, '상', 'embezzle'),
    ('소송등의제기ㆍ신청(경영권분쟁소송)', 3, '상', 'control_dispute'),
    ('최대주주변경', 3, '상', 'control_change'),
    ('최대주주등소유주식변동신고서(최대주주변경시)', 3, '상', 'control_change_holding'),
    ('최대주주등소유주식변동신고서', 3, '중', 'major_holder'),
    ('풍문또는보도에대한해명(미확정)', 3, '상', 'rumor_reply'),
    ('매매거래정지및정지해제(중요내용공시)', 3, '상', 'trading_halt'),
    ('임원ㆍ주요주주특정증권등소유상황보고서', 3, '하', 'insider_holding'),   # PM 결정(가): 하 + 묶음
    ('임원ㆍ주요주주특정증권등거래계획보고서', 3, '중', 'insider_plan'),
    ('주식등의대량보유상황보고서(일반)', 3, '중', 'block_holding'),
    ('대표이사(대표집행임원)변경(안내공시)', 3, '중', 'ceo_change'),
    ('기업가치제고계획예고(안내공시)', 3, '하', 'valueup_notice'),
    ('기업가치제고계획(자율공시)', 3, '중', 'valueup'),
    ('분기보고서 (2025.09)', 3, '중', 'periodic'),
    ('기업설명회(IR)개최(안내공시)', 3, '하', 'ir'),
    ('의결권대리행사권유참고서류', 3, '하', 'proxy'),
    ('기타경영사항(자율공시)(중대재해발생제외판정및종결알림)', 3, '하', 'fair_disclosure_misc'),
    ('중대재해발생', 3, '상', 'accident'),
]


class Rules(unittest.TestCase):
    def test_cases(self):
        for t, g, tier, rule in CASES:
            c = G.classify(t)
            self.assertEqual((c['grade'], c['tier'], c['rule']), (g, tier, rule), t)

    def test_correction_prefix_and_spaces(self):
        c = G.classify('[기재정정] 현금ㆍ현물 배당결정')
        self.assertEqual((c['grade'], c['rule'], c['corrected']), (1, 'dividend', True))
        self.assertFalse(G.classify('현금ㆍ현물배당결정')['corrected'])

    def test_subsidiary_one_step_down(self):
        c = G.classify('단일판매ㆍ공급계약체결(자회사의주요경영사항)')
        self.assertEqual((c['grade'], c['tier'], c['subsidiary']), (3, '하', True))
        self.assertTrue(c['label'].startswith('자회사 공시'))
        self.assertEqual(G.classify('횡령ㆍ배임사실확인(자회사의주요경영사항)')['tier'], '중')
        self.assertEqual(G.classify('감사보고서제출(종속회사의주요경영사항)')['tier'], '하')

    def test_unmatched_is_shown_not_guessed(self):
        c = G.classify('처음보는공시종류')
        self.assertEqual((c['grade'], c['tier'], c['rule'], c['label']), (3, '하', 'unmatched', '분류 규칙 없음'))

    def test_no_direction_words(self):
        cfg = json.loads(G.PATH.read_text(encoding='utf-8'))
        words = ('호재', '악재', '긍정', '부정적', '좋은', '나쁜', '매수 신호', '매도 신호', '주의 요망')
        text = ' '.join(r['label'] for r in cfg['rules']) + ' '.join(G.TIER_NOTE.values()) + ' '.join(G.GRADE_LABEL.values())
        for w in words:
            self.assertNotIn(w, text)

    def test_bad_rule_files_refused(self):
        with tempfile.TemporaryDirectory() as d:
            base = json.loads(G.PATH.read_text(encoding='utf-8'))
            for broken, msg in [({**base, 'rules': base['rules'] + [base['rules'][0]]}, '두 번'),
                                ({**base, 'rules': [{'id': 'x', 're': 'x', 'grade': 3, 'label': 'x'}]}, '상·중·하'),
                                ({**base, 'rules': [{'id': 'x', 're': 'x', 'grade': 1, 'tier': '상', 'label': 'x'}]}, '두지 않아요'),
                                ({**base, 'rules': [{'id': 'x', 're': 'x', 'grade': 4, 'label': 'x'}]}, '1·2·3')]:
                p = os.path.join(d, f'g{len(msg)}.json'); Path(p).write_text(json.dumps(broken, ensure_ascii=False), encoding='utf-8')
                with self.assertRaises(ValueError) as e:
                    G.load(p)
                self.assertIn(msg, str(e.exception))


def r(no, nm, t='005930', dt=None):
    return {'rcept_no': no, 'ticker': t, 'name': '삼성전자', 'report_nm': nm, 'rcept_dt': dt or f'{no[:4]}-{no[4:6]}-{no[6:8]}'}


class Board(unittest.TestCase):
    def test_bundle_and_sections(self):
        rows = [r('20261112000017', '임원ㆍ주요주주특정증권등소유상황보고서'), r('20261111000113', '현금ㆍ현물배당결정'),
                r('20261110000320', '임원ㆍ주요주주특정증권등소유상황보고서'), r('20261109000007', '임원ㆍ주요주주특정증권등소유상황보고서'),
                r('20261108000001', '임원ㆍ주요주주특정증권등소유상황보고서', t='000660'), r('20261107000001', '횡령ㆍ배임사실확인'),
                r('20261106000001', '기업설명회(IR)개최(안내공시)')]
        b = G.board(rows)
        self.assertEqual([x['rcept_no'] for x in b['computable']], ['20261111000113'])
        self.assertEqual([x['rule'] for x in b['상']], ['embezzle'])
        low = b['하']
        sam = [x for x in low if x.get('group') and x['ticker'] == '005930']
        self.assertEqual(len(sam), 1)
        self.assertEqual((sam[0]['count'], sam[0]['from'], sam[0]['to'], sam[0]['rcept_no']), (3, '2026-11-09', '2026-11-12', '20261112000017'))
        hy = [x for x in low if x['ticker'] == '000660']
        self.assertEqual(len(hy), 1); self.assertNotIn('count', hy[0]); self.assertNotIn('group', hy[0])   # 한 건은 묶지 않음(다른 회사와 섞지 않음)
        ir = [x for x in low if x['rule'] == 'ir']
        self.assertEqual(len(ir), 1); self.assertNotIn('group', ir[0])                 # 묶는 종류라도 한 건이면 묶지 않음
        self.assertEqual(sum(x.get('count', 1) for t in G.TIERS for x in b[t]) + len(b['computable']), len(rows))   # 빠진 줄 0


@unittest.skipUnless(REAL.is_dir(), '실제 Neon 사본이 있을 때만')
class RealCopy(unittest.TestCase):
    def test_every_title_classified(self):
        rows = [json.loads(l) for f in glob.glob(str(REAL / '*.jsonl')) for l in open(f, encoding='utf-8')]
        self.assertGreater(len(rows), 19000)
        cs = [G.classify(x['report_nm']) for x in rows]
        un = sum(c['rule'] == 'unmatched' for c in cs)
        self.assertLessEqual(un / len(rows), 0.005)                             # 규칙 없는 제목 0.5% 이하(지금 0건)
        top = sum(c['tier'] == '상' for c in cs) / len(rows)
        self.assertTrue(0.01 <= top <= 0.05, top)                              # 「꼭 알아 둘 공시」는 드물어야 화면이 덮이지 않음
        for x, c in zip(rows, cs):                                             # 엔진이 계산하는 종류는 모두 1등급
            k = D.classify(x['report_nm'])
            if k in ('retire', 'buyback_decision', 'dividend', 'prelim') and not c['subsidiary']:
                self.assertEqual(c['grade'], 1, x['report_nm'])


if __name__ == '__main__':
    unittest.main()
