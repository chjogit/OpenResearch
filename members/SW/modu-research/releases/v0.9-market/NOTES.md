# v0.9-market — T06 가격·거래량 자료 + N09·N10 기술적 분석

- 추가: mrn/market.py (Neon 사본 읽기: manifest·표 해시 재대조, 기준시점 확정 거래일까지만, fsc 행만, 공백·가격제한폭 초과 변동 표시)
- T06 not_connected → real (설정: 기업, 사본 이름(비우면 최신), 거래일 수 260/520/1300)
- N09 not_connected → real: 기준 종가, 1주~1년 수익률, 20/60/120일 이동평균과 차이, 1년 최고·최저, 거래량 20/120일, 거래대금, 방향이 다른 지표
- N10 not_connected → partial: 실현 변동성 20/60/252일, 1년 최대 낙폭, 거래량 급증일(직전 120일 대비 3σ), 60일 평균 위 비율. 국면 분류·원인 해석은 보류
- 예시 사례 6번 「주가 흐름과 거래량 기본 보기」, 계획 에이전트 템플릿 price-basic
- 자료: _sources/neon/<asof>/ (PC에서 _tools/neon_snapshot/run-neon-snapshot.cmd로 생성). 앱은 DB에 접속하지 않음
- 시험: 76개 통과(신규 10, 실제 사본 시험 포함), 2차_실제 기준선 898 일치, 헤드리스 브라우저 점검(콘솔 오류 0)
- 되돌리기: ..\v0.8.1-rag\app.tgz 또는 ..\v0.2-stable\restore.cmd (DB 변경 없음)
