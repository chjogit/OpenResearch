# CH 작업 폴더

CH 의 개인 작업 공간입니다. 실험 노트북, 스크립트, 메모를 자유롭게 두세요.

- 팀이 함께 쓸 코드가 되면 `agent/` 로 옮겨 PR 로 올립니다.
- `.env`, API 키, DB 접속 주소는 여기에도 커밋하지 않습니다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `ch_agents/` | CH 담당 에이전트 패키지 (A1 거시·민감도, A2 재무·밸류에이션·건전성, A4 투자심리·수급) |
| `ch_agents_A1_A2_A4.ipynb` | 위 패키지를 실행·확인하는 노트북 (데이터 확인 → 교차 검증 → 에이전트 실행 → 첨삭 → 일괄 점검) |
| `tests/` | 패키지 테스트. DB·LLM 없이 실행 |
| `solar_pro_4.ipynb` | 6+1 전체 파이프라인 원본. 참고용이며 더 이상 수정하지 않음 |

## 실행 (Windows cmd)

```
cd OpenResearch
pip install -r requirements-dev.txt
python -m pytest members\CH\tests -q
```

노트북은 `members\CH` 폴더에서 열고, `.env`에 `DATABASE_URL`, `UPSTAGE_API_KEY`를 둡니다.

## 출력 계약 (오케스트레이터 전달용)

`run_agent()`가 돌려주는 dict 키입니다.

| 키 | 내용 |
| --- | --- |
| `agent_id`, `agent_name`, `status` | 상태: 완료 / 완료 (수정 1회) / 완료 (일부 문장 제외) / 규칙 기반 대체 |
| `period`, `as_of` | 관측 기간과 기준일 |
| `result` | 핵심진단, 주장(문장·구분·근거 키), 긍정요인, 리스크요인, 미확인, 다음점검, 자체점수, 점수이유 |
| `facts`, `gaps`, `flags` | 숫자 장부, 무자료 목록, 코드 판정 |
| `checks`, `removed`, `attempts` | 코드 검사 결과, 최종 출력에서 뺀 문장, LLM 시도 기록 |
| `analysis`, `source` | 사람이 읽는 마크다운(키를 값으로 바꾼 것), 출처 |

`result`의 문장은 숫자 대신 `{M1}` 같은 키를 담고 있습니다. 값은 `facts[키]["text"]`로 바꿔 씁니다.
