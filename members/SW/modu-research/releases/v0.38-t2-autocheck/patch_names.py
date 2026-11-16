"""v0.38 곁가지(PM 결정): 쉬운 화면 위쪽 6개 이름을 쓰는 사람의 말로.
  내 관심 종목 → 관심회사 공시함 · 최근 본 답 → 지난 질문 다시보기 · 가설 일지 → 내 예상 채점표
  배우는 길 → 따라하는 사용법 · 확인서로 다시 계산 → 근거검증 · 작동 원리 공개 → 앱의 작동원리(◎ 표시는 그대로)
화면 글자 + 「따라하는 사용법」 과제 안내 문장 3곳(learn.py, 글자만 — 칸·구조 그대로). 확인서·공유 페이지 안의 문장은 바꾸지 않음
(확인서 내용이 바뀌면 확인 번호가 달라지므로) — 대신 근거검증 화면 제목 아래에 옛 이름 「확인서로 다시 계산해 보기」를 함께 적어 이어지게 함.
여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
MARK = '<!-- v0.38 names -->'

EDITS = {
    'web/easy.html': [
        ('>내 관심 종목</button>', '>관심회사 공시함</button>'),
        ('<button id="nHistory" class="ghost">최근 본 답</button>',
         '<button id="nHistory" class="ghost" title="이 브라우저에서 했던 질문과 답을 다시 열어요">지난 질문 다시보기</button>'),
        ('>가설 일지</button>', '>내 예상 채점표</button>'),
        ('>배우는 길</button>', '>따라하는 사용법</button>'),
        ('<button id="nVerify" class="ghost">확인서로 다시 계산</button>',
         '<button id="nVerify" class="ghost" title="받은 답이 정말 그 근거에서 나왔는지 다시 계산해 확인해요">근거검증</button>'),
        ('>작동 원리 공개</button>', '>앱의 작동원리</button>'),
        ('<b>최근 본 답 다시 따라가기</b>', '<b>지난 질문 다시보기</b>'),
        ('<h2>확인서로 다시 계산해 보기</h2>', '<h2>근거검증 <span class="h2sub">— 확인서로 다시 계산해 보기</span></h2>'),
        ('<h2>내 관심 종목</h2>', '<h2>관심회사 공시함</h2>'),
        ('<h2>내 가설 일지</h2>', '<h2>내 예상 채점표</h2>'),
        ('<h2>배우는 길</h2>', '<h2>따라하는 사용법</h2>'),
        ('<h2>작동 원리 공개 <span class="h2sub">', '<h2>앱의 작동원리 <span class="h2sub">'),
        ('<h2>최근 본 답</h2>', '<h2>지난 질문 다시보기</h2>'),
        ('</body>', MARK + '\n</body>'),
    ],
    'web/easy.js': [
        ('「확인서로 다시 계산해 보기」로 같은 결과가', '「근거검증」으로 같은 결과가'),
        ('`배우는 길 <span class="lcount">', '`따라하는 사용법 <span class="lcount">'),
        ("'가설 일지에서 왜 이렇게 봤는지 적기 →'", "'내 예상 채점표에서 왜 이렇게 봤는지 적기 →'"),
    ],
    'web/index.html': [
        ('근거 확인서 내려받기 · 확인서로 다시 계산</div>', '근거 확인서 내려받기 · 근거검증(확인서로 다시 계산)</div>'),
    ],
    'mrn/learn.py': [
        ('위쪽 「작동 원리 공개」를 열어 보세요.', '위쪽 「앱의 작동원리」를 열어 보세요.'),
        ("'title': '가설 일지에 이유 남기기', 'how': '「가설 일지」에서", "'title': '내 예상 채점표에 이유 남기기', 'how': '「내 예상 채점표」에서"),
        ('「확인서로 다시 계산해 보기」에 넣어 보세요.', '「근거검증」(확인서로 다시 계산해 보기)에 넣어 보세요.'),
    ],
    'tests/test_open_label.py': [
        ("self.assertIn('>작동 원리 공개</button>', s)", "self.assertIn('>앱의 작동원리</button>', s)   # v0.38 이름 바꿈"),
        ("self.assertIn('<h2>작동 원리 공개', s)", "self.assertIn('<h2>앱의 작동원리', s)"),
    ],
}

html = (N / 'web/easy.html').read_text(encoding='utf-8')
if MARK in html:
    print('이미 적용됨'); sys.exit(0)
for rel, pairs in EDITS.items():                       # 먼저 모두 확인(하나라도 안 맞으면 아무것도 바꾸지 않음)
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
