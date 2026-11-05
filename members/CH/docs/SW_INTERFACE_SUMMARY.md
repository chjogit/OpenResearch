# CH 노드 인터페이스 요약 (SW 오케스트레이터 연동용) — r4-1.4 갱신

원본: `.scratch/agent-split/sw-interface-summary.md`(2026-11-02, #21)를 옮겨 **전망 결론(r4-1.4, #54)** 을 더했습니다.

## CH 담당 노드
| 에이전트 번호 | 노드 | 종류 |
|---|---|---|
| 3 거시경제·정책 | N05 기업별 거시 노출 / N06 시나리오·민감도 | 기본 / 확장 |
| 4 수급 | N07 유동성·거래대금 / N08 수급 전환·가격 불일치 | 기본 / 확장 |
| 6 투자심리·뉴스 | N11 감성·불확실성 / N12 후속 시장 반응 검증 | 기본 / 확장 |

정의 위치: `members/CH/ch_agents/nodes.py`. 실행: `run_agent_nodes(agent_no, ticker, as_of, extension, available)`. 서술·검증·계약까지: `ch_agents.llm.run_node_agent(agent_no, ticker, ...)`.

## 호출·반환 스키마 (pydantic, 알 수 없는 필드 거절)
- NodeTask: `task_id`, `node_id`, `target_ticker`, `as_of_date`, `input_data_ids`, `parameters`, `constraints`
- NodeResult: `status`(SUCCESS / PARTIAL_SUCCESS / DATA_INSUFFICIENT / FAILED), `artifacts`, `evidence_links`, `missing_items`/`unresolved`, `execution_meta`, 확장 스킵 시 `prediction_skipped_reason`

## 규칙
- 모든 조회가 `as_of` 필수, 기준일 당일 포함·다음 날부터 제거. 진술 태그 Fact / Computation / Prediction / Interpretation. 상충 신호는 `conflicts`(평균 없음).
- 미확보 입력: 호가 잔량, 세부 투자 주체, 거시 수정 이력 — `missing_items` 로 표시.
- 데이터 계약 `r4-1.4`: r4-1.3 필드(`agent.agentNos`, `claims[].tag`, `nodes[]`, `nodeSummary`, `conflicts`, `predictionSkippedReason`) + **`outlook`**(아래). 기존 필드·상태값 불변, `outlook` 이 없는 옛 결과도 그대로 읽힘.

## 전망 결론 `outlook` (에이전트 3·4·6 각각, r4-1.4)
각 에이전트가 자기 영역의 **기준일 다음 거래일부터 20거래일 가격 방향**을 긍정·중립·부정으로 냅니다. 값은 **정해진 규칙**(규칙 버전 `outlook-r1`, 문서 `docs/OUTLOOK_RULES.md`)이 정하고 LLM 은 쓰지 않습니다. 매수·매도·보유 결론과 가격 수준은 없습니다.

예시 (삼성전자, 에이전트 4, 기준일 2026-11-04):
```json
"outlook": {
  "direction": "negative", "directionLabel": "부정", "horizonDays": 20, "startAfter": "2026-11-04",
  "reasonCode": null, "reason": null, "tag": "Prediction",
  "positiveFactors": [],
  "negativeFactors": [{"signalId": "flow_foreign", "text": "외국인 20일 순매수 강도 -4.34%: 순매도 우세(규칙 기준 초과)",
                       "template": "외국인 20일 순매수 강도 {S4}: 순매도 우세(규칙 기준 초과)", "tag": "Computation", "evidenceKeys": ["S4"], "evidenceIds": []}],
  "signals": [{"id": "flow_foreign", "state": "negative", "...": "..."}, {"id": "flow_institution", "state": "neutral", "...": "..."}],
  "ledger": {"S4": {"label": "외국인 20일 순매수 강도(거래대금 대비)", "value": -4.34, "display": "-4.34%", "dataDate": "2026-11-03"}},
  "hitRate": {"status": "unverified", "rate": null, "n": null, "reason": "측정 전 (적중률 결과 파일 없음 — #55)", "text": "과거 적중률: 미검증 (측정 전 …)"},
  "ruleVersion": "outlook-r1", "limit": "수급 자료는 시세보다 하루 늦게 적재됨 …", "note": "세 에이전트 결론의 종합은 오케스트레이터(SW) 담당입니다 …"
}
```
- **`hitRate.verdict`(`edge`·`indistinct`·`unverified`) + `verdictLabel` + `notice`**(#58): 판정이 `edge`(기준선 대비 우위 있음)가 아니면 **종합 가중에 쓰지 말 것**. 현재 에이전트 4·3 은 `indistinct`(기준선과 구별 안 됨), 에이전트 6 은 `unverified`. `notice` 는 화면에 그대로 붙일 고정 문구입니다. 판정 규칙은 `docs/OUTLOOK_BACKTEST.md` 5-1.
- 중립이면 `reasonCode`: `mixed`(혼재) · `insufficient`(근거 부족) · `weak`(신호 미약).
- **종합 시 주의**: ① `중립(weak)` 은 '약한 신호'이지 '반대 의견'이 아닙니다 — 에이전트 3은 신호가 2개뿐이라 중립이 많습니다. ② `hitRate.status` 가 `unverified` 이면 그 에이전트 결론에는 과거 검증 근거가 없으니 가중에 쓰지 마세요(`measured` 일 때만 `rate`·`n`·`ci95` 참고). 적중률은 #55 결과 파일이 생기면 채워집니다. ③ 세 결론은 근거 키가 서로 다른 영역이라 독립으로 보이지만, 수급과 심리는 같은 사건을 반영할 수 있습니다. ④ 에이전트 6 감성은 정확도 56.6% 기준선, 에이전트 3 은 지표 수정 이력 미보관. ⑤ 결론 확정·가격 수준 표현은 어디에도 없어야 합니다 — 종합 결론에서도 같습니다.

## SW 님과 정할 것
1. 실행 노드 수 규칙(6+N)과 확장 선택 전달 방식(`parameters` 필드 이름).
2. `MAX_REPAIR_ATTEMPTS` 를 오케스트레이터가 정할지 노드 기본값을 쓸지.
3. 다른 팀원 노드(N01~N04, N09·N10)도 같은 NodeTask/NodeResult 를 쓸지.
4. (신규) 종합 규칙에서 `hitRate`·`reasonCode` 를 어떻게 쓸지(SW 몫).
