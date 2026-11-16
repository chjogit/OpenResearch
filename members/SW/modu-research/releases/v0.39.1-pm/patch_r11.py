"""v0.39.1 R11(전태님 REQUESTS 2026-11-13): 질문 카드 짧은 이름(`/api/easy/cards`의 `cards[].short`)을 화면 이름표에 맞춘다. 값(글자)만 바꿈, 칸은 그대로.
원래 질문형 제목(title)은 그대로. 고칠 곳을 먼저 확인하고 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
OLD = ("SHORT = {'events': '요즘 공시·뉴스', 'price': '주가·수급', 'earnings': '실적', 'macro': '환율·금리', 'holders': '대주주·경영진', 'relations': '함께 움직인 것',\n"
       "         'forecasts': '증권사 전망', 'edi': '주가와 실적의 시차', 'nowcast': '매출 조기 확인', 'attention': '관심도', 'reaction': '공시 반응'}\n")
NEW = ("SHORT = {'events': '최근 주요 사건', 'price': '주가 흐름·매매 주체', 'earnings': '실적 요약', 'macro': '환율·금리 영향', 'holders': '대주주·지분 변동',   # v0.39.1 R11 화면 이름표\n"
       "         'relations': '함께 움직인 지표', 'forecasts': '증권사 실적 전망', 'edi': '주가 선반영 햇수', 'nowcast': '이번 분기 매출 조기 추정',\n"
       "         'attention': '관심도 추이', 'reaction': '공시별 과거 주가 반응'}\n")
p = N / 'mrn/easy.py'; s = p.read_text(encoding='utf-8')
if "v0.39.1 R11" in s:
    print('mrn/easy.py: 이미 적용됨'); sys.exit(0)
if s.count(OLD) != 1:
    raise SystemExit(f'mrn/easy.py: SHORT 자리를 정확히 하나 찾지 못함({s.count(OLD)}) — 아무것도 바꾸지 않음')
p.write_text(s.replace(OLD, NEW), encoding='utf-8', newline='\n'); print('mrn/easy.py: 고침')
