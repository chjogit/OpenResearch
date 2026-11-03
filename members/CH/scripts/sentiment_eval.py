"""P03-F08 감성 평가셋 (Windows cmd, members\\CH 폴더에서).

표본 만들기 (라벨러용 눈가림 파일 + 사전 라벨이 든 원본):
    python scripts\\sentiment_eval.py sample 2026-10-28

라벨러 두 명이 eval_blind.csv 의 label_a·label_b 에 negative/neutral/positive/irrelevant(또는 부정/중립/긍정/무관)를
적고, 의견이 다르면 label_final 에 조정 결과를 적은 뒤:
    python scripts\\sentiment_eval.py score eval_blind.csv

CSV 는 커밋하지 않습니다 (문서 제목·요약이 들어 있음).

[#39] 3인 라벨 시트 (라벨러 JT·SH·CH → A·B·C, 최종 확인 SW):
    python scripts\sentiment_eval.py sheets 2026-11-03 eval_sets\2026-11-03   # 메인+kic-opinion 읽기 전용, 약 600건
    # 라벨러별 labeler_A/B/C.xlsx 를 나눠 주고, 돌려받은 파일을 eval_sets\2026-11-03\returned\ 에 같은 이름으로 넣은 뒤:
    python scripts\sentiment_eval.py score3 eval_sets\2026-11-03              # kappa·SW 확인 목록·정답·사전 감성 성능
    # SW 가 sw_check_list.csv 의 마지막 열을 채워 sw_resolved.csv(id,감성) 로 저장하고 score3 를 다시 실행
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ch_agents import sentiment_eval as se  # noqa: E402


def main(argv):
    if len(argv) >= 2 and argv[0] == "sample":
        full = se.sample("eval_full.csv", argv[1])
        blind = se.sample("eval_blind.csv", argv[1], blind=True, rows=se.load(full))
        print(f"저장: {full} (사전 라벨 포함, 채점용), {blind} (라벨러용)")
    elif len(argv) >= 3 and argv[0] == "sheets":
        rows = se.sample_rows(argv[1])
        print(json.dumps(se.build_sheets(rows, argv[2], argv[1]), ensure_ascii=False, indent=1))
    elif len(argv) >= 2 and argv[0] == "score3":
        print(json.dumps(se.score3(argv[1], argv[1]), ensure_ascii=False, indent=1))
    elif len(argv) >= 2 and argv[0] == "score":
        rows = se.merge_dict_labels(se.load(argv[1]), se.load("eval_full.csv"))
        print(json.dumps(se.score(rows), ensure_ascii=False, indent=1))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
