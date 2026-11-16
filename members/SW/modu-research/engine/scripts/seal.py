"""Seal or verify an evaluation question file without revealing its contents.

  seal:   python seal.py <file.csv>            -> prints SHA-256, appends a record to _eval/seal-records.jsonl
  verify: python seal.py --verify <file.csv>   -> checks the file against the recorded hash
Only the hash, row count and column check are recorded — never the questions.
"""
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = ['id', '질문', '기대유형', '기대내용', '대상기업', '대상기간', '관점', '난이도', '메모']
TYPES = {'answer', 'hold', 'false_premise', 'numeric_bait', 'judgment_bait'}
RECORDS = Path(__file__).resolve().parents[2] / '_eval' / 'seal-records.jsonl'


def inspect(path):
    data = path.read_bytes()
    with path.open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] != COLUMNS:
        raise SystemExit('열 이름이 양식과 다릅니다: ' + ', '.join(COLUMNS))
    body = [r for r in rows[1:] if any(c.strip() for c in r)]
    if any(r[0].startswith('예시') for r in body):
        raise SystemExit('예시 행이 남아 있습니다. 지운 뒤 다시 봉인하세요.')
    bad = [r[0] for r in body if len(r) < 3 or r[2].strip() not in TYPES]
    if bad:
        raise SystemExit('기대유형이 잘못된 행: ' + ', '.join(bad) + ' (허용: ' + ', '.join(sorted(TYPES)) + ')')
    counts = {}
    for r in body:
        counts[r[2].strip()] = counts.get(r[2].strip(), 0) + 1
    return hashlib.sha256(data).hexdigest(), len(body), counts


def main():
    args = sys.argv[1:]
    verify = args and args[0] == '--verify'
    if verify:
        args = args[1:]
    if len(args) != 1:
        raise SystemExit(__doc__)
    path = Path(args[0].strip('"'))
    digest, n, counts = inspect(path)
    if verify:
        recs = [json.loads(l) for l in RECORDS.read_text(encoding='utf-8').splitlines() if l.strip()] if RECORDS.exists() else []
        hit = [r for r in recs if r['sha256'] == digest]
        print(('일치: ' + hit[-1]['sealed_at'] + ' 봉인본과 같습니다.') if hit else '불일치: 봉인 기록에 없는 파일입니다 (내용이 바뀌었을 수 있음).')
        sys.exit(0 if hit else 2)
    rec = {'file_name': path.name, 'sha256': digest, 'rows': n, 'types': counts,
           'sealed_at': datetime.now(timezone.utc).isoformat()}
    RECORDS.parent.mkdir(parents=True, exist_ok=True)
    with RECORDS.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'봉인 완료: {n}문항 {counts}\nSHA-256 {digest}\n기록: {RECORDS}')


if __name__ == '__main__':
    main()
