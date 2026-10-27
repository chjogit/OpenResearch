# 에이전트 출력 데이터 계약 (r4-1.0)

기초기획서 R4 3장과 교재 제2판 27장(주장과 원문 연결)을 코드로 옮긴 계약입니다.
에이전트 1(거시경제)·에이전트 3(투자심리·수급)은 `run_agent()` 결과의 `contract`에 이 JSON을 담습니다.
오케스트레이터·화면·Verifier는 이 형식만 읽으면 됩니다.

- 스키마 파일: `ch_agents/schema/agent_output.schema.json` (JSON Schema 2020-12)
- 생성: `ch_agents/contract.py`의 `build()`
- 검사: `contract.validate(c)` (스키마), `contract.link_errors(c)` (claimId 중복·근거 ID 연결)

## 1. 필드

| 필드 | 뜻 | R4 항목 |
| --- | --- | --- |
| `reportId` | `RPT-<에이전트>-<종목>-<기준일>-<내용 해시 8자>`. 같은 입력·같은 주장이면 같은 ID | reportId |
| `agent.id`, `agent.module` | 교재 번호와 모듈명 (`1`·`agent1_macro`, `3`·`agent3_sentiment_flow`) | 번호 체계 |
| `asOf`, `observationPeriod` | 분석 기준일, 관측 기간 | 자료 기준일 |
| `summary` | 핵심 진단 문장과 근거 ID | |
| `claims[].claimId` | 주장 ID `C01`… 주장과 반대 근거를 이어서 매김 | claimId |
| `claims[].role` | `main` 주장, `counter` 반대 근거 | 반대 근거 |
| `claims[].type` | `fact` 사실, `interpretation` 해석, `forecast` 예측 (`typeLabel`은 한글) | 사실·해석·예측 |
| `claims[].text` / `template` | 값을 채운 문장 / 장부 키(`{S2}`)가 남은 원문 | |
| `claims[].evidenceIds` | 근거 ID `E01`… `evidence[]`와 1:1 | evidenceId |
| `claims[].sourceTags` | `[출처: Neon core.…, 기준일]` | 출처 태그 |
| `claims[].verification` | Verifier 결과 (`passed`만 남음. 실패한 주장은 출력에서 빠지고 `verification.results`에 기록) | Verifier 연동 |
| `downsideRisks[]` | 하방 위험 `R01`… | 하방 위험 |
| `upsideFactors[]` | 긍정 요인 `U01`… | |
| `unverified[]` | 미확인 상태. `category`: 무자료 / 미확인 전제 / 판단 보류, `status`: 미확인 / 일부 확인 | 미확인 상태 |
| `evidence[]` | 근거 목록. 숫자(`number`)·문서(`document`)·공시(`disclosure`) | |
| `evidence[].dataDate` | 자료 기준일 (관측 시점, 사업보고서는 `FY2025`) | 자료 기준일 |
| `evidence[].publishedAt` | 공개시각 (문서·공시). 거시 지표는 공표 시각 미수집이라 `null` | 공개시각 |
| `evidence[].valueType` | 실측·계산·대용치·회사 공시 / 문서 종류 | |
| `evidence[].cited` | 이번 출력에서 인용했는지 | |
| `codeFindings[]` | 코드 판정 문장 (LLM 무관) | |
| `verification` | 대조 문장 수, 통과 수, 제외 문장 수, claimId별 결과 | Verifier |
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
2. `fact`·`interpretation` 주장은 근거 ID가 1개 이상 있어야 합니다 (`link_errors`가 검사).
3. 근거 ID는 장부 순서(숫자 → 문서)로 매기므로 같은 입력이면 같은 ID입니다. 다른 출력과 섞을 때는 `reportId`와 함께 씁니다.
4. 오케스트레이터가 요약을 바꿔도 `claimId`·`evidenceId`·검토 상태의 연결은 유지합니다 (교재 11장).
5. 반대 근거와 하방 위험은 사용자 성향과 상관없이 늘 포함합니다 (교재 8장).

## 3. 예시 (테스트 픽스처의 가상 데이터, 실제 종목 값 아님)

일부 배열은 줄였습니다.

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
