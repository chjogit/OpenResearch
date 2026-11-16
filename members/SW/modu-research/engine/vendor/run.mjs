import {loadFinancialCorpus,calculateFinancial,LIMITS} from './lib/p07/evidence.mjs';
import {loadMacroCorpus,readIndicator,companyEvidence,buildMacroAnswer} from './lib/p01/evidence.mjs';
const f=loadFinancialCorpus(),m=loadMacroCorpus();const evidence=m.sources.map(s=>s.kind==='indicator'?readIndicator(s):companyEvidence(s));
const financial=f.sources.map(s=>({company:s.id,name:s.name,calculation:calculateFinancial(s),documents:s.documents.map(({rawResponse,...d})=>d)}));
const macro=buildMacroAnswer({evidence,gaps:[]});console.log(JSON.stringify({financial,macro,limits:LIMITS,sourceMode:'stored_official',liveFetch:false}));
