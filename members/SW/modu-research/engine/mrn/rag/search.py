"""Hybrid retrieval over the chunk index.

- BM25 over Korean character bigrams + latin/number words (no external tokenizer; deterministic)
- small curated synonym table (domain knowledge; listed in SYNONYMS so it is auditable)
- optional dense vectors (Ollama embedding model) combined with BM25 by RRF(k=60).
  If vectors are absent or the model differs from the index, mode is reported as 'bm25',
  never silently called hybrid.
"""
import json
from pathlib import Path
import math
import os
import re
import urllib.request
from collections import defaultdict

HANGUL = re.compile(r'[가-힣]+')
WORD = re.compile(r'[A-Za-z]+|\d[\d,\.]*')
SYNONYMS = {
    '직원': ['근로자', '종업원', '임직원'], '근속': ['근속연수'], '연구개발': ['R&D', '연구개발비용'],
    '감사인': ['회계법인', '외부감사인', '감사의견'], '회계법인': ['감사인'], '매출': ['매출액', '수익'],
    '영업이익': ['영업손익'], '순이익': ['당기순이익', '당기순손익'], '배당': ['배당금', '주당배당금', '현금배당'],
    '환율': ['외화', '환위험', '환율변동위험'], '주당이익': ['주당순이익', '기본주당이익'], '육아휴직': ['육아휴직자'],
    '에너지': ['에너지사용량', '에너지 사용량'], '이사': ['이사회', '사내이사', '사외이사'], '제품': ['주요제품', '품목'],
}
STOP = {'알려', '주세', '세요', '해주', '나요', '인가', '얼마', '무엇', '각각', '어떻', '떻게', '궁금', '합니', '니다', '확인', '찾아', '아주'}


def tokens(text):
    out = []
    for w in WORD.findall(text):
        w = w.lower().rstrip('.')
        out.append(w)
        if ',' in w:
            out.append(w.replace(',', ''))
    for h in HANGUL.findall(text):
        if len(h) == 1:
            out.append(h)
        out += [h[i:i + 2] for i in range(len(h) - 1)]
    return out


def expand(query):
    extra = []
    for k, vs in SYNONYMS.items():
        if k in query:
            extra += vs
    return query + (' ' + ' '.join(extra) if extra else '')


class Index:
    def __init__(self, folder):
        self.folder = folder
        self.chunks = json.loads(Path(os.path.join(folder, 'chunks.json')).read_text(encoding='utf-8'))
        self.manifest = json.loads(Path(os.path.join(folder, 'manifest.json')).read_text(encoding='utf-8'))
        self.postings = defaultdict(list)
        self.lens = []
        for i, c in enumerate(self.chunks):
            tf = defaultdict(int)
            toks = tokens(' '.join(c['path']) + ' ' + c['text'])
            for t in toks:
                tf[t] += 1
            for t, n in tf.items():
                self.postings[t].append((i, n))
            self.lens.append(len(toks))
        self.avg = sum(self.lens) / max(1, len(self.lens))
        self.N = len(self.chunks)
        self.vectors, self.vec_meta = None, None
        vp, vm = os.path.join(folder, 'vectors.npy'), os.path.join(folder, 'vectors.json')
        if os.path.exists(vp) and os.path.exists(vm):
            try:
                import numpy as np
                v = np.load(vp)
                meta = json.loads(Path(vm).read_text(encoding='utf-8'))
                if v.shape[0] == self.N and meta.get('corpusHash') == self.manifest['corpusHash']:
                    self.vectors, self.vec_meta = v, meta
            except Exception:
                self.vectors = None

    def bm25(self, query, allowed, k1=1.2, b=0.75):
        scores = defaultdict(float)
        for t in set(tokens(query)):
            if t in STOP:
                continue
            plist = self.postings.get(t)
            if not plist:
                continue
            idf = math.log(1 + (self.N - len(plist) + 0.5) / (len(plist) + 0.5))
            for i, tf in plist:
                if allowed is not None and i not in allowed:
                    continue
                scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * self.lens[i] / self.avg))
        return sorted(scores, key=lambda i: -scores[i]), scores

    def dense(self, query, allowed, url, model):
        import numpy as np
        body = json.dumps({'model': model, 'input': 'task: search result | query: ' + query}).encode()
        req = urllib.request.Request(url.rstrip('/') + '/api/embed', data=body, headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as r:
            q = np.asarray(json.loads(r.read())['embeddings'][0], dtype='float32')
        q /= (np.linalg.norm(q) or 1)
        sims = self.vectors @ q
        order = [int(i) for i in np.argsort(-sims) if allowed is None or int(i) in allowed]
        return order

    def search(self, query, company=None, k=10, mode='auto', synonyms=True):
        allowed = None
        if company:
            allowed = {i for i, c in enumerate(self.chunks) if company in (c['company'], c['code'])}
        q = expand(query) if synonyms else query
        order, scores = self.bm25(q, allowed)
        used, note = 'bm25', ''
        want_dense = mode in ('auto', 'hybrid')
        if want_dense and self.vectors is not None:
            url = os.environ.get('MODU_NODES_OLLAMA', 'http://127.0.0.1:11434')
            try:
                dense = self.dense(query, allowed, url, self.vec_meta['model'])
                rrf = defaultdict(float)
                for r, i in enumerate(order[:60]):
                    rrf[i] += 1 / (60 + r + 1)
                for r, i in enumerate(dense[:60]):
                    rrf[i] += 1 / (60 + r + 1)
                order = sorted(rrf, key=lambda i: -rrf[i])
                used = 'hybrid'
            except Exception as e:
                note = f'임베딩 호출 실패로 BM25만 사용 ({type(e).__name__})'
        elif want_dense:
            note = '벡터 색인 없음: BM25만 사용 (prepare-rag.cmd --embed 로 생성)'
        if mode == 'hybrid' and used != 'hybrid':
            note = note or '하이브리드 불가'
        hits = []
        for rank, i in enumerate(order[:k]):
            c = self.chunks[i]
            hits.append({'rank': rank + 1, 'id': c['id'], 'company': c['company'], 'section': c['section'], 'path': c['path'],
                         'kind': c['kind'], 'text': c['text'], 'source': c['source'], 'bm25': round(scores.get(i, 0.0), 4)})
        return {'query': query, 'expanded': q if synonyms else query, 'mode': used, 'note': note, 'hits': hits,
                'index': {'chunks': self.N, 'parser': self.manifest['parser'], 'corpusHash': self.manifest['corpusHash'][:16],
                          'vectors': bool(self.vectors is not None), 'model': (self.vec_meta or {}).get('model')}}


def embed_index(folder, url, model, batch=32, progress=None):
    """Compute dense vectors for every chunk via Ollama (run on the user's PC)."""
    import numpy as np
    chunks = json.loads(Path(os.path.join(folder, 'chunks.json')).read_text(encoding='utf-8'))
    manifest = json.loads(Path(os.path.join(folder, 'manifest.json')).read_text(encoding='utf-8'))
    out = []
    for s in range(0, len(chunks), batch):
        part = chunks[s:s + batch]
        inputs = ['title: ' + ' > '.join(c['path'])[:200] + ' | text: ' + c['text'][:1500] for c in part]
        req = urllib.request.Request(url.rstrip('/') + '/api/embed', data=json.dumps({'model': model, 'input': inputs}).encode(),
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=600) as r:
            out += json.loads(r.read())['embeddings']
        if progress:
            progress(min(s + batch, len(chunks)), len(chunks))
    v = np.asarray(out, dtype='float32')
    v /= np.linalg.norm(v, axis=1, keepdims=True).clip(1e-9)
    np.save(os.path.join(folder, 'vectors.npy'), v)
    Path(os.path.join(folder, 'vectors.json')).write_text(json.dumps({'model': model, 'dimensions': int(v.shape[1]),
        'corpusHash': manifest['corpusHash'], 'count': int(v.shape[0])}, ensure_ascii=False), encoding='utf-8')
    return v.shape
