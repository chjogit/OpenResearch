"""감성 한계 문구 — 한곳 상수. 상태 코드(SENT_MODEL_UNVALIDATED)·스킵 로직과 별개로 사용자 노출 문구만 담는다."""
from __future__ import annotations

# 출처: eval_sets/2026-11-03 score3_out.json (#45 2차 채점, 2026-11-03 기준).
# 사람 라벨 600건(SW 검수) 중 '무관' 제외 440건 기준 키워드 사전 정확도 56.6%.
SENT_EVAL_N = 600
SENT_EVAL_SCORED_N = 440   # 감성 대상(무관 160건 제외)
SENT_EVAL_ACCURACY = "56.6%"
SENT_LIMIT_TEXT = (f"키워드 사전 기준선 — 사람 라벨 {SENT_EVAL_N}건(SW 검수) 중 감성 대상 {SENT_EVAL_SCORED_N}건 기준 "
                   f"정확도 {SENT_EVAL_ACCURACY}, "
                   "긍정 과소 탐지·중립 편향, 개선 전")
