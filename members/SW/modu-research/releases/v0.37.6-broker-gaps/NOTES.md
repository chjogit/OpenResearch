# v0.37.6 — 증권사 보고서 수집 빈틈 고침 · 카드가 흐린 이유를 사실대로
기준 v0.37.5 · 시험 347개 통과

## 바뀐 것
1. 수집 도구(_tools/broker_fetch/bulk_fetch.py) 확인 규칙 `mentions`: 글자가 거의 없는 그림 PDF는 확인할 수 없으므로 받음 · 종목명은 띄어쓰기 무시
2. 새 도구 recheck_skipped.py: 이미 건너뛴 PDF를 새 규칙으로 다시 봄 → 9건 inbox로 옮김(DB손해보험·NH투자증권·현대해상·삼성E&A·포스코인터내셔널·KB금융 2·LG전자·우리금융지주), 2건 그대로(IBK 산일전기 — 첫 두 쪽에 종목명 없음, 대신 — 네이버가 다른 회사로 잘못 분류)
3. 「증권사들은 실적을 어떻게 보나?」 카드가 흐린 이유 두 가지로 구분
   - 받은 보고서 없음: 「보고서를 모으는 곳(네이버 증권 리서치)에 최근 이 회사 보고서가 올라오지 않아…」
   - 받았으나 승인된 전망 없음: 「받아 두었지만, 확인을 마친 실적 전망 숫자가 아직 없어요…」

## PM이 할 일
stop.cmd → _tools\broker_fetch\run-register-recheck.cmd (9건 등록·스캔) → start.cmd

## 되돌리기
before/mrn 의 easy.py·server.py → modu-research-nodes/mrn, before/_tools/bulk_fetch.py → _tools/broker_fetch. 옮긴 9건은 inbox에서 inbox/_skipped 로 되돌리면 됨
