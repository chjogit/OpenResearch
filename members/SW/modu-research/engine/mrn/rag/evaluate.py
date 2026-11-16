"""Retrieval recall of expected value strings (see cases.py for provenance and limits)."""
from .cases import DEV, HOLDOUT


def run(index, ks=(5, 10, 16), mode='auto', synonyms=True, company='005930'):
    rows = []
    for split, cases in (('dev', DEV), ('holdout', HOLDOUT)):
        for c in cases:
            r = index.search(c['question'], company=company, k=max(ks), mode=mode, synonyms=synonyms)
            row = {'id': c['id'], 'split': split, 'question': c['question'], 'values': c['values'], 'mode': r['mode']}
            for k in ks:
                text = '\n'.join(h['text'] for h in r['hits'][:k])
                found = [v for v in c['values'] if v in text]
                row[f'found@{k}'] = found
                row[f'all@{k}'] = len(found) == len(c['values'])
            first = None
            for h in r['hits']:
                if any(v in h['text'] for v in c['values']):
                    first = h['rank']
                    break
            row['first_rank'] = first
            rows.append(row)
    summary = {}
    for split in ('dev', 'holdout', 'all'):
        sel = [x for x in rows if split == 'all' or x['split'] == split]
        summary[split] = {f'@{k}': f"{sum(x[f'all@{k}'] for x in sel)}/{len(sel)}" for k in ks}
    return {'definition': '질문별 기대값 문자열이 상위 k개 청크에 모두 있으면 확보. 검색 단계 지표이며 답변 정확도가 아님. 질문은 개발자 작성 초안.',
            'mode': rows[0]['mode'] if rows else '', 'synonyms': synonyms, 'summary': summary, 'rows': rows}
