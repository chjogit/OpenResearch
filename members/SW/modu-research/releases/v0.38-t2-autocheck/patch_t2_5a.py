"""v0.38 T2-5(J27) 자기주식 취득 카드의 「하루 평균 매입 필요 금액」을 평일 수가 아니라 거래일 수(한국거래소 휴장일 반영)로 나눈다.
- 근거 사본 자기주식 취득 결정 219건으로 재 보니 평일로 세면 하루 평균이 평균 5.7%(최대 10.5%) 작게 나왔음(휴장일만큼 나누는 날이 많음).
- 「취득 예상 기간」 줄의 「(평일 N일)」 → 「(거래일 N일)」. 휴장일 표가 없는 해가 끼면 그해만 평일로 세고 그 사실을 같은 줄에 적는다.
- 기존 카드 값이 바뀌는 변경 — 약속서 v1.4 「값이 바뀐 칸」에 적는다.
고칠 곳을 먼저 모두 확인하고, 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1]); rel = 'mrn/filing.py'
PAIRS = [
    ("        n += d0.weekday() < 5; d0 += timedelta(days=1)\n    return n\n",
     "        n += d0.weekday() < 5; d0 += timedelta(days=1)\n    return n\n\n\n"
     "def trading_days(a, b):\n"
     "    \"\"\"v0.38 T2-5(J27): a~b(양끝 포함) 거래일 수(한국거래소 휴장일 반영)와, 휴장일 표가 없는 해가 끼었으면 그 알림(없으면 빈 글).\"\"\"\n"
     "    from . import tradecal as C\n"
     "    return C.count(a, b), C.note(a, b).strip().rstrip('.')\n"),
    ("        if s and e:\n            fact('취득 예상 기간', f\"{s} ~ {e}\" + (f\" (평일 {weekdays(s, e)}일)\" if e >= s else ' (원문 그대로 — 종료일이 시작일보다 앞섬)'))\n",
     "        td, tdn = trading_days(s, e) if (s and e and e >= s) else (0, '')          # v0.38 T2-5(J27) 거래일(휴장일 반영)\n"
     "        if s and e:\n            fact('취득 예상 기간', f\"{s} ~ {e}\" + (f\" (거래일 {td}일\" + (f' — {tdn}' if tdn else '') + ')' if e >= s else ' (원문 그대로 — 종료일이 시작일보다 앞섬)'))\n"),
    ("        if a is not None and s and e and weekdays(s, e) == 0:\n            held.append(f'하루 평균 매입 필요 금액: 원문의 취득 기간({s} ~ {e})으로는 평일 수를 셀 수 없음 — 보류')\n",
     "        if a is not None and s and e and td == 0:\n            held.append(f'하루 평균 매입 필요 금액: 원문의 취득 기간({s} ~ {e})으로는 거래일 수를 셀 수 없음 — 보류')\n"),
    ("            n = weekdays(s, e); per = a / n\n", "            n = td; per = a / n\n"),
    ("                 '취득 예정 금액 ÷ 취득 기간 평일 수 ÷ 공시 전 20거래일 평균 거래대금 × 100 (공휴일은 빼지 않은 근사)', r, '%')\n",
     "                 '취득 예정 금액 ÷ 취득 기간 거래일 수(한국거래소 휴장일 반영) ÷ 공시 전 20거래일 평균 거래대금 × 100' + (f' — {tdn}' if tdn else ''), r, '%')\n"),
]
s = (N / rel).read_text(encoding='utf-8')
if 'def trading_days' in s:
    print(f'{rel}: 이미 적용됨'); sys.exit(0)
for old, _ in PAIRS:
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 「{old[:60]!r}」 자리를 정확히 하나 찾지 못함({s.count(old)}) — 아무것도 바꾸지 않음')
for old, new in PAIRS:
    s = s.replace(old, new)
(N / rel).write_text(s, encoding='utf-8', newline=''); print(f'{rel}: {len(PAIRS)}곳 적용')
