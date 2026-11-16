"""v0.32 T3 배우는 길 — 기관 리서치의 세 가지 규율(출처·시점·사실과 가정 구분)과 재현을 손으로 익히는 과제 9개.

진도는 실제로 한 일에서 스스로 알아낸다(실행·가정·확인서·공유 기록). 화면 안에서만 일어나는 일(근거 열기,
작동 원리 보기, 기준 날짜 바꾸기)은 화면이 알려 준 표시만 받는다. 새 표 하나(learn_marks)만 더한다.
"""
import json

CLIENT_MARKS = ('evidence', 'strip', 'then')
STAGES = [('read', '1단계 · 읽기', '답을 읽고, 숫자의 출처를 확인하는 습관'),
          ('think', '2단계 · 따져 보기', '그때 알 수 있던 것과 내 생각을 나눠 보기'),
          ('prove', '3단계 · 증명하기', '같은 근거면 같은 결과 — 남이 확인할 수 있게')]
TASKS = [
    {'id': 'ask', 'stage': 'read', 'title': '첫 질문 하기', 'how': '회사 하나를 고르고 질문 카드 하나를 눌러 보세요.',
     'why': '리서치는 결론이 아니라 질문에서 시작해요.'},
    {'id': 'evidence', 'stage': 'read', 'title': '숫자 하나의 근거 열기', 'how': '답에서 숫자 줄을 눌러 원문·계산 방법·자료 지문을 확인해 보세요.',
     'why': '기관 리서치의 첫 규율 — 출처를 댄다.'},
    {'id': 'strip', 'stage': 'read', 'title': '작동 원리 보기', 'how': '답 아래 「작동 원리」 띠의 단계를 하나 눌러 보거나, 위쪽 「앱의 작동원리」를 열어 보세요.',
     'why': '답이 어떻게 만들어졌는지 알아야 얼마나 믿을지 정할 수 있어요.'},
    {'id': 'then', 'stage': 'think', 'title': '그때는 어땠나? 비교하기', 'how': '답 아래 「그때는 어땠나?」로 기준 날짜를 바꿔 지금과 견줘 보세요.',
     'why': '두 번째 규율 — 그때 알 수 있던 것만으로 판단한다(뒤늦은 지혜 빼기).'},
    {'id': 'crowd', 'stage': 'think', 'title': '내 가정 적기', 'how': '「증권사들은 실적을 어떻게 보나?」에서 올해 실적에 대한 내 가정을 적어 보세요.',
     'why': '세 번째 규율 — 사실과 가정을 섞지 않는다. 내 생각을 숫자로 적으면 가정이 돼요.'},
    {'id': 'note', 'stage': 'think', 'title': '내 예상 채점표에 이유 남기기', 'how': '「내 예상 채점표」에서 내 가정 옆에 왜 그렇게 봤는지 한 줄 적어 보세요.',
     'why': '실적이 나와 채점될 때, 무엇을 맞히고 무엇을 놓쳤는지 배우는 재료가 돼요.'},
    {'id': 'verify', 'stage': 'prove', 'title': '확인서로 다시 계산하기', 'how': '근거 확인서(또는 공유용 페이지)를 「근거검증」(확인서로 다시 계산해 보기)에 넣어 보세요.',
     'why': '같은 근거·같은 기준 날짜면 누가 계산해도 같은 결과가 나와야 해요.'},
    {'id': 'share', 'stage': 'prove', 'title': '공유용 페이지 만들기', 'how': '답 아래 「공유용 페이지 내려받기」로 남에게 보낼 파일을 만들어 보세요.',
     'why': '내 결론이 아니라 내 근거를 넘기면, 받는 사람이 스스로 확인할 수 있어요.'},
    {'id': 'expert', 'stage': 'prove', 'title': '전문가 모드에서 단계 이어 보기', 'how': '전문가 모드의 「예시 사례」를 하나 불러와 실행해 보세요.',
     'why': '답이 지나온 단계를 그림으로 보고, 바꿔서 다시 계산하는 법을 익혀요.'},
]
DDL = 'CREATE TABLE IF NOT EXISTS learn_marks(owner_id TEXT NOT NULL, task TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY(owner_id, task))'


def ensure(store):
    with store.lock, store.connect() as c:
        c.execute(DDL)


def mark(store, owner, task, at):
    if task not in CLIENT_MARKS:
        raise ValueError('알 수 없는 과제예요.')
    ensure(store)
    with store.lock, store.connect() as c:
        c.execute('INSERT OR IGNORE INTO learn_marks VALUES(?,?,?)', (owner, task, at))


def _done(store, owner):
    from .journal import ensure as j_ensure
    ensure(store); j_ensure(store)
    done = {}
    with store.connect() as c:
        for r in c.execute('SELECT task, at FROM learn_marks WHERE owner_id=?', (owner,)):
            done[r['task']] = r['at']
        def first(sql, args):
            r = c.execute(sql, args).fetchone()
            return r[0] if r else None
        aud = lambda a: first('SELECT MIN(at) FROM audit WHERE owner_id=? AND action=?', (owner, a))
        for t, a in (('verify', 'easy.verify'), ('share', 'easy.share')):
            v = aud(a)
            if v:
                done[t] = v
        v = first('SELECT MIN(submitted_at) FROM crowd_assumptions WHERE owner_id=?', (owner,))
        if v:
            done['crowd'] = v
        v = first('SELECT MIN(at) FROM hypothesis_notes WHERE owner_id=?', (owner,))
        if v:
            done['note'] = v
        for r in c.execute('SELECT doc, created_at FROM runs WHERE owner_id=? ORDER BY created_at LIMIT 500', (owner,)):
            try:
                meta = json.loads(r['doc']).get('meta') or {}
            except Exception:
                meta = {}
            k = 'ask' if meta.get('ui') == 'easy' else 'expert'
            done.setdefault(k, r['created_at'])
    return done


SHORT = {'ask': '첫 질문', 'evidence': '근거 열기', 'strip': '작동 원리', 'then': '그때와 비교', 'crowd': '내 가정 적기', 'note': '이유 남기기',
         'verify': '다시 계산', 'share': '공유 페이지'}      # v0.36.2 (R7)


def progress(store, owner):
    done = _done(store, owner)
    tasks = [{**t, 'short': SHORT.get(t['id'], t['title']), 'done': t['id'] in done, 'at': (done.get(t['id']) or '')[:16]} for t in TASKS]
    stages = [{'id': s, 'title': ti, 'sub': sub, 'tasks': [t for t in tasks if t['stage'] == s]} for s, ti, sub in STAGES]
    for s in stages:
        s['done'] = sum(t['done'] for t in s['tasks'])
    n = sum(t['done'] for t in tasks)
    nxt = next((t for t in tasks if not t['done']), None)
    return {'done': n, 'total': len(tasks), 'stages': stages, 'next': nxt['id'] if nxt else None}
