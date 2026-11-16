"""v0.39.1 R12(PM 2026-11-15, Claude API 연결): Claude 최신 모델은 temperature 값을 받지 않는다(HTTP 400 「temperature is deprecated for this model」).
모델 이름이 claude 로 시작하면 temperature 를 빼고, 모든 모델에 답 길이 상한(max_tokens 1024)을 넣는다. 로컬 모델(exaone 등)은 temperature 0 그대로.
고칠 곳(mrn/guide.py, mrn/planner.py 각 1곳)을 먼저 모두 확인하고 하나라도 못 찾으면 아무것도 바꾸지 않는다. 두 번 돌려도 같다."""
import sys
from pathlib import Path

N = Path(sys.argv[1])
OLD = "    body = json.dumps({'model': model, 'temperature': 0, 'messages': [{'role': 'user', 'content': prompt}]}).encode()\n"
NEW = ("    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'max_tokens': 1024}   # v0.39.1 R12\n"
       "    if not model.lower().startswith('claude'):\n"
       "        body['temperature'] = 0                                   # Claude 최신 모델은 temperature 를 받지 않음(400)\n"
       "    body = json.dumps(body).encode()\n")
FILES = ['mrn/guide.py', 'mrn/planner.py']
todo = []
for f in FILES:
    s = (N / f).read_text(encoding='utf-8')
    if 'v0.39.1 R12' in s:
        print(f'{f}: 이미 적용됨'); continue
    if s.count(OLD) != 1:
        raise SystemExit(f'{f}: 고칠 자리를 정확히 하나 찾지 못함({s.count(OLD)}) — 아무것도 바꾸지 않음')
    todo.append((f, s.replace(OLD, NEW)))
for f, s in todo:
    (N / f).write_text(s, encoding='utf-8', newline='\n'); print(f'{f}: 고침')
