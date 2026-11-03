"""지배구조판정 노트북의 근거 표·규칙 판정(13개)을 JSON으로 꺼낸다. build_governance_contract.py가 이 파일을 합친다.

하는 일
- 노트북 사본을 임시 폴더에서 실행한다(원본 노트북·agent_memo 파일은 바꾸지 않는다)
- 마지막에 셀 하나를 덧붙여 evidence·result 표를 data/governance_rules_<회사>_<기준일>.json으로 저장한다
- DART 키는 .env에서 읽어 커널 환경변수로만 넘긴다. 값은 출력하지 않는다

사용 방법(프로젝트 폴더에서):
  .venv-sentiment\\Scripts\\python.exe scripts\\export_notebook_rules.py
"""
from pathlib import Path
import json
import os
import shutil
import sys
import tempfile

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "지배구조판정_삼성전자.ipynb"
COMPANY = "삼성전자"
AS_OF = "2026-10-27"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith("DART_API_KEY="):
            os.environ["DART_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
    nb = nbformat.read(NOTEBOOK, as_version=4)
    nb.cells.append(nbformat.v4.new_code_cell(
        "import json\n"
        "json.dump({'mode': MODE, 'as_of': AS_OF, 'data_mode': data_mode,"
        " 'evidence': json.loads(evidence.to_json(orient='records', force_ascii=False)),"
        " 'result': json.loads(result.to_json(orient='records', force_ascii=False)), 'memo': memo},"
        " open('rules_export.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)"))
    work = Path(tempfile.mkdtemp(prefix="p05_nb_"))
    try:
        NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": str(work)}}).execute()
        data = json.loads((work / "rules_export.json").read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if data["as_of"] != AS_OF:
        sys.exit(f"노트북 기준일 {data['as_of']}이 {AS_OF}와 다르다")
    out = ROOT / "data" / f"governance_rules_{COMPANY}_{AS_OF.replace('-', '')}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"모드 {data['mode']} | 근거 {len(data['evidence'])} | 판정 {len(data['result'])} | 저장 {out.name}")


if __name__ == "__main__":
    main()
