# 되돌리기 (v0.37 → v0.36.4)
1. stop.cmd
2. `before/mrn/` 의 nodes.py · easy.py · specs.py · dartdocs.py 를 `modu-research-nodes/mrn/` 에 덮어쓰기
3. `mrn/segments.py`, `tests/test_v037_segments.py` 는 남아 있어도 쓰이지 않음(지우지 않아도 됨)
4. start.cmd — 다시 적용하려면 `python apply_v037.py <modu-research-nodes 폴더>` (여러 번 실행해도 안전)
