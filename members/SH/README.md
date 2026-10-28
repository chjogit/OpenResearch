# SH 작업 폴더

SH 의 개인 작업 공간입니다. 담당: **산업·사업모델 Agent**, **기술적 분석 Agent**.

- 팀이 함께 쓸 코드가 되면 `agent/` 로 옮겨 PR 로 올립니다.
- `.env`, API 키, DB 접속 주소는 여기에도 커밋하지 않습니다.
- 노트북 실행 결과(`private_outputs/`)·문단 분류 표(`private_data/`)는 DB 원문이 들어 있어 커밋하지 않습니다(`.gitignore`).

## 파일

| 위치 | 내용 |
| --- | --- |
| `sh_agents/basic_agents.py` | 두 Agent(`IndustryBusinessAgent`, `TechnicalAnalysisAgent`), LLM 연결, 페르소나 선택 |
| `sh_agents/model_hooks.py` | 【ML/DL 연결 위치】 `model_tool` 계약, 학습 없는 기준선(키워드 문단 분류·변동성 유지) |
| `sh_agents/personas.py`, `persona_presentation.py`, `persona_evaluation.py` | 이해도 L1~L4 × 성향 A/C(미정 U), 표현 규칙, 페르소나 변경 전후 보존 평가 |
| `sh_agents/quality_gate.py`, `price_checks.py` | 기업별 품질 검사(실행 가능·일부 가능·보류), OHLC·±30%·거래일·기업행위 검사 |
| `sh_agents/neon_agents.py`, `snapshots.py`, `data_inventory.py` | Neon 읽기 전용 조회, 두 Agent 공통 스냅샷, 기업별 보유 현황 |
| `sh_agents/document_selection.py`, `business_sections.py`, `paragraph_labels.py` | 공시 문서 선별, '사업의 내용' 절 탐지, 문단 분류 기준선·사람 정답 평가 |
| `sh_agents/technical_states.py` | 기술 지표의 관측 상태 설명 규칙(예측·신호 아님) |
| `sh_agents/research_contract.py`, `result_verifier.py`, `model_comparison.py` | 주장·근거·버전 계약, 재현 Verifier, ML 채택 판단 |
| `notebooks/` | 실행 노트북과 안내 문서 (아래 표) |
| `examples/` | 합성 A기업 예시 자료·스크립트 |
| `web/research-preview/` | 합성 A기업 리서치 탐색 화면 |
| `docs/` | 페르소나 정의(`PERSONAS.md`), 주장·근거 계약(`RESEARCH_CONTRACT.md`) |
| `tests/` | 패키지 테스트. DB·LLM 없이 실행 |

### 노트북

| 노트북 | 내용 |
| --- | --- |
| `01_산업사업모델_Agent_Neon.ipynb`, `02_기술적분석_Agent_Neon.ipynb` | 실데이터 실행용. `INPUT_MODE` = wait / mock / neon / snapshot |
| `03_인수인계_기본구조_둘러보기.ipynb` | 페르소나·계약·두 Agent 기본 계산·품질 검사·Verifier |
| `04_품질검사_문서선별_공통스냅샷.ipynb` | 가격 검사, 문서 선별, 사업의 내용 절 탐지, 공통 스냅샷, 저장 차단 |
| `05_페르소나_문단분류_관측상태_평가.ipynb` | 페르소나 → 문단 분류 기준선 → 관측 상태 → 보존 평가 → ML 판단 |
| `06_산업사업모델_Agent_기본소스.ipynb`, `07_기술적분석_Agent_기본소스.ipynb` | Agent별 【Python】→【LLM】→【ML/DL 연결 위치】 기본 소스 |

03~07 은 DB·API 키 없이 실행되며 실행 결과가 저장되어 있습니다.

## 실행 (Windows cmd)

```
cd OpenResearch
pip install -r requirements-dev.txt
python -m pytest members\SH\tests -q

cd members\SH
pip install -r requirements-neon-agents.txt
python -m jupyter lab
```

노트북은 `members\SH\notebooks` 에서 열고, `.env` 는 저장소 루트(`OpenResearch\.env`)에 둡니다.
`sh_agents` 를 import 하면 공용 `agent` 패키지(예: `agent.llm`)를 쓰도록 저장소 루트가 자동으로 경로에 추가됩니다.

```python
from sh_agents.basic_agents import AgentSettings, TechnicalAnalysisAgent, select_persona
from sh_agents.snapshots import mock_snapshot, reports_from_snapshot
from sh_agents.neon_agents import execute_report

profile, _ = select_persona(literacy='L1', style='C')
report = reports_from_snapshot(mock_snapshot())[0]
gate, result = execute_report(report, TechnicalAnalysisAgent(settings=AgentSettings.from_persona(profile, window=5)),
                              'technical_analysis')
```

## 확인하지 못한 것

실제 Neon 접속·source 값·공시 제목 형식, Solar 호출, 가격 조정 기준 출처, KRX 거래일 달력·기업행위 자료,
사람이 붙인 문단 정답, 관측 상태 임계값·분류 키워드의 검증. 학습된 ML/DL 모델은 없습니다.
