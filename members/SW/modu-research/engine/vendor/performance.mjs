import {loadFinancialCorpus,calculateFinancial} from './lib/p07/evidence.mjs';
const corpus=loadFinancialCorpus();
console.log(JSON.stringify({digest:corpus.digest,manifestDigest:corpus.manifestDigest,sources:corpus.sources.map(s=>({...s,documents:s.documents.map(({rawResponse,...d})=>d),calculation:calculateFinancial(s)}))}));
