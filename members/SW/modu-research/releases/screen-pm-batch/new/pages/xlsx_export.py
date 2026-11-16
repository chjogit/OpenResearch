"""엑셀(.xlsx) 내보내기 (PM 2026-11-15, 여러 회사 한꺼번에). 외부 패키지 없이 파이썬 표준 zipfile 로 만든다.
POST /export/xlsx/  {"filename": "...", "sheets": [{"name": "비교표", "rows": [[...], ...]}]}
- 화면이 이미 받은 엔진 결과를 표로 옮기기만 한다(새 계산·저장 없음). 숫자는 숫자 칸, 나머지는 글자 칸.
- 크기 제한: 시트 5개, 시트당 5,000줄 · 60칸, 칸당 글자 2,000자, 요청 3MB.
- 수식처럼 보이는 글자(= + - @ 로 시작)는 앞에 ' 를 붙여 엑셀이 수식으로 실행하지 않게 한다."""
import io
import json
import re
import zipfile
from xml.sax.saxutils import escape

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

MAX_BODY, MAX_SHEETS, MAX_ROWS, MAX_COLS, MAX_TEXT = 3_000_000, 5, 5000, 60, 2000
_BAD = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')


def _col(i):
    s = ''
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _cell(ref, v, bold=False):
    st = ' s="1"' if bold else ''
    if isinstance(v, bool) or v is None:
        v = '' if v is None else ('예' if v else '아니오')
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}"{st}><v>{v}</v></c>'
    t = _BAD.sub('', str(v))[:MAX_TEXT]
    if t[:1] in ('=', '+', '-', '@'):
        t = "'" + t
    return f'<c r="{ref}" t="inlineStr"{st}><is><t xml:space="preserve">{escape(t)}</t></is></c>'


def _sheet(rows):
    out = []
    for r, row in enumerate(rows[:MAX_ROWS]):
        cells = ''.join(_cell(f'{_col(c)}{r + 1}', v, bold=(r == 0)) for c, v in enumerate(list(row)[:MAX_COLS]))
        out.append(f'<row r="{r + 1}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            f'<sheetData>{"".join(out)}</sheetData></worksheet>')


def build_xlsx(sheets):
    sheets = sheets[:MAX_SHEETS] or [{'name': '시트1', 'rows': []}]
    names, used = [], set()
    for i, s in enumerate(sheets):
        n = re.sub(r'[\[\]:*?/\\]', ' ', str(s.get('name') or f'시트{i + 1}'))[:31] or f'시트{i + 1}'
        while n in used:
            n = (n[:28] + f'_{i + 1}')[:31]
        used.add(n); names.append(n)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + ''.join(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(len(names)))
                   + '</Types>')
        z.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + ''.join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)) + '</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + ''.join(f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>' for i in range(len(names)))
                   + f'<Relationship Id="rId{len(names) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('xl/styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<fonts count="2"><font><sz val="11"/><name val="맑은 고딕"/></font><font><b/><sz val="11"/><name val="맑은 고딕"/></font></fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
                   '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')
        for i, s in enumerate(sheets):
            z.writestr(f'xl/worksheets/sheet{i + 1}.xml', _sheet(list(s.get('rows') or [])))
    return buf.getvalue()


@csrf_exempt          # 상태를 바꾸지 않고 보낸 표를 파일로 돌려줄 뿐
@require_POST
def export_xlsx(request):
    if len(request.body) > MAX_BODY:
        return JsonResponse({'detail': '표가 너무 커요.'}, status=413)
    try:
        data = json.loads(request.body or b'{}')
        sheets = data['sheets']
        assert isinstance(sheets, list) and all(isinstance(s, dict) and isinstance(s.get('rows', []), list) for s in sheets)
    except (ValueError, KeyError, AssertionError, TypeError):
        return JsonResponse({'detail': '표 형식이 맞지 않아요.'}, status=400)
    name = re.sub(r'[^0-9A-Za-z가-힣_.-]+', '_', str(data.get('filename') or '모두의리서치'))[:80] or '모두의리서치'
    out = HttpResponse(build_xlsx(sheets), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    from urllib.parse import quote
    out['Content-Disposition'] = f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(name)}.xlsx"
    return out
