"""엑셀 내보내기 시험 (PM 2026-11-15). 실행: python manage.py test pages.test_xlsx_export"""
import io, json, zipfile
from xml.dom import minidom

from django.test import TestCase

from .xlsx_export import build_xlsx


class Xlsx(TestCase):
    def test_workbook_is_valid_and_typed(self):
        data = build_xlsx([{'name': '비교표', 'rows': [['회사', '2025년 매출액'], ['삼성전자', 333605938], ['=HYPERLINK("x")', '<&>']]},
                           {'name': '모든/숫자:출처', 'rows': [['a']]}])
        z = zipfile.ZipFile(io.BytesIO(data))
        self.assertIsNone(z.testzip())
        for n in z.namelist():
            if n.endswith('.xml') or n.endswith('.rels'):
                minidom.parseString(z.read(n))                      # 모든 XML이 올바른지
        s1 = z.read('xl/worksheets/sheet1.xml').decode()
        self.assertIn('<v>333605938</v>', s1)                       # 숫자는 숫자 칸
        self.assertIn("'=HYPERLINK", s1)                             # 수식 실행 막기
        self.assertIn('&lt;&amp;&gt;', s1)
        wb = z.read('xl/workbook.xml').decode()
        self.assertIn('name="비교표"', wb); self.assertIn('name="모든 숫자 출처"', wb)

    def test_endpoint(self):
        r = self.client.post('/export/xlsx/', data=json.dumps({'filename': '모두의리서치_실적', 'sheets': [{'name': 'x', 'rows': [['a', 1]]}]}), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('spreadsheetml', r['Content-Type']); self.assertIn("UTF-8''", r['Content-Disposition'])
        self.assertEqual(self.client.post('/export/xlsx/', data='{"x":1}', content_type='application/json').status_code, 400)
        self.assertEqual(self.client.get('/export/xlsx/').status_code, 405)
