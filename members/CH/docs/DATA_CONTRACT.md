# 에이전트 출력 데이터 계약 (r4-1.0)

기초기획서 R4 3장과 교재 제2판 27장(주장과 원문 연결)을 코드로 옮긴 계약입니다.
에이전트 1(거시경제)·에이전트 3(투자심리·수급)은 `run_agent()` 결과의 `contract`에 이 JSON을 담습니다.
오케스트레이터·화면·Verifier는 이 형식만 읽으면 됩니다.

> 상태: **팀 확정 검토안 (2026-10-28)**. 4장의 결정 항목을 팀이 정하면 "확정"으로 바꾸고, 이후 바뀌는 내용은 5장 규칙대로 `schemaVersion`을 올립니다.

- 스키마 파일: `ch_agents/schema/agent_output.schema.json` (JSON Schema 2020-12)
- 생성: `ch_agents/contract.py`의 `build()`
- 검사: `contract.validate(c)` (스키마), `contract.link_errors(c)` (claimId 중복·근거 ID 연결)

## 1. 필드

| 필드 | 뜻 | R4 항목 |
| --- | --- | --- |
| `reportId` | `RPT-<에이전트>-<종목>-<기준일>-<내용 해시 8자>`. 해시는 `agent`·`target`·`asOf`·`mode`·`claims`만으로 만들므로, 같은 기준일에 같은 주장(인용한 값 포함)이면 같은 ID. 인용하지 않은 근거나 위험·요약만 달라지면 ID가 같을 수 있음 | reportId |
| `agent.id`, `agent.module` | 교재 번호와 모듈명 (`1`·`agent1_macro`, `3`·`agent3_sentiment_flow`) | 번호 체계 |
| `asOf`, `observationPeriod` | 분석 기준일, 관측 기간 | 자료 기준일 |
| `summary` | 핵심 진단 문장과 근거 ID | |
| `claims[].claimId` | 주장 ID `C01`… 주장과 반대 근거를 이어서 매김. Verifier에서 빠진 주장의 번호는 비어 있을 수 있음(`C01`, `C03`) | claimId |
| `claims[].role` | `main` 주장, `counter` 반대 근거 | 반대 근거 |
| `claims[].type` | `fact` 사실, `interpretation` 해석, `forecast` 예측 (`typeLabel`은 한글) | 사실·해석·예측 |
| `claims[].text` / `template` | 값을 채운 문장 / 장부 키(`{S2}`)가 남은 원문 | |
| `claims[].evidenceIds` | 근거 ID `E01`… `evidence[]`와 1:1. 근거가 100개를 넘으면 그 출력 안에서는 `E001`처럼 자릿수가 늘어남(형식은 `E` + 숫자) | evidenceId |
| `claims[].sourceTags` | `[출처: Neon core.…, 기준일]` | 출처 태그 |
| `claims[].verification` | Verifier 결과. 출력에 남는 주장은 모두 `passed` (스키마에는 `failed`도 있으나 현재 코드는 실패 주장을 빼므로 나오지 않음) | Verifier 연동 |
| `downsideRisks[]` | 하방 위험 `R01`… | 하방 위험 |
| `upsideFactors[]` | 긍정 요인 `U01`… | |
| `unverified[]` | 미확인 상태. `category`: 무자료 / 미확인 전제 / 판단 보류, `status`: 미확인 / 일부 확인. 반대 근거와 하방 위험이 모두 비면 `item: "반대 근거·하방 위험"`(판단 보류)이 들어감 | 미확인 상태 |
| `evidence[]` | 근거 목록. 숫자(`number`)·문서(`document`)·공시(`disclosure`) | |
| `evidence[].dataDate` | 자료 기준일 (관측 시점, 사업보고서는 `FY2025`) | 자료 기준일 |
| `evidence[].publishedAt` | 공개시각 (문서·공시). 원천에 시각이 없으면 날짜만(`2026-10-13`). 숫자 근거는 공표 시각 미수집이라 `null` | 공개시각 |
| `evidence[].valueType` | 실측·계산·대용치·회사 공시 / 문서 종류 | |
| `evidence[].cited` | 이번 출력에서 인용했는지 | |
| `codeFindings[]` | 코드 판정 문장 (LLM 무관) | |
| `verification` | `results`: 수치 대조(fact_source_verifier) 기록. 주장은 통과·실패 모두 claimId와 함께 남고, 요약·위험 등 주장이 아닌 문장은 실패한 것만 `claimId: null`로 남음. `checked`·`passed`: `results`의 건수와 그중 통과 수. `removedSentences`: 형식 검사(장부 키·판정 방향·중복)와 수치 대조에서 뺀 문장 수 합계. 형식 검사에서 빠진 주장은 claimId를 받기 전이라 `results`에 없음 | Verifier |
| `status` | 실행 상태 문장. `완료`, `완료 (수정 1회)`, `완료 (일부 문장 제외)`, `규칙 기반 대체 (LLM 호출 실패: …)` 등 자유 문장 (4장 결정 항목 1) | |
| `dataQuality[]` | 수집 품질 주의 (quality.api_status) | |
| `disclaimer` | 투자 권유 아님 문구 | 투자 권유 배제 |

에이전트별 추가 필드

| 에이전트 | 필드 | 뜻 |
| --- | --- | --- |
| 1 | `exposure[]` | 거시 변수별 노출 등급(높음/중간/낮음)과 근거 ID, 회사 공시 기반 여부 |
| 1 | `premises[]` | 미확인 전제: 환헤지 여부·비율, 결제 통화·시점, 판가 전가력, 달러 비용 비중, 수출 비중, 차입 조건 (확인/일부 확인/미확인) |
| 3 | `anomalies[]` | 이상 징후 문장과 근거 ID |
| 3 | `baseline[]` | 규칙·사전 기준선 비교 (신호, 기준선 방식, 상태, 근거 ID) |
| 3 | `duplicateSignals[]` | 중복 신호 묶음 `X1`: 함께 나타난 신호와 근거 ID. 독립 근거로 세지 않음 |
| 3 | `sentimentModel` | 감성 점수 방식 (키워드 감성 사전 기준선, 학습 모델 아님, 성능 미검증) |

## 2. 규칙

1. 숫자는 `evidence[]`의 DB 값만 씁니다. 주장 문장의 숫자는 Verifier가 근거 값과 1:1 대조합니다.
2. `fact`·`interpretation` 주장은 근거 ID가 1개 이상 있어야 합니다. 생성 단계(형식 검사)는 주장·반대 근거 모두 근거 없는 사실·해석을 빼고, `link_errors`는 `role: main`만 다시 검사합니다 (4장 결정 항목 3).
3. 근거 ID는 장부 순서(숫자 → 문서)로 매기므로 같은 입력이면 같은 ID입니다. 다른 출력과 섞을 때는 `reportId`와 함께 씁니다.
4. 오케스트레이터가 요약을 바꿔도 `claimId`·`evidenceId`·검토 상태의 연결은 유지합니다 (교재 11장).
5. 반대 근거와 하방 위험은 사용자 성향과 상관없이 늘 요청합니다 (교재 8장). 검증을 통과한 것이 하나도 없으면 비워 두지 않고 `unverified[]`에 `반대 근거·하방 위험`(판단 보류)을 넣어, 화면이 "반대 근거 없음"을 "반대 근거를 확인하지 못함"으로 보여 주게 합니다.

## 3. 예시 (테스트 픽스처의 가상 데이터, 실제 종목 값 아님)

일부 배열은 줄였습니다. 그래서 `codeFindings`·`anomalies`·`baseline`이 가리키는 근거 ID 일부(E06·E23 등)는 아래 `evidence[]`에 없습니다. 실제 출력은 `link_errors`를 통과합니다.

```json
{
  "schemaVersion": "r4-1.0",
  "reportId": "RPT-3-005930-20261026-2078d610",
  "agent": {
    "id": 3,
    "module": "agent3_sentiment_flow",
    "name": "에이전트 3 투자심리·수급 분석 (Sentiment & Flow)"
  },
  "target": {
    "ticker": "005930",
    "name": "삼성전자",
    "market": "KR"
  },
  "mode": "expert",
  "asOf": "2026-10-26",
  "observationPeriod": "수급 2026-05-11~2026-10-23 (120거래일)",
  "generatedAt": "2026-10-27T18:00:00+09:00",
  "status": "완료",
  "userInput": {},
  "summary": {
    "text": "외국인은 20일간 순매도(-20,000주)이고 거래대금은 평소보다 많습니다(3.00배).",
    "evidenceIds": [
      "E02",
      "E25"
    ]
  },
  "claims": [
    {
      "claimId": "C01",
      "role": "main",
      "text": "외국인은 20일간 -20,000주 순매도했다.",
      "template": "외국인은 20일간 {S2} 순매도했다.",
      "type": "fact",
      "typeLabel": "사실",
      "evidenceIds": [
        "E02"
      ],
      "sourceTags": [
        "[출처: Neon core.investor_flow_daily, 2026-10-23]"
      ],
      "verification": {
        "status": "passed",
        "checkedBy": "fact_source_verifier",
        "unmatched": []
      }
    },
    {
      "claimId": "C02",
      "role": "main",
      "text": "거래대금 급증(3.00배)과 뉴스 논조 개선은 같은 사건을 반영할 수 있어 하나의 근거로 본다.",
      "template": "거래대금 급증({S25})과 뉴스 논조 개선은 같은 사건을 반영할 수 있어 하나의 근거로 본다.",
      "type": "interpretation",
      "typeLabel": "해석",
      "evidenceIds": [
        "E25"
      ],
      "sourceTags": [
        "[출처: Neon core.price_daily, 2026-10-23]"
      ],
      "verification": {
        "status": "passed",
        "checkedBy": "fact_source_verifier",
        "unmatched": []
      }
    },
    {
      "claimId": "C03",
      "role": "counter",
      "text": "주가는 20일 -8.30% 변했다.",
      "template": "주가는 20일 {S26} 변했다.",
      "type": "fact",
      "typeLabel": "사실",
      "evidenceIds": [
        "E26"
      ],
      "sourceTags": [
        "[출처: Neon core.price_daily, 2026-10-23]"
      ],
      "verification": {
        "status": "passed",
        "checkedBy": "fact_source_verifier",
        "unmatched": []
      }
    }
  ],
  "upsideFactors": [],
  "downsideRisks": [
    {
      "riskId": "R01",
      "text": "외국인 순매도가 이어지면 수급 부담이 커질 수 있다.",
      "evidenceIds": []
    }
  ],
  "unverified": [
    {
      "item": "외국인 집중 매매 점검",
      "reason": "강도 계산에 필요한 65거래일 미만",
      "category": "무자료",
      "status": "미확인",
      "evidenceIds": []
    },
    {
      "item": "기관 집중 매매 점검",
      "reason": "강도 계산에 필요한 65거래일 미만",
      "category": "무자료",
      "status": "미확인",
      "evidenceIds": []
    },
    {
      "item": "블로그 감성(최근 7일)",
      "reason": "점수 붙은 문서 3건 (최소 5건)",
      "category": "무자료",
      "status": "미확인",
      "evidenceIds": []
    }
  ],
  "nextChecks": [
    "외국인 5일 순매수 방향 전환 여부"
  ],
  "evidence": [
    {
      "evidenceId": "E02",
      "ledgerKey": "S2",
      "kind": "number",
      "label": "외국인 20일 순매수 수량",
      "value": -20000.0,
      "unit": "주",
      "display": "-20,000주",
      "valueType": "계산",
      "group": "수급",
      "dataDate": "2026-10-23",
      "publishedAt": null,
      "source": "core.investor_flow_daily (네이버 투자자별 매매)",
      "sourceTag": "[출처: Neon core.investor_flow_daily, 2026-10-23]",
      "url": null,
      "note": null,
      "cited": true
    },
    {
      "evidenceId": "E25",
      "ledgerKey": "S25",
      "kind": "number",
      "label": "거래대금 배율(최근 5일 ÷ 직전 60일)",
      "value": 3.0,
      "unit": "배",
      "display": "3.00배",
      "valueType": "계산",
      "group": "거래",
      "dataDate": "2026-10-23",
      "publishedAt": null,
      "source": "core.price_daily",
      "sourceTag": "[출처: Neon core.price_daily, 2026-10-23]",
      "url": null,
      "note": "1보다 크면 평소보다 거래가 많음",
      "cited": true
    },
    {
      "evidenceId": "E26",
      "ledgerKey": "S26",
      "kind": "number",
      "label": "20일 주가 수익률",
      "value": -8.298755186721996,
      "unit": "%chg",
      "display": "-8.30%",
      "valueType": "계산",
      "group": "가격·시장",
      "dataDate": "2026-10-23",
      "publishedAt": null,
      "source": "core.price_daily",
      "sourceTag": "[출처: Neon core.price_daily, 2026-10-23]",
      "url": null,
      "note": null,
      "cited": true
    }
  ],
  "codeFindings": [
    {
      "text": "외국인 120거래일 연속 순매도 (120일)",
      "evidenceIds": [
        "E06"
      ]
    },
    {
      "text": "기관 120거래일 연속 순매수 (120일)",
      "evidenceIds": [
        "E12"
      ]
    }
  ],
  "verification": {
    "checker": "agent/verifier/fact_source_verifier.py",
    "checked": 3,
    "passed": 3,
    "removedSentences": 0,
    "results": [
      {
        "claimId": "C01",
        "ok": true,
        "unmatched": [],
        "evidenceIds": [
          "E02"
        ]
      },
      {
        "claimId": "C02",
        "ok": true,
        "unmatched": [],
        "evidenceIds": [
          "E25"
        ]
      },
      {
        "claimId": "C03",
        "ok": true,
        "unmatched": [],
        "evidenceIds": [
          "E26"
        ]
      }
    ]
  },
  "dataQuality": [],
  "selfScore": 6,
  "disclaimer": "투자 검토 참고치 및 리스크 요약입니다. 매수·매도 추천이나 목표주가가 아닙니다.",
  "anomalies": [
    {
      "text": "이상 징후: 거래대금 급증 (3.00배)",
      "evidenceIds": [
        "E25"
      ]
    },
    {
      "text": "이상 징후: 뉴스 논조 급격한 개선 (+0.500)",
      "evidenceIds": [
        "E34"
      ]
    },
    {
      "text": "이상 징후: 검색 관심 급증 (3.00배)",
      "evidenceIds": [
        "E35"
      ]
    }
  ],
  "baseline": [
    {
      "signal": "거래대금",
      "method": "규칙: 직전 60거래일 평균",
      "rule": "배율 2 이상이면 이례적",
      "status": "기준선 대비 이례적",
      "evidenceIds": [
        "E23",
        "E24",
        "E25"
      ]
    },
    {
      "signal": "뉴스 논조",
      "method": "사전: 키워드 감성 사전 기준선 (학습 모델 아님, 성능 미검증), 직전 8~30일 대비",
      "rule": "변화 절댓값 0.15 이상이면 이례적",
      "status": "기준선 대비 이례적",
      "evidenceIds": [
        "E32",
        "E33",
        "E34"
      ]
    }
  ],
  "duplicateSignals": [
    {
      "clusterId": "X1",
      "signals": [
        "뉴스 논조",
        "검색 관심",
        "거래대금"
      ],
      "evidenceIds": [
        "E34",
        "E35",
        "E25"
      ],
      "rule": "같은 사건을 반영할 수 있어 독립 근거로 중복 계산하지 않음"
    }
  ],
  "sentimentModel": "키워드 감성 사전 기준선 (학습 모델 아님, 성능 미검증)"
}
```

## 4. 팀 확정 때 정할 것

코드를 고치지 않고 현재 동작 그대로 확정해도 됩니다. 각 항목의 제안은 CH 의견입니다.

| # | 항목 | 현재 | 제안 |
| --- | --- | --- | --- |
| 1 | `status` 기계 판독 | 자유 문장 (`규칙 기반 대체 (LLM 호출 실패: TimeoutError)`) | 화면·오케스트레이터가 분기할 수 있게 `statusCode`(`completed` / `completed_partial` / `fallback`)를 추가하고 `status` 문장은 그대로 둠. 추가 필드라 r4-1.1 |
| 2 | 다른 에이전트 모듈 이름 | 스키마는 `agent.id` 1~7, `module`은 `agent<번호>_…` 형식만 검사. 1·3 외 이름 미정 | 각 담당자가 `agent2_…` 식 이름을 정해 이 표에 적음 (스키마 변경 없음) |
| 3 | 반대 근거의 근거 ID 검사 | 생성 단계는 반대 근거도 검사, `link_errors`는 `main`만 | `link_errors`도 `counter`까지 검사 (다른 에이전트가 생성 단계 없이 계약만 맞출 때 대비) |
| 4 | 공개시각 형식 | 문서는 시각이 없으면 날짜만 | 날짜만 있는 값을 허용하고, 화면은 날짜만 보여 줌 (현행 유지) |
| 5 | 근거 ID 자릿수 | 근거 수에 따라 `E01` 또는 `E001` | 현행 유지. 받는 쪽은 `E\d+`로 읽음 |

## 5. 버전 규칙

- 필드 추가처럼 기존 소비자가 깨지지 않는 변경: `r4-1.x` (예: 1번 `statusCode` 추가 → `r4-1.1`)
- 필드 이름·의미 변경, 필수 필드 추가, 허용 값 축소: `r4-2.0`
- 버전을 올릴 때는 `contract.SCHEMA_VERSION`, 스키마 파일의 `schemaVersion.enum`, 이 문서 제목을 함께 바꿉니다.

## 6. 다른 에이전트가 맞출 최소 요건

1. 스키마 필수 필드(`schemaVersion`·`reportId`·`agent`·`target`·`mode`·`asOf`·`generatedAt`·`status`·`summary`·`claims`·`downsideRisks`·`unverified`·`evidence`·`verification`·`disclaimer`)를 채웁니다.
2. 문장 속 숫자는 모두 `evidence[]`의 `value`에서 옵니다. 팀 공용 `agent/verifier/fact_source_verifier.py`로 대조합니다.
3. 제출 전 `contract.validate(c) == []`, `contract.link_errors(c) == []`를 확인합니다 (`jsonschema` 패키지가 있으면 `jsonschema.validate`도).
4. 에이전트 고유 필드는 1장의 에이전트별 표처럼 최상위에 추가하고, 근거 연결이 있으면 `evidenceIds`를 씁니다.
