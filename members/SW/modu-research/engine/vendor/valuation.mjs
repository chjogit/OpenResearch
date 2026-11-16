// Reuse the pinned HTML/cell verifier. No external fetch and no model calls.
import {loadFinancialCorpus,calculateFinancial} from './lib/p07/evidence.mjs';
const corpus=loadFinancialCorpus();
console.log(JSON.stringify({manifestDigest:corpus.manifestDigest,companies:corpus.sources.map(s=>({
  company:s.id,name:s.name,calculation:calculateFinancial(s),
  documents:s.documents.filter(d=>d.scope==='CFS').map(({rawResponse,...d})=>d)
}))}));
