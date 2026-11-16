# v0.8-rag-xbrl — RAG T1 + DART XBRL
- 추가: mrn/rag (ingest/search/evaluate/cases), mrn/xbrl.py, 「문서·재무」 화면, prepare-rag.cmd, setup에 numpy
- 원천: _sources/dart_full (gongsi-hybrid DART HTML 복사본, 해시 대조)
- 검색 평가(BM25) @10: 동의어 없음 15/16, 포함 16/16 (검색 단계 지표)
- XBRL: 키는 환경변수만, 응답 캐시+해시, N01 표 값과 자동 대조
- 시험 66개 통과
