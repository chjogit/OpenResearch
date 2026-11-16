"""Neon 공용 DB → 기준 시점 사본 고정 (읽기 전용).
결과: ../../_sources/neon/<기준시각>/ 표별 JSONL + manifest.json(sha256, 질의, 행 수, 출처 등급).
앱은 이 사본만 읽고 DB 주소는 모른다."""
import os, sys, re, datetime
import psycopg
import traceback
def _ok(u):
    return bool(u) and u.strip().strip('"').startswith(('postgresql://', 'postgres://'))

def _clipboard():
    import subprocess
    try:
        r = subprocess.run(['powershell', '-NoProfile', '-Command', 'Get-Clipboard -Raw'],
                           capture_output=True, text=True, encoding='utf-8', timeout=15)
        return (r.stdout or '').strip()
    except Exception:
        return ''

url = os.environ.get('MODU_NODES_PG_URL', '')
if not _ok(url):
    url = _clipboard()
    if _ok(url):
        print('클립보드에서 DB 주소를 읽었습니다 (화면·파일에 표시하지 않음).')
tries = 0
while not _ok(url) and tries < 3:
    tries += 1
    url = input('postgresql:// 로 시작하는 DB 주소를 붙여 넣고 Enter: ').strip()
    if not _ok(url):
        print('  주소 형식이 아닙니다. 다시 입력해 주세요.')
if not _ok(url):
    sys.exit('DB 주소를 받지 못했습니다.')
url = url.strip().strip('"')
TICKERS = ['005930', '000660']
# name: (sql, params_kind, source_grade, note)
Q = {
 'company': ("select company_id, market, ticker, name, corp_code, sector, sector_desc, krx_sector, index_tags, shares_outstanding, shares_asof from core.company order by market, ticker", None, 'registered', '전체 기업 목록(v3)'),
 'price_daily': ("select c.ticker, p.trade_date, p.open, p.high, p.low, p.close, p.volume, p.trade_value, p.market_cap, p.source, p.collected_at from core.price_daily p join core.company c using(company_id) where c.ticker = any(%s) and p.source = 'fsc' order by 1,2", 'tickers', 'public:fsc', 'KR 종목 fsc(금융위)만'),
 'investor_flow_daily': ("select c.ticker, f.trade_date, f.foreign_net_qty, f.institution_net_qty, f.individual_net_qty, f.foreign_hold_pct, f.volume, f.source, f.collected_at from core.investor_flow_daily f join core.company c using(company_id) where c.ticker = any(%s) order by 1,2", 'tickers', 'portal:naver', '포털 수집값'),
 'stock_lending_daily': ("select c.ticker, s.trade_date, s.lent_qty, s.repaid_qty, s.balance_qty, s.balance_amt, s.source, s.collected_at from core.stock_lending_daily s join core.company c using(company_id) where c.ticker = any(%s) order by 1,2", 'tickers', 'public:fsc', ''),
 'financial_quarter': ("select c.ticker, q.period_end, q.fiscal_year, q.fiscal_q, q.metric, q.amount, q.currency, q.source from core.financial_quarter q join core.company c using(company_id) where c.ticker = any(%s) order by 1,2,5", 'tickers', 'official:dart', 'XBRL 대조 68/68 통과 표(financial_fact)에서 파생'),
 'largest_holder': ("select c.ticker, h.fiscal_year, h.report_code, h.holder, h.stock_kind, h.relate, h.end_qty, h.stake_rt, h.begin_rt, h.settle_dt, h.rcept_no, h.collected_at from core.largest_holder h join core.company c using(company_id) where c.ticker = any(%s) order by 1,2,4", 'tickers', 'official:dart', ''),
 'ownership_report': ("select c.ticker, o.rcept_no, o.repror, o.rcept_dt, o.report_tp, o.report_resn, o.stkqy, o.stkrt, o.stkrt_irds, o.ctr_stkrt, o.collected_at from core.ownership_report o join core.company c using(company_id) where c.ticker = any(%s) order by 1,4", 'tickers', 'official:dart', ''),
 # ---- v2: 사건·뉴스·감성(T08) / 비교기업(T09). 뉴스는 제목·링크·날짜만(본문·요약 제외)
 'disclosure': ("select c.ticker, d.rcept_no, d.report_nm, d.rcept_dt, d.filer, d.category, d.event_type, d.url, d.source, d.collected_at from core.disclosure d join core.company c using(company_id) where c.ticker = any(%s) order by 1,4", 'tickers', 'official:dart', '공시 목록'),
 'news_title': ("select c.ticker, r.doc_id, r.source, r.title, r.url, r.published_at, r.created_at from rag.document r join core.company c using(company_id) where c.ticker = any(%s) order by 1,6", 'tickers', 'portal:news_title', '제목·링크·날짜만 (본문·요약 미수집)'),
 'doc_daily_agg': ("select c.ticker, a.source, a.d, a.n_docs, a.n_scored, a.score_sum, a.updated_at from core.doc_daily_agg a join core.company c using(company_id) where c.ticker = any(%s) order by 1,3,2", 'tickers', 'rule_derived:lexicon', '사전 기반 감성 점수 일별 합계'),
 'mention_count': ("select c.ticker, m.source, m.query, m.captured_at, m.trade_date, m.total from core.mention_count m join core.company c using(company_id) where c.ticker = any(%s) order by 1,5,2", 'tickers', 'portal:naver', '검색 결과 건수'),
 'reaction_pulse': ("select c.ticker, r.captured_at, r.trade_date, r.n_today, r.n_news, r.n_blog, r.n_positive, r.n_negative, r.sentiment, r.mentions_vs_30d, r.new_docs, r.method from core.reaction_pulse r join core.company c using(company_id) where c.ticker = any(%s) order by 1,2", 'tickers', 'rule_derived:lexicon', ''),
 'peer_group': ("select c.ticker as base_ticker, g.peer_group_id, g.method, g.created_at, pc.ticker, pc.name, m.rank, m.reason from core.peer_group g join core.company c on c.company_id = g.base_company_id join core.peer_member m using(peer_group_id) join core.company pc on pc.company_id = m.company_id where c.ticker = any(%s) order by 1,2,7", 'tickers', 'registered:team', '비교기업 묶음(선정 방법·이유 포함)'),
 'peer_company': ("select distinct pc.company_id, pc.market, pc.ticker, pc.name, pc.corp_code, pc.sector, pc.krx_sector, pc.shares_outstanding, pc.shares_asof from core.peer_group g join core.company c on c.company_id = g.base_company_id join core.peer_member m using(peer_group_id) join core.company pc on pc.company_id = m.company_id where c.ticker = any(%s) order by 3", 'tickers', 'registered', ''),
 'peer_financial_quarter': ("select pc.ticker, q.period_end, q.fiscal_year, q.fiscal_q, q.metric, q.amount, q.currency, q.source from core.financial_quarter q join core.company pc using(company_id) where q.company_id in (select m.company_id from core.peer_group g join core.company c on c.company_id = g.base_company_id join core.peer_member m using(peer_group_id) where c.ticker = any(%s)) order by 1,2,5", 'tickers', 'official:dart/sec', 'DART(국내)·SEC(해외)'),
 'peer_price_daily': ("select pc.ticker, p.trade_date, p.close, p.volume, p.market_cap, p.source from core.price_daily p join core.company pc using(company_id) where p.trade_date >= current_date - 400 and p.company_id in (select m.company_id from core.peer_group g join core.company c on c.company_id = g.base_company_id join core.peer_member m using(peer_group_id) where c.ticker = any(%s)) order by 1,2", 'tickers', 'public:fsc/unofficial:yfinance', '행마다 source 확인'),
 'macro_series': ("select series_id, name, source, frequency, unit from core.macro_series order by 1", None, 'public', ''),
 'macro_obs': ("select series_id, obs_date, value, source, collected_at from core.macro_obs order by 1,2", None, 'public:fred/ecos/kcs', ''),
 'market_index_daily': ("select symbol, trade_date, name, open, high, low, close, volume, source, collected_at from core.market_index_daily order by 1,2", None, 'unofficial:yfinance', '비공식 — 참고용'),
}

# ---- v3: 종목별로 나눠 저장하는 표 (앱은 필요한 종목 파일만 읽는다)
PARTS = {
 'price_daily': ("select c.ticker, p.trade_date, p.open, p.high, p.low, p.close, p.volume, p.trade_value, p.market_cap, p.source, p.collected_at from core.price_daily p join core.company c using(company_id) where c.market = 'KR' and p.source = 'fsc' order by 1,2", 'public:fsc', '국내 기업, 금융위(fsc) 행만'),
 'investor_flow_daily': ("select c.ticker, f.trade_date, f.foreign_net_qty, f.institution_net_qty, f.individual_net_qty, f.foreign_hold_pct, f.volume, f.source, f.collected_at from core.investor_flow_daily f join core.company c using(company_id) order by 1,2", 'portal:naver', '포털 수집값'),
 'stock_lending_daily': ("select c.ticker, s.trade_date, s.lent_qty, s.repaid_qty, s.balance_qty, s.balance_amt, s.source, s.collected_at from core.stock_lending_daily s join core.company c using(company_id) order by 1,2", 'public:fsc', ''),
}
# ---- v4: 키트 2·T08·N11~N13용 — 모든 기업, 기업별 파일
ACC = ['ifrs-full_Revenue', 'dart_OperatingIncomeLoss', 'ifrs-full_ProfitLoss', 'ifrs-full_ProfitLossAttributableToOwnersOfParent',
       'ifrs-full_CashFlowsFromUsedInOperatingActivities', 'ifrs-full_Assets', 'ifrs-full_Liabilities', 'ifrs-full_Equity',
       'ifrs-full_CurrentAssets', 'ifrs-full_CurrentLiabilities', 'ifrs-full_Inventories', 'ifrs-full_BasicEarningsLossPerShare',
       'ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities',
       'ifrs-full_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities']
PARTS.update({
 'financial_fact': ("select c.ticker, f.fiscal_year, f.report_code, f.fs_div, f.sj_div, f.account_id, f.account_nm, f.amount, f.amount_ytd, f.currency, f.rcept_no, f.period_end, f.source, f.collected_at from core.financial_fact f join core.company c using(company_id) where c.market = 'KR' and f.sj_div <> 'SCE' and f.account_id in (" + ','.join("'" + a + "'" for a in ACC) + ") order by 1,2,3,6,4", 'official:dart_api', 'DART 정기보고서 재무(공시 API) — 주요 14개 계정'),
 'report_exposure': ("select c.ticker, e.fiscal_year, e.rcept_no, e.metric, e.currency, e.value, e.change_pct, e.basis, e.unit_raw, e.evidence, e.file, e.table_index, e.extracted_at from core.report_exposure e join core.company c using(company_id) order by 1,2,4", 'rule_derived:report_parse', '사업보고서 표에서 규칙으로 읽은 환율·금리 민감도(원문 문장 포함)'),
 'disclosure': ("select c.ticker, d.rcept_no, d.report_nm, d.rcept_dt, d.filer, d.category, d.event_type, d.url, d.source, d.collected_at from core.disclosure d join core.company c using(company_id) order by 1,4,2", 'official:dart_list', 'DART 공시 목록'),
 'news_title': ("select c.ticker, r.doc_id, r.source, r.title, r.url, r.published_at, r.created_at, s.score, s.label, s.method from rag.document r join core.company c using(company_id) left join core.doc_sentiment s using(doc_id) order by 1,6,2", 'portal:news_title', '제목·링크·날짜만(본문·요약 제외), 사전 기반 감성 점수'),
 'doc_daily_agg': ("select c.ticker, a.source, a.d, a.n_docs, a.n_scored, a.score_sum, a.updated_at from core.doc_daily_agg a join core.company c using(company_id) order by 1,3,2", 'rule_derived:lexicon', '사전 기반 감성 일별 합'),
 'mention_count': ("select c.ticker, m.source, m.query, m.captured_at, m.trade_date, m.total from core.mention_count m join core.company c using(company_id) order by 1,5,2", 'portal:naver', '검색 결과 건수'),
 'largest_holder': ("select c.ticker, h.fiscal_year, h.report_code, h.holder, h.stock_kind, h.relate, h.end_qty, h.stake_rt, h.begin_rt, h.settle_dt, h.rcept_no, h.collected_at from core.largest_holder h join core.company c using(company_id) order by 1,2,4", 'official:dart_api', '최대주주 및 특수관계인'),
 'ownership_report': ("select c.ticker, o.rcept_no, o.repror, o.rcept_dt, o.report_tp, o.report_resn, o.stkqy, o.stkrt, o.stkrt_irds, o.ctr_stkrt, o.collected_at from core.ownership_report o join core.company c using(company_id) order by 1,4", 'official:dart_api', '대량보유(5%) 보고'),
})

# ---- v3: 커버리지 — 행을 받지 않고 기업별 개수·최근 날짜만 받는다 (DB 부담 최소)
COVER = {
 'price_fsc': "select company_id, count(*), max(trade_date)::text from core.price_daily where source = 'fsc' group by 1",
 'price_other': "select company_id, count(*), max(trade_date)::text from core.price_daily where source <> 'fsc' group by 1",
 'flow': "select company_id, count(*), max(trade_date)::text from core.investor_flow_daily group by 1",
 'lending': "select company_id, count(*), max(trade_date)::text from core.stock_lending_daily group by 1",
 'fin_annual': "select company_id, count(*), max(fiscal_year)::text from core.financial_fact where report_code = '11011' group by 1",
 'fin_quarter': "select company_id, count(*), max(period_end)::text from core.financial_quarter group by 1",
 'exposure': "select company_id, count(*), string_agg(distinct metric, ',') from core.report_exposure group by 1",
 'peer_manual': "select base_company_id, count(*), string_agg(distinct method, ',') from core.peer_group where method like 'manual:%%' group by 1",
 'peer_auto': "select base_company_id, count(*), string_agg(distinct method, ',') from core.peer_group where method not like 'manual:%%' group by 1",
 'disclosure': "select company_id, count(*), max(rcept_dt)::text from core.disclosure group by 1",
 'news': "select company_id, count(*), max(published_at)::text from rag.document group by 1",
 'sentiment': "select company_id, count(*), max(d)::text from core.doc_daily_agg group by 1",
 'holder': "select company_id, count(*), max(fiscal_year)::text from core.largest_holder group by 1",
 'ownership': "select company_id, count(*), max(rcept_dt)::text from core.ownership_report group by 1",
 'dart_archive': "select company_id, count(*), max(fetched_at)::text from ops.dart_archive group by 1",
}

def _ser(v):
    import datetime, decimal
    if isinstance(v, decimal.Decimal): return format(v, 'f')
    if isinstance(v, (datetime.date, datetime.datetime)): return v.isoformat()
    return v

def main():
    import json, hashlib, datetime
    asof = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).strftime('%Y%m%dT%H%M%S+0900')
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '_sources', 'neon', asof))
    os.makedirs(root, exist_ok=True)
    man = {'asof_kst': asof, 'db': 'neon(shared) read-only', 'tool_version': 4, 'tickers': TICKERS, 'tables': {}}
    with psycopg.connect(url, connect_timeout=20, options='-c default_transaction_read_only=on') as c:
        cur = c.cursor()
        cur.execute('show transaction_read_only'); man['read_only'] = cur.fetchone()[0]
        for name, (sql, pk, grade, note) in Q.items():
            if name in PARTS:
                continue
            try:
                cur.execute(sql, (TICKERS,) if pk == 'tickers' else None)
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()
            except Exception as e:                      # 표 하나가 실패해도 나머지는 받는다
                c.rollback()
                man.setdefault('failed', {})[name] = type(e).__name__ + ': ' + str(e).splitlines()[0][:200]
                print(f'  {name}: 실패 ({type(e).__name__}) — 나머지는 계속')
                continue
            path = os.path.join(root, name + '.jsonl')
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                for r in rows:
                    f.write(json.dumps({k: _ser(v) for k, v in zip(cols, r)}, ensure_ascii=False, sort_keys=True) + '\n')
            h = hashlib.sha256(open(path, 'rb').read()).hexdigest()
            man['tables'][name] = {'file': name + '.jsonl', 'rows': len(rows), 'sha256': h, 'columns': cols,
                                   'source_grade': grade, 'note': note, 'query': ' '.join(sql.split())}
            print(f'  {name}: {len(rows)}행')
        # ---- 분할 표
        for name, (sql, grade, note) in PARTS.items():
            try:
                cur.execute(sql)
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()
            except Exception as e:
                c.rollback(); man.setdefault('failed', {})[name] = type(e).__name__ + ': ' + str(e).splitlines()[0][:200]
                print(f'  {name}: 실패 ({type(e).__name__})'); continue
            pdir = os.path.join(root, name); os.makedirs(pdir, exist_ok=True)
            groups = {}
            for r in rows:
                groups.setdefault(r[0], []).append(r)
            parts = {}
            for t, rs in groups.items():
                fn = os.path.join(pdir, f'{t}.jsonl')
                with open(fn, 'w', encoding='utf-8', newline='\n') as f:
                    for r in rs:
                        f.write(json.dumps({k: _ser(v) for k, v in zip(cols, r)}, ensure_ascii=False, sort_keys=True) + '\n')
                parts[t] = {'file': f'{name}/{t}.jsonl', 'rows': len(rs), 'sha256': hashlib.sha256(open(fn, 'rb').read()).hexdigest()}
            man['tables'][name] = {'partitioned': True, 'parts': parts, 'rows': len(rows), 'columns': cols, 'source_grade': grade, 'note': note, 'query': ' '.join(sql.split())}
            print(f'  {name}: {len(rows)}행, {len(parts)}개 기업 파일')
        # ---- 커버리지
        cur.execute('select company_id, ticker from core.company'); idmap = dict(cur.fetchall())
        cov = {}
        for key, sql in COVER.items():
            try:
                cur.execute(sql)
                for cid, n, extra in cur.fetchall():
                    if cid in idmap:
                        cov.setdefault(idmap[cid], {})[key] = {'n': n, 'x': extra}
            except Exception as e:
                c.rollback(); man.setdefault('failed', {})['coverage.' + key] = type(e).__name__
        path = os.path.join(root, 'coverage.jsonl')
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            for t in sorted(cov):
                f.write(json.dumps({'ticker': t, **cov[t]}, ensure_ascii=False, sort_keys=True) + '\n')
        man['tables']['coverage'] = {'file': 'coverage.jsonl', 'rows': len(cov), 'sha256': hashlib.sha256(open(path, 'rb').read()).hexdigest(),
                                     'source_grade': 'derived:count', 'note': '기업별 자료 개수·최근 날짜(행 미수집)', 'columns': list(COVER)}
        print(f'  coverage: {len(cov)}개 기업')
    mp = os.path.join(root, 'manifest.json')
    json.dump(man, open(mp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    man_sha = hashlib.sha256(open(mp, 'rb').read()).hexdigest()
    open(os.path.join(root, 'manifest.sha256'), 'w', encoding='utf-8', newline='\n').write(man_sha + '  manifest.json\n')
    open(os.path.join(os.path.dirname(root), 'LATEST.txt'), 'w', encoding='utf-8').write(asof + '\n')
    print('완료:', root)

err_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'snapshot-error.txt')
open(err_path, 'w', encoding='utf-8').write('오류 없음 (실행 중 또는 성공)')
try:
    main()
except Exception as e:
    msg = re.sub(r'postgres(ql)?://\S+', 'postgresql://***', str(e))
    msg = re.sub(r'npg_[A-Za-z0-9]+', '***', msg)
    print('오류:', type(e).__name__, msg)
    open(err_path, 'w', encoding='utf-8').write(type(e).__name__ + ' ' + msg)
    sys.exit(1)
