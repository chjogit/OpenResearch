"""첫 채움 — 빈 PC에서 본인 KIS·DART 키만으로 엔진이 읽는 자료 사본을 처음 만든다 (연구용 · 재배포 계약 전).

누가 쓰나: 모두의리서치를 자기 PC에서 처음 돌려 보는 팀원. Neon(공용 DB) 접속이 없어도 된다.
무엇을 만드나: _sources/neon/<시각>/ 사본 하나 + LATEST.txt (엔진·가격 갱신·수급 갱신이 늘 읽는 형식 그대로)

받는 자료 (모두 공식 API, 본인 키)
 - 한국투자증권(KIS) 조회 전용: 회사 기본(이름·시장·업종·상장주식수) · 일별 시세(약 1년 반) · 투자자별 순매수(최근 약 30거래일) · 코스피/코스닥 지수
 - DART OpenAPI: 고유번호 · 공시 목록(2년) · 주요 재무 14계정(사업보고서 5년 + 분기·반기 2년) · 최대주주(3년) · 대량보유 보고
비워 두는 표: 뉴스·검색량·감성·대차잔고·공시 민감도·비교기업·거시 (엔진은 「자료 없음」으로 표시하고 나머지는 그대로 동작)

지키는 것
 - 이미 사본이 있으면 아무것도 쓰지 않고 멈춘다(PM PC처럼 자료가 있는 곳을 덮지 않음). 꼭 새로 만들려면 --new 를 붙인다
   (그때도 예전 사본은 지우지 않고, LATEST.txt 만 바꾼다. 되돌리기 = LATEST.txt 를 예전 이름으로).
 - 키는 환경 변수(엔진 local-env.cmd)의 KIS_APP_KEY · KIS_APP_SECRET · DART_API_KEY 만 쓴다. 키 값은 화면·파일·기록 어디에도 쓰지 않는다.
 - 다 쓴 뒤 엔진의 읽기 함수(해시·행 수 대조)로 다시 읽어 본 다음에만 LATEST.txt 를 쓴다.
 - 외국인 보유율: KIS 일자별의 「소진율」은 외국인 한도 종목(통신·전력·항공 등)에서 보유율과 다르다.
   오늘 보유수량÷상장주식수로 구한 보유율과 오늘 소진율이 0.01%p 안이면 소진율을 보유율로 쓰고, 다르면 비워 둔다(추정해서 넣지 않음).
 - 시가총액 = 오늘 상장주식수 × 그날 종가(그 사이 주식 수가 같다는 가정 — manifest 에 적어 둠).

쓰는 법: (엔진 가상환경 python) first_fill.py [--tickers 005930,000660] [--tickers-file 목록.txt] [--days 550] [--dry] [--new] [--check]
  --check : 키·폴더만 확인하고 끝냄(호출 없음)      --dry : 받기만 하고 쓰지 않음"""
import io, json, os, shutil, sys, time, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _e in (os.environ.get('MODU_ENGINE_DIR'), ROOT / 'modu-research-nodes', ROOT / 'engine'):   # PM PC 배치 · 공용 저장소 배치 모두
    if _e and (Path(_e) / 'mrn').is_dir():
        sys.path.insert(0, str(_e)); break
from mrn import market as M, surge as SG   # noqa: E402

KST = timezone(timedelta(hours=9))
TOOL = 'first_fill v1'
# 처음 해 보기 좋은 20곳(코스피 큰 회사, 업종 고르게). --tickers 로 바꿀 수 있음
STARTER = ['005930', '000660', '373220', '207940', '005380', '000270', '068270', '035420', '035720', '105560',
           '055550', '005490', '051910', '006400', '012330', '028260', '066570', '003550', '017670', '030200']
ACC = ['ifrs-full_Revenue', 'dart_OperatingIncomeLoss', 'ifrs-full_ProfitLoss', 'ifrs-full_ProfitLossAttributableToOwnersOfParent',
       'ifrs-full_CashFlowsFromUsedInOperatingActivities', 'ifrs-full_Assets', 'ifrs-full_Liabilities', 'ifrs-full_Equity',
       'ifrs-full_CurrentAssets', 'ifrs-full_CurrentLiabilities', 'ifrs-full_Inventories', 'ifrs-full_BasicEarningsLossPerShare',
       'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
       'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities']
DART_Q = {1: '11013', 2: '11012', 3: '11014', 4: '11011'}
Q_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
FLOW_IDS = {'revenue': ['ifrs-full_Revenue'], 'operating_income': ['dart_OperatingIncomeLoss'], 'net_income': ['ifrs-full_ProfitLoss']}
STOCK_IDS = {'assets': ['ifrs-full_Assets'], 'liabilities': ['ifrs-full_Liabilities'], 'equity': ['ifrs-full_Equity']}
DISC_TYPES = 'ABCDEFI'   # 정기·주요사항·발행·지분·기타·외부감사·거래소
# 공시 종류 이름 → event_type (팀 수집기 kic-agent-data 의 분류 규칙과 같게 맞춤)
EVENT_KEYWORDS = [
    ('유상증자', 'rights_issue'), ('무상증자', 'bonus_issue'), ('자기주식', 'buyback'), ('신주인수권부사채', 'bond_with_warrant'),
    ('전환사채', 'convertible_bond'), ('영업(잠정)실적', 'earnings_prelim'), ('잠정', 'earnings_prelim'), ('합병', 'merger'),
    ('분할', 'spin_off'), ('감자', 'capital_reduction'), ('배당', 'dividend'), ('단일판매', 'supply_contract'), ('소송', 'litigation'),
    ('횡령', 'embezzlement'), ('관리종목', 'delisting_risk'), ('상장폐지', 'delisting_risk'), ('조회공시요구', 'rumor_inquiry'),
    ('풍문또는보도', 'rumor_clarification'), ('매출액또는손익구조', 'earnings_change'), ('장래사업', 'guidance'),
    ('주식소각', 'stock_retirement'), ('주식교환', 'share_exchange'), ('타법인주식및출자증권취득', 'investment_acquisition'),
    ('영업양수', 'business_transfer'), ('영업양도', 'business_transfer'), ('금전대여', 'loan_decision'), ('신규시설투자', 'capex'),
    ('유형자산취득', 'capex'), ('전환청구권', 'conversion_exercise'), ('최대주주등소유주식변동', 'major_holder_change'),
    ('기업가치제고', 'value_up_plan'), ('기업설명회', 'ir_event'), ('주주총회', 'shareholders_meeting'), ('주주명부폐쇄', 'record_date'),
    ('감사보고서', 'audit_report'), ('기업지배구조', 'governance_report'), ('지속가능경영', 'esg_report'), ('수시공시의무', 'fair_disclosure'),
    ('기타경영사항', 'other_management'), ('사업보고서', 'annual_report'), ('반기보고서', 'half_year_report'),
    ('분기보고서', 'quarterly_report'), ('대량보유상황보고서', 'major_holding_report')]
QUERY = {   # 「어떻게 받았나」 한 줄
    'company': 'DART corpCode.xml(이름·고유번호) + KIS 주식현재가 FHKST01010100(시장·업종·상장주식수)',
    'coverage': '첫 채움 결과에서 기업별 개수·최근 날짜를 셈',
    'financial_quarter': 'financial_fact 의 분기·반기·3분기·사업보고서 누적값에서 분기 단독값 도출',
    'market_index_daily': 'KIS 국내업종 일별 FHKUP03500100 (0001 코스피 · 1001 코스닥)',
    'price_daily': 'KIS 국내주식 기간별 시세 FHKST03010100 (일봉, 원주가)',
    'investor_flow_daily': 'KIS 주식현재가 투자자 FHKST01010900 + 일자별 FHKST01010400 (소진율·거래량)',
    'financial_fact': 'DART fnlttSinglAcntAll (연결 CFS, 없으면 별도 OFS) 주요 14계정, SCE 제외',
    'disclosure': 'DART list.json (공시유형 A·B·C·D·E·F·I, 최근 2년)',
    'largest_holder': 'DART hyslrSttus (사업보고서 최근 3년)',
    'ownership_report': 'DART majorstock'}
# 표 → (기업별로 나눔?, source_grade, note). 엔진 사본(tool_version 4)과 같은 22개 표
TABLES = {
    'company': (False, 'official:kis+dart', '첫 채움: 이름·고유번호 DART, 시장·업종·상장주식수 KIS'),
    'coverage': (False, 'derived:count', '기업별 자료 개수·최근 날짜. 첫 채움판의 price_fsc 칸은 KIS 일별 시세 개수(금융위 시세 없음)'),
    'financial_quarter': (False, 'official:dart', '첫 채움: financial_fact(분기·반기·사업보고서 누적값)에서 분기 단독값 도출'),
    'market_index_daily': (False, 'official:kis', '첫 채움: 한국투자증권 업종(지수) 일별 — 코스피·코스닥만(연구용·재배포 계약 전)'),
    'price_daily': (True, 'official:kis', '첫 채움: 한국투자증권 일별 시세(kis, 원주가). 시가총액 = 오늘 상장주식수 × 종가(연구용·재배포 계약 전)'),
    'investor_flow_daily': (True, 'official:kis', '첫 채움: 한국투자증권 투자자별 매매(kis_investor) 최근 약 30거래일. 보유율은 소진율과 같을 때만(연구용·재배포 계약 전)'),
    'financial_fact': (True, 'official:dart_api', 'DART 정기보고서 재무(공시 API) — 주요 14개 계정'),
    'disclosure': (True, 'official:dart_list', 'DART 공시 목록'),
    'largest_holder': (True, 'official:dart_api', '최대주주 및 특수관계인'),
    'ownership_report': (True, 'official:dart_api', '대량보유(5%) 보고'),
}
EMPTY = {'stock_lending_daily': True, 'report_exposure': True, 'news_title': True, 'doc_daily_agg': True, 'mention_count': True,
         'reaction_pulse': False, 'peer_group': False, 'peer_company': False, 'peer_financial_quarter': False, 'peer_price_daily': False,
         'macro_series': False, 'macro_obs': False}
LOG = []


def say(s):
    LOG.append(s); print(s, flush=True)


def ymd(d):
    return d.replace('-', '') if isinstance(d, str) else d.strftime('%Y%m%d')


def iso8(s):
    s = ''.join(ch for ch in (s or '') if ch.isdigit())
    return f'{s[:4]}-{s[4:6]}-{s[6:8]}' if len(s) == 8 else None


def num(x):
    """'1,234' · '-' · '' → Decimal 또는 None"""
    s = str(x if x is not None else '').replace(',', '').strip()
    if s in ('', '-'):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def nstr(x):
    v = num(x)
    if v is None:
        return None
    return str(int(v)) if v == v.to_integral() else format(v, 'f')


def nint(x):
    v = num(x)
    return int(v) if v is not None else 0


# ---------------------------------------------------------------- DART
class Dart:
    BASE = 'https://opendart.fss.or.kr/api'
    SPACING = 0.15

    def __init__(self, key, fetch=None, sleep=time.sleep):
        self.key, self.sleep, self.calls = key, sleep, 0
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'modu-research-first-fill'}), timeout=30) as r:
            return r.read()

    def raw(self, path, params):
        self.sleep(self.SPACING); self.calls += 1
        try:
            return self.fetch(f'{self.BASE}/{path}?' + urllib.parse.urlencode({'crtfc_key': self.key, **params}))
        except Exception as e:   # 주소(키 포함)가 오류 글에 섞여 나오지 않도록 종류와 요약만
            msg = str(getattr(e, 'reason', '') or getattr(e, 'code', '') or type(e).__name__)
            raise RuntimeError(f'DART {path} 연결 실패: {msg.replace(self.key, "***")[:80]}') from None

    def full(self, path, params):
        js = json.loads(self.raw(path, params).decode('utf-8'))
        st = str(js.get('status'))
        if st == '013':          # 조회된 데이터 없음
            return {'list': [], 'total_count': 0}
        if st != '000':
            raise RuntimeError(f"DART {st} {js.get('message', '')[:60]}")
        return js

    def json(self, path, params):
        return self.full(path, params).get('list') or []

    def corp_codes(self):
        """{종목코드: (고유번호, 회사명)}"""
        z = zipfile.ZipFile(io.BytesIO(self.raw('corpCode.xml', {})))
        root = ET.fromstring(z.read(z.namelist()[0]))
        out = {}
        for it in root.iter('list'):
            sc = (it.findtext('stock_code') or '').strip()
            if sc:
                out[sc] = ((it.findtext('corp_code') or '').strip(), (it.findtext('corp_name') or '').strip())
        return out


def classify(report_nm):
    name = ''.join((report_nm or '').split())
    for kw, ev in EVENT_KEYWORDS:
        if kw in name:
            return ev
    return None


def dart_disclosures(dart, t, cc, start, end, now_iso):
    """공시 목록. DART 는 한 번 조회에 1,000건(100건 × 10쪽)까지만 주는 것으로 보임(삼성전자 지분공시 2년 실측 1,000건에서 멈춤)
    → 한 구간의 전체 건수(total_count)가 받은 건수보다 많으면 기간을 반으로 나눠 다시 받는다."""
    rows = {}

    def take(ty, bgn, fin):
        got, page, total = [], 1, None
        while page <= 10:
            js = dart.full('list.json', {'corp_code': cc, 'bgn_de': ymd(bgn), 'end_de': ymd(fin), 'pblntf_ty': ty, 'page_no': page, 'page_count': 100})
            lst = js.get('list') or []
            total = int(js.get('total_count') or len(lst)) if total is None else total
            got += lst
            if len(lst) < 100 or len(got) >= total:
                break
            page += 1
        if total is not None and len(got) < total and bgn < fin:          # 상한에 걸림 → 기간 반으로
            mid = date.fromisoformat(bgn) + (date.fromisoformat(fin) - date.fromisoformat(bgn)) // 2
            take(ty, bgn, mid.isoformat()); take(ty, (mid + timedelta(days=1)).isoformat(), fin)
            return
        for it in got:
            d = iso8(it.get('rcept_dt')); no = (it.get('rcept_no') or '').strip()
            if d and no and no not in rows:
                rows[no] = {'ticker': t, 'rcept_no': no, 'report_nm': (it.get('report_nm') or '').strip(), 'rcept_dt': d,
                            'filer': (it.get('flr_nm') or '').strip(), 'category': ty, 'event_type': classify(it.get('report_nm')),
                            'url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={no}', 'source': 'dart', 'collected_at': now_iso}
    for ty in DISC_TYPES:
        take(ty, start, end)
    return sorted(rows.values(), key=lambda r: (r['rcept_dt'], r['rcept_no']))


def dart_financials(dart, t, cc, years_annual, years_q, now_iso):
    """사업보고서(연결 → 없으면 별도) 5년 + 분기·반기 2년, 주요 14계정"""
    jobs = [(y, '11011') for y in years_annual] + [(y, c) for y in years_q for c in ('11013', '11012', '11014')]
    rows = []
    for y, code in jobs:
        got, fs = [], None
        for fs_div in ('CFS', 'OFS'):
            got = dart.json('fnlttSinglAcntAll.json', {'corp_code': cc, 'bsns_year': str(y), 'reprt_code': code, 'fs_div': fs_div})
            if got:
                fs = fs_div; break
        seen = set()
        for it in got:
            aid, sj = (it.get('account_id') or ''), (it.get('sj_div') or '')
            if aid not in ACC or sj == 'SCE' or (aid, sj) in seen:
                continue
            seen.add((aid, sj))
            rows.append({'ticker': t, 'fiscal_year': y, 'report_code': code, 'fs_div': fs, 'sj_div': sj, 'account_id': aid,
                         'account_nm': (it.get('account_nm') or '').strip(), 'amount': nstr(it.get('thstrm_amount')),
                         'amount_ytd': nstr(it.get('thstrm_add_amount')), 'currency': it.get('currency') or 'KRW',
                         'rcept_no': it.get('rcept_no'), 'period_end': None, 'source': 'dart', 'collected_at': now_iso})
    return rows


def derive_quarters(t, facts):
    """분기 단독값: 1Q=1분기 누적, 2Q=반기−1Q, 3Q=3분기−반기, 4Q=사업보고서−3분기. 잔액 항목은 그 보고서 값. 12월 결산 가정"""
    idx = {}
    for f in facts:
        idx.setdefault((f['fiscal_year'], f['report_code'], f['account_id']), f)

    def pick(y, code, ids, field):
        for i in ids:
            f = idx.get((y, code, i))
            if f is not None and f.get(field) is not None:
                return Decimal(f[field]), f
        return None, None
    out = {}
    for y in sorted({f['fiscal_year'] for f in facts}):
        for metric, ids in FLOW_IDS.items():
            ytd = {}
            for q, code in DART_Q.items():
                v, _ = pick(y, code, ids, 'amount' if q == 4 else 'amount_ytd')
                if v is None and q == 1:
                    v, _ = pick(y, code, ids, 'amount')
                ytd[q] = v
            for q in (1, 2, 3, 4):
                if ytd[q] is None or (q > 1 and ytd[q - 1] is None):
                    continue
                pe = date(y, *Q_END[q]).isoformat()
                out[(pe, metric)] = {'ticker': t, 'period_end': pe, 'fiscal_year': y, 'fiscal_q': q, 'metric': metric,
                                     'amount': str(ytd[q] if q == 1 else ytd[q] - ytd[q - 1]), 'currency': 'KRW', 'source': 'dart'}
        for q, code in DART_Q.items():
            for metric, ids in STOCK_IDS.items():
                v, _ = pick(y, code, ids, 'amount')
                if v is not None:
                    pe = date(y, *Q_END[q]).isoformat()
                    out[(pe, metric)] = {'ticker': t, 'period_end': pe, 'fiscal_year': y, 'fiscal_q': q, 'metric': metric,
                                         'amount': str(v), 'currency': 'KRW', 'source': 'dart'}
    return sorted(out.values(), key=lambda r: (r['period_end'], r['metric']))


def dart_holders(dart, t, cc, years, now_iso):
    rows = []
    for y in years:
        for it in dart.json('hyslrSttus.json', {'corp_code': cc, 'bsns_year': str(y), 'reprt_code': '11011'}):
            nm = (it.get('nm') or '').strip()
            if nm:
                rows.append({'ticker': t, 'fiscal_year': y, 'report_code': '11011', 'holder': nm, 'stock_kind': (it.get('stock_knd') or '').strip(),
                             'relate': (it.get('relate') or '').strip() or None, 'end_qty': nstr(it.get('trmend_posesn_stock_co')),
                             'stake_rt': nstr(it.get('trmend_posesn_stock_qota_rt')), 'begin_rt': nstr(it.get('bsis_posesn_stock_qota_rt')),
                             'settle_dt': iso8(it.get('stlm_dt')), 'rcept_no': (it.get('rcept_no') or '').strip() or None, 'collected_at': now_iso})
    return rows


def dart_ownership(dart, t, cc, now_iso):
    rows = []
    for it in dart.json('majorstock.json', {'corp_code': cc}):
        no = (it.get('rcept_no') or '').strip()
        if no:
            rows.append({'ticker': t, 'rcept_no': no, 'repror': (it.get('repror') or '').strip(), 'rcept_dt': iso8(it.get('rcept_dt')),
                         'report_tp': (it.get('report_tp') or '').strip() or None, 'report_resn': (it.get('report_resn') or '').strip() or None,
                         'stkqy': nstr(it.get('stkqy')), 'stkrt': nstr(it.get('stkrt')), 'stkrt_irds': nstr(it.get('stkrt_irds')),
                         'ctr_stkrt': nstr(it.get('ctr_stkrt')), 'collected_at': now_iso})
    return sorted(rows, key=lambda r: (r['rcept_dt'] or '', r['rcept_no']))


# ---------------------------------------------------------------- KIS (조회만)
def kis_list(kis, path, tr_id, params, key='output2'):
    tok = kis.token()
    kis.sleep(SG.SPACING); kis._count()
    st, js = kis.http('GET', SG.SERVER + path + '?' + urllib.parse.urlencode(params),
                      {'authorization': 'Bearer ' + tok, 'appkey': kis.key, 'appsecret': kis.secret, 'tr_id': tr_id, 'custtype': 'P'}, None)
    if st != 200 or str((js or {}).get('rt_cd')) != '0':
        raise SG.KisError('kis_' + str((js or {}).get('msg_cd') or st), f"KIS 조회 실패(HTTP {st} {(js or {}).get('msg_cd', '')})")
    out = js.get(key)
    return out if isinstance(out, list) else ([out] if out else [])


def kis_daily(kis, path, tr_id, base, start, end, datekey='stck_bsop_date', valkey='stck_clpr'):
    """한 번에 100건까지 — 모자라면 앞쪽으로 나눠 받음 → {YYYY-MM-DD: 행}"""
    out, hi = {}, end
    for _ in range(12):
        rows = kis_list(kis, path, tr_id, {**base, 'FID_INPUT_DATE_1': ymd(start), 'FID_INPUT_DATE_2': ymd(hi), 'FID_PERIOD_DIV_CODE': 'D'})
        got = [r for r in rows if r.get(datekey) and (r.get(valkey) or '0') not in ('0', '')]
        for r in got:
            out[iso8(r[datekey])] = r
        if len(rows) < 100 or not got:
            break
        hi = (date.fromisoformat(min(out)) - timedelta(days=1)).isoformat()
        if hi < start:
            break
    return {d: r for d, r in out.items() if start <= d <= end}


def kis_company(kis, t):
    o = kis_list(kis, '/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
                 {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t}, key='output')
    return o[0] if o else {}


def kis_prices(kis, t, start, end, shares, now_iso):
    k = kis_daily(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice', 'FHKST03010100',
                  {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t, 'FID_ORG_ADJ_PRC': '1'}, start, end)   # 1 = 원주가
    rows = []
    for d in sorted(k):
        r = k[d]; c = nint(r.get('stck_clpr'))
        rows.append({'ticker': t, 'trade_date': d, 'open': str(nint(r.get('stck_oprc')) or c), 'high': str(nint(r.get('stck_hgpr')) or c),
                     'low': str(nint(r.get('stck_lwpr')) or c), 'close': str(c), 'volume': nint(r.get('acml_vol')),
                     'trade_value': str(nint(r.get('acml_tr_pbmn'))), 'market_cap': str(shares * c) if shares else None,
                     'source': 'kis', 'collected_at': now_iso})
    return rows


def kis_flows(kis, t, upto, hold_ok, now_iso):
    inv = kis_list(kis, '/uapi/domestic-stock/v1/quotations/inquire-investor', 'FHKST01010900',
                   {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t}, key='output')
    day = kis_list(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-price', 'FHKST01010400',
                   {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': t, 'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '1'}, key='output')
    inv = {iso8(r['stck_bsop_date']): r for r in inv if r.get('stck_bsop_date')}
    day = {iso8(r['stck_bsop_date']): r for r in day if r.get('stck_bsop_date')}
    rows = []
    for d in sorted(x for x in inv if x <= upto and x in day):
        k, y = inv[d], day[d]
        if all(k.get(f) in (None, '') for f in ('prsn_ntby_qty', 'frgn_ntby_qty', 'orgn_ntby_qty')):
            continue                                  # 장 마감 전 오늘 줄(값 비어 있음)
        hp = num(y.get('hts_frgn_ehrt'))
        rows.append({'ticker': t, 'trade_date': d, 'individual_net_qty': nint(k.get('prsn_ntby_qty')),
                     'foreign_net_qty': nint(k.get('frgn_ntby_qty')), 'institution_net_qty': nint(k.get('orgn_ntby_qty')),
                     'foreign_hold_pct': f'{hp.quantize(Decimal("0.0001"))}' if (hold_ok and hp is not None) else None,
                     'volume': nint(y.get('acml_vol')), 'source': 'kis_investor', 'collected_at': now_iso})
    return rows


def hold_check(o):
    """오늘 보유율(보유수량 ÷ 상장주식수)과 오늘 소진율이 0.01%p 안이면 True"""
    q, n, e = num(o.get('frgn_hldn_qty')), num(o.get('lstn_stcn')), num(o.get('hts_frgn_ehrt'))
    if not q or not n or e is None:
        return False
    return abs(q / n * 100 - e) <= Decimal('0.0101')


# ---------------------------------------------------------------- 쓰기
def sha(p):
    return M._sha(Path(p))


def write_jsonl(p, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w', encoding='utf-8', newline='\n') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + '\n')


def coverage(t, data):
    def cnt(tab, key):
        rows = data.get(tab, {}).get(t, [])
        vals = [str(r.get(key))[:10] for r in rows if r.get(key) is not None]
        return {'n': len(rows), 'x': max(vals) if vals else None} if rows else None
    c = {'ticker': t}
    for k, v in (('price_fsc', cnt('price_daily', 'trade_date')), ('flow', cnt('investor_flow_daily', 'trade_date')),
                 ('disclosure', cnt('disclosure', 'rcept_dt')), ('holder', cnt('largest_holder', 'fiscal_year')),
                 ('ownership', cnt('ownership_report', 'rcept_dt'))):
        if v:
            c[k] = v
    ann = [r for r in data.get('financial_fact', {}).get(t, []) if r['report_code'] == '11011']
    if ann:
        c['fin_annual'] = {'n': len(ann), 'x': str(max(r['fiscal_year'] for r in ann))}
    fq = [r for r in data.get('financial_quarter_rows', []) if r['ticker'] == t]
    if fq:
        c['fin_quarter'] = {'n': len(fq), 'x': max(r['period_end'] for r in fq)}
    return c


def build(dst_parent, stamp, data, companies, index_rows, meta):
    tmp = dst_parent / (stamp + '.part')
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    tickers = [c['ticker'] for c in companies]
    man = {'asof_kst': stamp, 'db': 'first_fill (KIS·DART 직접, 연구용)', 'tool_version': 4, 'tickers': tickers, 'read_only': 'n/a',
           'tables': {}, 'refresh': [], 'first_fill': meta}
    fq_rows = data.get('financial_quarter_rows', [])
    flat = {'company': companies, 'financial_quarter': fq_rows, 'market_index_daily': index_rows,
            'coverage': [coverage(t, data) for t in tickers]}
    for name, (part, grade, note) in TABLES.items():
        if part:
            parts = {}
            for t in tickers:
                rows = data.get(name, {}).get(t) or []
                if not rows:
                    continue
                rel = f'{name}/{t}.jsonl'; write_jsonl(tmp / rel, rows)
                parts[t] = {'file': rel, 'rows': len(rows), 'sha256': sha(tmp / rel)}
            (tmp / name).mkdir(exist_ok=True)
            man['tables'][name] = {'partitioned': True, 'parts': parts, 'rows': sum(p['rows'] for p in parts.values()),
                                   'source_grade': grade, 'note': note}
        else:
            rows = flat[name]; rel = name + '.jsonl'; write_jsonl(tmp / rel, rows)
            man['tables'][name] = {'file': rel, 'rows': len(rows), 'sha256': sha(tmp / rel), 'source_grade': grade, 'note': note}
    for name, part in EMPTY.items():
        note = '첫 채움에서 받지 않음(팀 수집기·Neon 자료). 엔진은 「자료 없음」으로 표시'
        if part:
            (tmp / name).mkdir(exist_ok=True)
            man['tables'][name] = {'partitioned': True, 'parts': {}, 'rows': 0, 'source_grade': 'none', 'note': note}
        else:
            rel = name + '.jsonl'; write_jsonl(tmp / rel, [])
            man['tables'][name] = {'file': rel, 'rows': 0, 'sha256': sha(tmp / rel), 'source_grade': 'none', 'note': note}
    for name, m in man['tables'].items():
        m['query'] = QUERY.get(name, '(첫 채움에서 받지 않음)')   # 엔진이 출처 설명에 보여 주는 칸(Neon 사본의 SQL 자리)
    mp = tmp / 'manifest.json'
    mp.write_text(json.dumps(man, ensure_ascii=False), encoding='utf-8')
    (tmp / 'manifest.sha256').write_bytes(f'{sha(mp)}  manifest.json\n'.encode())
    dst = dst_parent / stamp
    tmp.rename(dst)
    # 엔진 방식 그대로 다시 읽어 확인
    m2 = M.load_manifest(dst)
    for name, meta2 in m2['tables'].items():
        if meta2.get('partitioned'):
            for t in meta2['parts']:
                M.read_rows(dst, m2, name, t)
        else:
            M.read_table(dst, m2, name)
    return dst


# ---------------------------------------------------------------- 실행
def tickers_from(argv):
    if '--tickers' in argv:
        return [x.strip() for x in argv[argv.index('--tickers') + 1].split(',') if x.strip()]
    if '--tickers-file' in argv:
        txt = Path(argv[argv.index('--tickers-file') + 1]).read_text(encoding='utf-8')
        return [x.strip() for x in txt.replace(',', '\n').splitlines() if x.strip() and not x.strip().startswith('#')]
    return list(STARTER)


def last_closed(now):
    d = now.date()
    if d.weekday() >= 5 or (now.hour, now.minute) < (16, 0):
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def main(argv, kis=None, dart=None, now=None):
    now = now or datetime.now(KST)
    now_iso = now.astimezone(timezone.utc).isoformat()
    dry, new, check = '--dry' in argv, '--new' in argv, '--check' in argv
    days = int(argv[argv.index('--days') + 1]) if '--days' in argv else 550
    tickers = tickers_from(argv)
    bad = [t for t in tickers if not (len(t) == 6 and t.isalnum())]
    if bad:
        say(f'종목코드 6자리가 아닌 값이 있어요: {bad[:5]}'); return 2
    nd = M.neon_dir()
    say(f'자료 폴더: {nd}')
    if (nd / 'LATEST.txt').exists() and not new:
        say('이미 자료 사본이 있어요(LATEST.txt). 덮지 않으려고 멈춥니다. 이미 있는 사본은 가격·수급 갱신으로 최신화하세요.')
        say('정말 새로 만들려면 --new 를 붙이세요(예전 사본은 지우지 않고 LATEST.txt 만 바뀝니다).')
        return 3
    cfg = SG.config()
    dkey = (os.environ.get('DART_API_KEY') or '').strip()
    miss = [n for n, v in (('KIS_APP_KEY', cfg['key']), ('KIS_APP_SECRET', cfg['secret']), ('DART_API_KEY', dkey)) if not v]
    if miss and (kis is None or dart is None):
        say('키가 없어요: ' + ', '.join(miss) + ' — engine\\local-env.cmd 에 본인 키를 넣고 다시 실행하세요(안내서 2단계).')
        return 2
    say(f'키 확인: KIS·DART 모두 있음(값은 표시하지 않음) · 회사 {len(tickers)}곳 · 시세 약 {days}일')
    if check:
        say('--check: 확인만 하고 끝냅니다.'); return 0
    kis = kis or SG.Kis(cfg['key'], cfg['secret'])
    dart = dart or Dart(dkey)
    end = last_closed(now); start = (date.fromisoformat(end) - timedelta(days=days)).isoformat()
    y = now.year
    years_annual = [y - i for i in range(1, 6)]               # 사업보고서 5년
    years_q = [y - 1, y]                                       # 분기·반기 2년
    say('DART 고유번호 목록 받는 중…')
    codes = dart.corp_codes()
    data = {k: {} for k in TABLES}
    companies, fails, holdblank = [], {}, []
    for i, t in enumerate(tickers, 1):
        cc, cname = codes.get(t, (None, None))
        try:
            o = kis_company(kis, t)
        except Exception as e:
            fails[t] = f'KIS 회사 정보: {str(e)[:80]}'; continue
        shares = nint(o.get('lstn_stcn')) or None
        name = cname or (o.get('hts_kor_isnm') or '').strip() or t
        companies.append({'company_id': i, 'market': 'KR', 'ticker': t, 'name': name, 'corp_code': cc, 'sector': None, 'sector_desc': None,
                          'krx_sector': (o.get('bstp_kor_isnm') or '').strip() or None,
                          'index_tags': [x for x in [(o.get('rprs_mrkt_kor_name') or '').strip()] if x],
                          'shares_outstanding': str(shares) if shares else None, 'shares_asof': end})
        step = '시세'
        try:
            data['price_daily'][t] = kis_prices(kis, t, start, end, shares, now_iso)
            step = '수급'
            ok = hold_check(o)
            if not ok:
                holdblank.append(t)
            data['investor_flow_daily'][t] = kis_flows(kis, t, end, ok, now_iso)
            if cc:
                step = '공시 목록'
                data['disclosure'][t] = dart_disclosures(dart, t, cc, (date.fromisoformat(end) - timedelta(days=730)).isoformat(), now.date().isoformat(), now_iso)
                step = '재무'
                data['financial_fact'][t] = dart_financials(dart, t, cc, years_annual, years_q, now_iso)
                step = '최대주주'
                data['largest_holder'][t] = dart_holders(dart, t, cc, [y - 1, y - 2, y - 3], now_iso)
                step = '대량보유'
                data['ownership_report'][t] = dart_ownership(dart, t, cc, now_iso)
            else:
                fails[t] = 'DART 고유번호 없음(DART 자료 건너뜀)'
        except Exception as e:
            fails[t] = f'{step}: {type(e).__name__}: {str(e)[:80]}'
        say(f'  {i}/{len(tickers)} {t} {name}: 시세 {len(data["price_daily"].get(t, []))} · 수급 {len(data["investor_flow_daily"].get(t, []))}'
            f' · 공시 {len(data["disclosure"].get(t, []))} · 재무 {len(data["financial_fact"].get(t, []))}' + (f' · 문제 {fails[t]}' if t in fails else ''))
    data['financial_quarter_rows'] = [r for t in data['financial_fact'] for r in derive_quarters(t, data['financial_fact'][t])]
    index_rows = []
    for sym, (code, nm) in {'^KS11': ('0001', '코스피'), '^KQ11': ('1001', '코스닥')}.items():
        try:
            k = kis_daily(kis, '/uapi/domestic-stock/v1/quotations/inquire-daily-indexchartprice', 'FHKUP03500100',
                          {'FID_COND_MRKT_DIV_CODE': 'U', 'FID_INPUT_ISCD': code}, start, end, valkey='bstp_nmix_prpr')
        except Exception as e:
            fails[sym] = f'지수: {str(e)[:80]}'; continue
        for d in sorted(k):
            r = k[d]; c = r['bstp_nmix_prpr']
            index_rows.append({'symbol': sym, 'name': nm, 'trade_date': d, 'open': r.get('bstp_nmix_oprc') or c, 'high': r.get('bstp_nmix_hgpr') or c,
                               'low': r.get('bstp_nmix_lwpr') or c, 'close': c, 'volume': nint(r.get('acml_vol')), 'source': 'kis', 'collected_at': now_iso})
    good = [c for c in companies if data['price_daily'].get(c['ticker'])]
    say(f'받기 끝: 회사 {len(good)}/{len(tickers)}곳 · 지수 {len(index_rows)}행 · KIS 호출 {kis.calls}회 · DART 호출 {dart.calls}회')
    if holdblank:
        say(f'  외국인 보유율을 비운 회사 {len(holdblank)}곳(소진율 ≠ 보유율, 외국인 한도 종목 등): {", ".join(holdblank[:10])}')
    for t, why in list(fails.items())[:15]:
        say(f'  문제 {t}: {why}')
    if not good:
        say('시세를 받은 회사가 하나도 없어 아무것도 쓰지 않았어요. 키와 인터넷 연결을 확인하세요.'); return 4
    if dry:
        say('--dry: 아무것도 쓰지 않았어요.'); return 0
    meta = {'tool': TOOL, 'at': now.isoformat(timespec='seconds'), 'price_from': start, 'price_to': end, 'kis_calls': kis.calls,
            'dart_calls': dart.calls, 'failed': fails, 'hold_blank': holdblank,
            'assumptions': ['시가총액 = 오늘 상장주식수 × 그날 종가', '분기값은 12월 결산 가정', '수급은 KIS가 주는 최근 약 30거래일만']}
    nd.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime('%Y%m%dT%H%M%S+0900')
    prev = (nd / 'LATEST.txt').read_text(encoding='utf-8').strip() if (nd / 'LATEST.txt').exists() else None
    dst = build(nd, stamp, data, [c for c in companies if c in good], index_rows, meta)
    (nd / 'LATEST.txt.part').write_text(stamp + '\n', encoding='utf-8')
    os.replace(nd / 'LATEST.txt.part', nd / 'LATEST.txt')
    say(f'새 사본 {dst.name} 를 만들고 LATEST 를 정했어요.' + (f' 되돌리기: LATEST.txt 를 {prev} 로.' if prev else ''))
    say('다음: engine\\start.cmd 로 화면을 켜고, 날마다 가격·수급 갱신을 돌리세요(안내서 4·5단계).')
    return 0


if __name__ == '__main__':
    code = 1
    try:
        code = main(sys.argv[1:])
    except Exception as e:
        say(f'멈춤: {type(e).__name__}: {str(e)[:200]}')
    finally:
        try:
            (HERE / 'last-result.txt').write_text(datetime.now(KST).strftime('%Y-%m-%d %H:%M') + f' (끝 코드 {code})\n' + '\n'.join(LOG) + '\n',
                                                  encoding='utf-8')
        except OSError:
            pass
    sys.exit(code)
