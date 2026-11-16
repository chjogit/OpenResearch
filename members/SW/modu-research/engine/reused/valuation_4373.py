"""Source-bound, explicit-assumption valuations. No forecast model or advice."""
import json
import re
import subprocess
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal, localcontext, ROUND_HALF_UP
from pathlib import Path
from typing import Annotated, Literal, Union
from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from .contracts import Contract
from .storage import digest, now, Integrity

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'n01-valuation-1'
D = Decimal
Amount = Annotated[str, Field(pattern=r'^-?(?:0|[1-9][0-9]{0,12})(?:\.[0-9]{1,6})?$')]


def number(v):
    return D(v)


def out(v):
    return format(D(v).quantize(D('.000001'), rounding=ROUND_HALF_UP), 'f')


def positive(v, name, zero=True):
    if number(v) < 0 or (not zero and number(v) == 0):
        raise ValueError(name + ' 값은 ' + ('0 이상' if zero else '0 초과') + '이어야 합니다.')


class Bridge(Contract):
    debt: Amount
    excess_cash: Amount
    nonoperating_assets: Amount
    minority: Amount
    preferred: Amount
    other_claims: Amount

    @model_validator(mode='after')
    def bounds(self):
        for k,v in self.model_dump().items(): positive(v,k)
        return self


class FlowYear(Contract):
    growth: Amount
    margin: Amount
    tax: Amount
    depreciation: Amount
    capex: Amount
    delta_wc: Amount

    @model_validator(mode='after')
    def bounds(self):
        if not -100 < number(self.growth) <= 200: raise ValueError('매출 성장률은 -100% 초과, 200% 이하')
        if not -100 <= number(self.margin) <= 100: raise ValueError('영업이익률 범위 -100~100%')
        if not 0 <= number(self.tax) <= 100: raise ValueError('세율 범위 0~100%')
        positive(self.depreciation,'감가상각');positive(self.capex,'재투자')
        return self


class Discount(Contract):
    rate: Amount
    terminal_growth: Amount

    @model_validator(mode='after')
    def discount(self):
        r,g=number(self.rate),number(self.terminal_growth)
        if not 0 < r <= 50: raise ValueError('할인율은 0% 초과, 50% 이하')
        if not -5 <= g <= 10 or g >= r: raise ValueError('장기성장률은 -5~10%, 할인율보다 작아야 합니다.')
        return self


class DCF(Discount):
    method: Literal['dcf']
    discount_basis: Literal['WACC']
    years: list[FlowYear] = Field(min_length=1,max_length=10)
    bridge: Bridge
    terminal_fcff: Amount
    terminal_reason: str = Field(min_length=10,max_length=1000)

    @model_validator(mode='after')
    def terminal(self):
        positive(self.terminal_fcff,'정상화 N+1년 FCFF',False)
        return self


class DDM(Discount):
    method: Literal['ddm']
    discount_basis: Literal['cost_of_equity']
    dividends: list[Amount] = Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def dividends_valid(self):
        for x in self.dividends: positive(x,'보통주 배당')
        positive(self.dividends[-1],'마지막 해 배당',False)
        return self


class IncomeYear(Contract):
    net_income: Amount
    dividends: Amount

    @model_validator(mode='after')
    def bounds(self):
        positive(self.dividends,'보통주 배당')
        return self


class RIM(Discount):
    method: Literal['rim']
    discount_basis: Literal['cost_of_equity']
    common_book: Amount
    years: list[IncomeYear] = Field(min_length=1,max_length=10)
    terminal_mode: Literal['zero','perpetuity']
    clean_surplus_ack: Literal[True]

    @model_validator(mode='after')
    def book(self):
        positive(self.common_book,'보통주 장부가치',False)
        b=number(self.common_book)
        for y in self.years:
            b+=number(y.net_income)-number(y.dividends)
            if b<=0: raise ValueError('RIM 장부가치가 0 이하입니다. 이 모델의 적용범위를 벗어납니다.')
        if self.terminal_mode=='zero' and number(self.terminal_growth)!=0: raise ValueError('잔여이익 소멸 모델의 장기성장률은 0으로 입력하세요.')
        return self


class NAV(Contract):
    method: Literal['nav']
    asset_adjustment: Amount
    liability_adjustment: Amount
    realization_cost: Amount
    minority: Amount
    preferred: Amount
    other_claims: Amount

    @model_validator(mode='after')
    def bounds(self):
        for k in ('realization_cost','minority','preferred','other_claims'): positive(getattr(self,k),k)
        return self


class ValuationRequest(Contract):
    company: Literal['005930','000660']
    base_year: Literal[2024,2025]
    evidence_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    valuation_date: str
    label: str = Field(min_length=1,max_length=100)
    assumptions_note: str = Field(min_length=10,max_length=2000)
    share_basis: str = Field(min_length=10,max_length=1000)
    shares: Amount
    input_kind: Literal['user_assumptions','illustrative_assumptions']
    acknowledged: Literal[True]
    model: Annotated[Union[DCF,DDM,RIM,NAV],Field(discriminator='method')]

    @field_validator('valuation_date')
    @classmethod
    def at(cls,v):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v): raise ValueError('기준일 YYYY-MM-DD')
        today=datetime.now(timezone(timedelta(hours=9))).date()
        if not date(2026,11,2)<=date.fromisoformat(v)<=today: raise ValueError('이 자료판은 2026-11-02 이후, 오늘 이하 기준일만 지원합니다. 과거시점 백테스트용이 아닙니다.')
        return v

    @model_validator(mode='after')
    def valid(self):
        positive(self.shares,'희석 보통주 수',False)
        for v in (self.label,self.assumptions_note,self.share_basis):
            if len(v.strip())< (1 if v==self.label else 10):raise ValueError('가정과 주식 수 산정 근거를 적어 주세요.')
        return self


def load_sources():
    try:
        p=subprocess.run(['node',str(ROOT/'vendor/valuation.mjs')],capture_output=True,encoding='utf-8',timeout=30,check=True,cwd=ROOT)
        data=json.loads(p.stdout)
    except (subprocess.SubprocessError,ValueError,OSError) as e:
        raise Integrity('저장 공시 원문 대조 실패. 원문을 확인한 뒤 다시 시도하세요.') from e
    return data


def source_pack(company,year):
    source=next((c for c in load_sources()['companies'] if c['company']==company),None)
    if source is None:raise ValueError('지원하지 않는 기업')
    y=next((y for y in source['calculation']['years'] if y['year']==year),None)
    if y is None:raise ValueError('지원하지 않는 연도')
    doc=source['documents'][0]
    # Only expose the financial document, never raw HTML in a browser execution context.
    facts={k:{**v,'source_url':doc['url'],'document_hash':doc['rawHash'],'document_id':doc['id']} for k,v in y['inputs'].items()}
    pack={'company':company,'name':source['name'],'base_year':year,'facts':facts,
          'historical':{k:v for k,v in y.items() if k!='inputs'},
          'document':doc,'formulas':source['calculation']['formulas'],
          'correction_status':'저장된 공시 판. 최신·정정 탐색 미실시',
          'scope':'연결 / KRW / 백만원','source_type':'stored_official','earliest_supported_date':'2026-11-02'}
    return {**pack,'digest':digest(pack)}


def evaluate(req, pack):
    m=req.model
    r=number(m.rate)/100 if hasattr(m,'rate') else None
    g=number(m.terminal_growth)/100 if hasattr(m,'terminal_growth') else None
    rows=[];terminal=D(0);terminal_pv=D(0);enterprise=None;bridge=[]
    warnings=['가정의 타당성·미래 실현 가능성은 검증하지 않았습니다. 모델 예측이나 목표주가가 아닙니다.',
              '기준일 현재 이용 가능한 저장 2025 사업보고서의 비교 수치입니다. 최신·정정 자동 수집 및 과거시점 재생은 지원하지 않습니다.',
              '금액은 백만원, 주식 수는 주, 주당가치는 원입니다. 모든 미래 현금흐름은 명목 KRW·연말 발생으로 가정합니다.']
    if m.method=='dcf':
        revenue=number(pack['facts']['revenue']['value'])
        for i,y in enumerate(m.years,1):
            prior=revenue;revenue*=1+number(y.growth)/100
            ebit=revenue*number(y.margin)/100
            # No unverified immediate tax refund for operating losses.
            tax=max(ebit,D(0))*number(y.tax)/100;nopat=ebit-tax
            fcff=nopat+number(y.depreciation)-number(y.capex)-number(y.delta_wc)
            pv=fcff/(1+r)**i
            rows.append({'year':i,'prior_revenue':out(prior),'revenue':out(revenue),'ebit':out(ebit),'tax':out(tax),'nopat':out(nopat),
                         'depreciation':y.depreciation,'capex':y.capex,'delta_wc':y.delta_wc,'fcff':out(fcff),'factor':out(1/(1+r)**i),'pv':out(pv)})
        terminal=number(m.terminal_fcff)/(r-g);terminal_pv=terminal/(1+r)**len(rows)
        enterprise=sum((number(x['pv']) for x in rows),D(0))+terminal_pv
        b=m.bridge
        adjustments=[('영업가치 (FCFF 현재가치)',enterprise),('초과현금',number(b.excess_cash)),('비영업자산 (초과현금 제외)',number(b.nonoperating_assets)),
                     ('이자부채 (리스 포함 범위 확인)',-number(b.debt)),('비지배지분 가치',-number(b.minority)),('우선주 가치',-number(b.preferred)),('기타 청구권',-number(b.other_claims))]
        equity=sum((v for _,v in adjustments),D(0));bridge=[{'label':k,'value':out(v)} for k,v in adjustments]
        formulas=['매출ₜ = 매출ₜ₋₁ × (1 + 사용자 성장률)', 'EBIT = 매출 × 영업이익률; 세금 = max(EBIT, 0) × 세율',
                  'FCFF = EBIT − 세금 + 감가상각 − 재투자 − 운전자본 증가',
                  '영업가치 = Σ FCFFₜ / (1+WACC)^t + 정상화 N+1년 FCFF / (WACC−g) / (1+WACC)^N',
                  '보통주 가치 = 영업가치 + 초과현금 + 비영업자산 − 이자부채 − 비지배지분 − 우선주 − 기타청구권']
        warnings+=['저장 CFO−취득지출은 FCFF로 사용하지 않습니다. 손실 연도 세금환급은 0이며 이월결손금 절세효과는 미반영입니다.',
                   '첫해 성장률은 공시 기준연도 매출에서 평가기준일 이후 첫 1년 매출로 가는 변화입니다. 결산일 이후 공백기간을 자동 추정하지 않으며 이후 연도만 직전 전망 매출에 성장률을 적용합니다.',
                   '말기가치는 별도로 입력한 정상화 N+1년 FCFF를 사용합니다. 장기성장에 필요한 재투자와 수익성의 일관성을 사용자가 검토해야 합니다.',
                   '현금·비영업자산의 중복, 부채의 리스 포함, 연결 현금흐름에 대응하는 비지배지분·우선주 조정을 확인하세요.']
    elif m.method=='ddm':
        for i,v in enumerate(m.dividends,1):rows.append({'year':i,'dividends':v,'pv':out(number(v)/(1+r)**i)})
        terminal=number(m.dividends[-1])*(1+g)/(r-g);terminal_pv=terminal/(1+r)**len(rows)
        equity=sum((number(x['pv']) for x in rows),D(0))+terminal_pv
        formulas=['보통주 가치 = Σ 보통주 총배당ₜ/(1+자기자본비용)^t + 마지막 배당×(1+g)/(자기자본비용−g)/(1+자기자본비용)^N']
        warnings+=['보통주 배당만 입력합니다. 안정적인 배당정책·배당여력을 전제로 하며, 순차입금은 다시 차감하지 않습니다.']
    elif m.method=='rim':
        book=number(m.common_book)
        for i,y in enumerate(m.years,1):
            ri=number(y.net_income)-r*book;end=book+number(y.net_income)-number(y.dividends)
            rows.append({'year':i,'opening_book':out(book),'net_income':y.net_income,'dividends':y.dividends,'equity_charge':out(r*book),'residual_income':out(ri),'closing_book':out(end),'pv':out(ri/(1+r)**i)});book=end
        terminal=(ri*(1+g)/(r-g)) if m.terminal_mode=='perpetuity' else D(0)
        terminal_pv=terminal/(1+r)**len(rows)
        equity=number(m.common_book)+sum((number(x['pv']) for x in rows),D(0))+terminal_pv
        bridge=[{'label':'기초 보통주 장부가치 (사용자 가정)','value':m.common_book}]
        formulas=['잔여이익ₜ = 보통주 귀속 순이익ₜ − 자기자본비용 × 기초 보통주 장부가치ₜ',
                  '기말 장부가치 = 기초 장부가치 + 보통주 순이익 − 보통주 배당',
                  '보통주 가치 = 현재 보통주 장부가치 + 잔여이익의 현재가치 + 말기 잔여이익의 현재가치']
        warnings+=['연결 자본총계는 보통주 장부가치와 다릅니다. 비지배지분·우선주를 제외한 가정을 별도 입력합니다.',
                   '증자·자사주 매입·기타포괄손익 없이 순이익−배당만 자본을 변화시킨다는 clean surplus 가정입니다.',
                   '말기 잔여이익은 '+('N년 후 0으로 소멸' if m.terminal_mode=='zero' else '마지막 잔여이익이 g로 영구 성장')+'한다고 가정합니다. 순차입금을 다시 차감하지 않습니다.']
    else:
        a=number(pack['facts']['assets']['value']);l=number(pack['facts']['liabilities']['value'])
        if a+number(m.asset_adjustment)<0 or l+number(m.liability_adjustment)<0:raise ValueError('조정 후 자산·부채가 음수가 될 수 없습니다.')
        values=[('공시 자산총계',a),('자산 재평가 조정',number(m.asset_adjustment)),('공시 부채총계',-l),('부채 재평가 조정',-number(m.liability_adjustment)),
                ('실현 세금·비용',-number(m.realization_cost)),('비지배지분 조정가치',-number(m.minority)),('우선주 조정가치',-number(m.preferred)),('기타 청구권',-number(m.other_claims))]
        bridge=[{'label':k,'value':out(v)} for k,v in values];equity=sum((v for _,v in values),D(0))
        formulas=['조정순자산가치 = 공시 자산 + 자산 조정 − 공시 부채 − 부채 조정 − 실현비용 − 비지배지분 − 우선주 − 기타 청구권']
        warnings+=['재평가 조정은 자산·부채의 장부금액 대비 증감입니다. 이미 공시 부채에 포함된 차입금을 다시 차감하지 않습니다.',
                   '공시 결산일과 평가기준일 사이 변화, 미인식 자산·부채 및 실현 세금·비용은 사용자 조정에 반영해야 합니다.']
    if equity<=0:warnings.append('보통주 잔여가치가 0 이하입니다. 음수 계산값은 잔여가치 부족을 나타내며 주식의 음수 시장가격을 뜻하지 않습니다.')
    denominator=enterprise if enterprise is not None else equity
    if denominator>0 and terminal_pv/denominator>D('.7'):warnings.append('말기가치 현재가치 비중이 70%를 넘습니다. 장기 가정에 결과가 크게 의존합니다.')
    if r is not None and r-g<D('.01'):warnings.append('할인율과 장기성장률 차이가 1%p 미만으로 계산이 매우 민감합니다.')
    return {'method':m.method,'rows':rows,'bridge':bridge,'enterprise_value':out(enterprise) if enterprise is not None else None,
            'equity_value':out(equity),'per_share':out(equity*1000000/number(req.shares)),
            'terminal_value':out(terminal),'terminal_pv':out(terminal_pv),'terminal_weight_pct':out(terminal_pv/denominator*100) if denominator>0 else None,
            'formulas':formulas+['주당가치(원) = 보통주 가치(백만원) × 1,000,000 / 희석 보통주 수(주)'], 'warnings':warnings}


def calculate(req,pack):
    if req.evidence_digest!=pack['digest'] or req.company!=pack['company'] or req.base_year!=pack['base_year']:raise Integrity('기업·연도·원문 판이 바뀌었습니다. 원문을 다시 불러오고 가정을 확인하세요.')
    with localcontext() as ctx:
        ctx.prec=40
        result=evaluate(req,pack);sensitivity=[]
        if req.model.method!='nav':
            # DCF terminal FCFF N+1 remains fixed while terminal growth changes.
            for dr in ('-1','0','1'):
                for dg in ('-0.5','0','0.5'):
                    r=number(req.model.rate)+number(dr);g=number(req.model.terminal_growth)+number(dg)
                    cell={'rate':out(r),'growth':out(g)}
                    if req.model.method=='rim' and req.model.terminal_mode=='zero' and dg!='0':continue
                    try:
                        raw=req.model_dump();raw['model'].update(rate=out(r),terminal_growth=out(g))
                        other=ValuationRequest.model_validate(raw);value=evaluate(other,pack)
                        cell.update(status='calculated',per_share=value['per_share'])
                    except ValueError:cell.update(status='held',reason='할인율·성장률 허용범위 밖')
                    sensitivity.append(cell)
        result['sensitivity']=sensitivity
        result['sensitivity_note']='할인율 ±1%p·성장률 ±0.5%p의 조건부 계산입니다. 확률·신뢰구간이 아닙니다. DCF는 정상화 N+1 FCFF를 고정합니다. RIM 소멸형은 할인율만 바꿉니다.'
        return result


def checked_saved(store,key):
    saved=store.get('valuation',key)
    if saved['version']!=VERSION:raise Integrity('지원하지 않는 평가 산식 버전')
    pack=saved['source'];raw={k:v for k,v in pack.items() if k!='digest'}
    if digest(raw)!=pack['digest']:raise Integrity('저장 원문 스냅샷 해시 불일치')
    req=ValuationRequest.model_validate(saved['request'])
    if calculate(req,pack)!=saved['result']:raise Integrity('저장 계산 재현 불일치')
    return saved


def install_valuation(app,store,csrf):
    @app.get('/api/valuation/session')
    def session(): return {'csrf':csrf,'version':VERSION}

    @app.get('/api/valuation/source')
    def source(company:Literal['005930','000660']='005930',year:Literal['2024','2025']='2025'):
        return source_pack(company,int(year))

    @app.post('/api/valuation',status_code=201)
    def create(body:ValuationRequest):
        try:
            pack=source_pack(body.company,body.base_year);result=calculate(body,pack)
        except ValueError as e:
            if isinstance(e,Integrity):raise
            raise HTTPException(422,str(e)) from e
        saved={'version':VERSION,'created_at':now(),'request':body.model_dump(),'source':pack,'result':result,
               'classification':'user_assumption_calculation','ai_used':False,'ml_forecast':False,'publication_approved':False}
        key=store.put('valuation',saved)
        return {'id':key,**saved}

    @app.get('/api/valuation')
    def history():
        with store.connect() as c:keys=[x[0] for x in c.execute("SELECT id FROM objects WHERE kind='valuation' ORDER BY rowid DESC LIMIT 100")]
        return [{'id':key,'created_at':v['created_at'],'label':v['request']['label'],'company':v['source']['name'],'method':v['result']['method'],'input_kind':v['request']['input_kind']} for key in keys for v in [store.get('valuation',key)]]

    @app.get('/api/valuation/{key}')
    def get(key:str):return {'id':key,**checked_saved(store,key)}
