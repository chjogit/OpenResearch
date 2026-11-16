"""v0.38 이름 바꿈 2: 화면·안내 문장의 「관심 종목」을 새 이름 「관심회사」에 맞춤(주석은 그대로). 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
EDITS = {
    'mrn/autocheck.py': [
        ("'empty': '관심 종목 없음'", "'empty': '관심회사 없음'"),
        ("message='관심 종목이 없어 확인할 회사가 없어요.'", "message='관심회사가 없어 확인할 회사가 없어요.'"),
        ("message=f'관심 종목 {len(tickers)}곳 중 {done}곳 확인", "message=f'관심회사 {len(tickers)}곳 중 {done}곳 확인"),
    ],
    'mrn/watch.py': [
        ("f'관심 종목은 {LIMIT}개까지 저장할 수 있어요.'", "f'관심회사는 {LIMIT}곳까지 담을 수 있어요.'"),
    ],
    'web/watch.js': [
        ('title="관심 종목에서 빼기"', 'title="관심회사에서 빼기"'),
        ('관심 종목의 최근 ${a.window_days || 14}일 공시가 아직 없어요.', '관심회사의 최근 ${a.window_days || 14}일 공시가 아직 없어요.'),
    ],
    'tests/test_v038_watch.py': [
        ("self.assertIn('2개까지', r.json()['detail'])", "self.assertIn('2곳까지', r.json()['detail'])   # v0.38 이름 바꿈: 「관심회사는 n곳까지」"),
    ],
    'web/easy.html': [
        ('<h3>관심 종목 공시 <span class="hint">(최근 14일 · 자동 확인)</span></h3>', '<h3>최근 14일 공시 <span class="hint">(자동 확인)</span></h3>'),
    ],
}
done = (N / 'web/easy.html').read_text(encoding='utf-8').count('<h3>최근 14일 공시 <span class="hint">(자동 확인)</span></h3>')
if done:
    print('이미 적용됨'); sys.exit(0)
for rel, pairs in EDITS.items():
    s = (N / rel).read_text(encoding='utf-8')
    for old, new in pairs:
        if s.count(old) != 1:
            raise SystemExit(f'{rel}: 「{old[:40]}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
for rel, pairs in EDITS.items():
    p = N / rel; s = p.read_text(encoding='utf-8')
    for old, new in pairs:
        s = s.replace(old, new)
    p.write_text(s, encoding='utf-8', newline='')
    print(f'{rel}: {len(pairs)}곳 적용')
