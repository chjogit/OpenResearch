"""v0.38 T2-4e 화면 간 숫자 동일 시험(tests/test_v0379_closeout.py)에 공시 숫자 카드를 더한다(v0.38 안전장치: 기능마다 카드 추가).
기존 다섯 카드 시험은 그대로 돌고, 같은 시험 여섯 개를 공시 4종(소각·자기주식 취득·배당·잠정실적)으로 한 번 더 돈다.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1]); rel = 'tests/test_v0379_closeout.py'
s = (N / rel).read_text(encoding='utf-8')
if 'class SameNumbersFilingCard' in s:
    print(f'{rel}: 이미 적용됨'); sys.exit(0)
LOOP = '        for card in CARDS:\n'
ONE = [
    ("class SameNumbersEverywhere(EasyBase):\n    def run_card(self, card):\n        rid = self.c.post('/api/easy/run', json={'card': card, 'company': CO, 'cutoff': CUT}).json()['id']\n",
     "class SameNumbersEverywhere(EasyBase):\n    CARDS = CARDS\n\n"
     "    def run_card(self, card):\n        card, _, no = card.partition(':')                         # v0.38 T2-4e 공시 카드는 'filing:접수번호'\n"
     "        rid = self.c.post('/api/easy/run', json={'card': card, 'company': CO, 'cutoff': CUT, **({'rcept_no': no} if no else {})}).json()['id']\n"),
    ("    def run_direct(self, card):\n        r = self.c.post('/api/runs', json={'doc': plan(card, CO, CUT)})\n",
     "    def run_direct(self, card):\n        card, _, no = card.partition(':')\n        r = self.c.post('/api/runs', json={'doc': plan(card, CO, CUT, no)})\n"),
    ("\n\nclass FixedLimits(EasyBase):\n",
     "\n\nclass SameNumbersFilingCard(SameNumbersEverywhere):\n"
     "    \"\"\"v0.38 T2-4e: 공시 숫자 카드도 입구 2개 × 보는 곳 4개에서 숫자·근거·보류가 같고, 같은 입력 두 번이면 확인 번호까지 같다.\"\"\"\n"
     "    CARDS = ('filing:20260720800001', 'filing:20260720000002', 'filing:20260806800005', 'filing:20260714800007')   # 소각 · 자기주식 취득 · 배당 · 잠정실적\n\n"
     "    def setUp(self):\n"
     "        super().setUp()\n"
     "        import os, tempfile\n"
     "        from tests.test_v038_filing import make_docs\n"
     "        self.docs = tempfile.TemporaryDirectory(); os.environ['MODU_NODES_DART_DOCS'] = os.path.join(self.docs.name, 'dart_docs')\n"
     "        make_docs(os.environ['MODU_NODES_DART_DOCS'])\n\n"
     "    def tearDown(self):\n"
     "        import os\n"
     "        os.environ.pop('MODU_NODES_DART_DOCS', None); self.docs.cleanup()\n"
     "        super().tearDown()\n"
     "\n\nclass FixedLimits(EasyBase):\n"),
]
if s.count(LOOP) != 6:
    raise SystemExit(f'{rel}: 카드 반복문 6곳을 찾지 못함({s.count(LOOP)}) — 아무것도 바꾸지 않음')
for old, _ in ONE:
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 「{old[:60]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
s = s.replace(LOOP, '        for card in self.CARDS:\n')
for old, new in ONE:
    s = s.replace(old, new)
(N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {6 + len(ONE)}곳 적용')
