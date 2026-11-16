"""OpenResearch(공개 저장소) members/SW 로 올릴 묶음 만들기 (PM 2026-11-16). 원본 폴더는 읽기만 한다.
쓰는 법: (엔진 가상환경 python) pr_pack.py <OpenResearch 저장소 폴더>
- 코드·시험·문서·도구·변경 기록만 담는다. 자료(Neon 사본·KIS 시세/수급·증권사 PDF·DB 파일)·키·백업·가상환경·결과물(영상·음성)은 담지 않는다.
- 비밀 검사: ① 지금 PC의 실제 키 값(local-env.cmd 로 읽힌 환경 변수)이 어느 파일에든 들어 있으면 멈춘다(가장 확실한 검사)
             ② 키 모양(sk-ant-, sk_…, DB 주소의 비밀번호, crtfc_key=40자 등)이 있으면 멈춘다  ③ 이메일 주소가 보이면 알려 준다
- 결과: members/SW/modu-research/ (이전 내용은 지우고 새로 채움), PACK_MANIFEST.txt(파일·크기·sha256)"""
import hashlib, os, re, shutil, sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2]            # 2차_모두의리서치_cluade
if len(sys.argv) < 2:
    raise SystemExit('OpenResearch 저장소 폴더를 알려 주세요.')
REPO = Path(sys.argv[1]).resolve()
if not (REPO / 'members' / 'SW').is_dir() or not (REPO / 'agent').is_dir():
    raise SystemExit(f'{REPO} 가 OpenResearch 저장소가 아닌 것 같아요(members/SW 없음).')
DST = REPO / 'members' / 'SW' / 'modu-research'

ENGINE = SRC / 'modu-research-nodes'
PLAN = [  # (원본, 대상, 포함할 하위 항목 또는 None=전체)
    (ENGINE, 'engine', ['mrn', 'tests', 'web', 'scripts', 'docs', 'vendor', 'reused', 'README.md', 'pyproject.toml',
                        'setup.cmd', 'start.cmd', 'stop.cmd', 'test.cmd', 'prepare-rag.cmd', 'apply-quarter.cmd', 'local-env.example.cmd']),
    (SRC / '_tools', 'tools', ['price_refresh', 'flow_refresh', 'backup', 'voice', 'recorder', 'neon_snapshot', 'dart_docs', 'datalab', 'pr_pack']),   # kis(운용실 분봉·모의 결과)는 비공개 원칙이라 뺌
    (None, None, None),
    (SRC / '_screen_jt', 'launchers', None),   # 아래 LAUNCH_OK 로 시연 켜기·끄기·갱신 실행 파일만
]
LAUNCH_OK = re.compile(r'(\.bat|\.ps1)$', re.I)
SKIP_DIRS = {'__pycache__', '.pytest_cache', '.venv', '.venv-AI', '.uv-cache', 'node_modules', '.git', 'data', 'out', 'out_juan',
             '_to_delete', 'before', '모두의리서치_화면'}
SKIP_DIR_PREFIX = ('_backup_before_', 'before_', '.venv')
SKIP_FILES = {'local-env.cmd', '.env', 'last-result.txt', 'probe-result.txt', 'voices.txt', 'stop-token.txt', 'snapshot-error.txt'}
SKIP_SUFFIX = ('.pyc', '.log', '.bak', '.sqlite', '.sqlite3', '.db', '.mp3', '.mp4', '.webm', '.wav', '.zip', '.tgz', '.gz', '.pdf', '.part')
MAX_BYTES = 3 * 1024 * 1024
TEXT_SUFFIX = ('.py', '.md', '.txt', '.cmd', '.bat', '.ps1', '.json', '.jsonl', '.csv', '.js', '.mjs', '.html', '.css', '.toml', '.yml', '.yaml', '.ini', '.cfg', '.sql', '.example')
STRONG = [re.compile(p) for p in (
    rb'sk-ant-[A-Za-z0-9_\-]{20,}',                              # Anthropic
    rb'\bsk_[a-f0-9]{40,}\b',                                    # ElevenLabs
    rb'postgres(?:ql)?://[^\s"\'/:@]+:[^\s"\'@]{6,}@',           # DB 주소 안 비밀번호
    rb'crtfc_key=[0-9a-fA-F]{40}',                               # DART 키가 주소에 박힌 경우
    rb'(?i)(appkey|appsecret|app_key|app_secret)["\']?\s*[:=]\s*["\'][A-Za-z0-9/+=]{30,}["\']',   # KIS
    rb'(?i)xi-api-key["\']?\s*[:=]\s*["\'][A-Za-z0-9_]{20,}["\']')]
EMAIL = re.compile(rb'[A-Za-z0-9._%+-]+@(?:gmail|naver|kakao|daum|hanmail|outlook|hotmail)\.(?:com|net)')
SECRET_ENV = ('KIS_APP_KEY', 'KIS_APP_SECRET', 'DART_API_KEY', 'MODU_NODES_LLM_KEY', 'ELEVENLABS_API_KEY', 'ANTHROPIC_API_KEY', 'DATABASE_URL', 'NEON_DATABASE_URL')


def walk(base, keep):
    items = [base / k for k in keep] if keep else [base]
    for it in items:
        if not it.exists():
            continue
        if it.is_file():
            yield it; continue
        for dp, dn, fn in os.walk(it):
            dn[:] = sorted(d for d in dn if d not in SKIP_DIRS and not d.startswith(SKIP_DIR_PREFIX))
            for f in sorted(fn):
                yield Path(dp) / f


def releases():
    """_releases: 버전별 기록(.md)과 PM이 만든 패치·새 파일만. before*(바꾸기 전 원본, 전태님 원본 포함)는 담지 않음."""
    base = SRC / '_releases'
    for rel in sorted(p for p in base.iterdir() if p.is_dir()):
        for p in sorted(rel.iterdir()):
            if p.is_file() and (p.suffix.lower() == '.md' or (p.suffix == '.py' and (p.name.startswith('patch') or p.name == 'verify_rebuild.py'))):
                yield p
        if rel.name.startswith('screen-') and (rel / 'new').is_dir():   # 엔진 판의 new/ 는 엔진 폴더와 같은 내용이라 뺌(화면 패치만)
            yield from walk(rel, ['new'])


def ok_file(p):
    n = p.name
    return not (n in SKIP_FILES or n.lower().endswith(SKIP_SUFFIX) or (n.startswith('.env') and n != '.env.example') or p.stat().st_size > MAX_BYTES)


def main():
    secrets = [v for v in (os.environ.get(k, '').strip() for k in SECRET_ENV) if len(v) >= 12]
    print(f'원본 {SRC}\n대상 {DST}\n실제 키 값 대조: {len(secrets)}개를 대조합니다(값은 표시하지 않음)')
    plan = []
    for base, name, keep in PLAN:
        if base is None:
            continue
        for p in walk(base, keep):
            if name == 'launchers' and (p.parent != base or not LAUNCH_OK.search(p.name)):
                continue
            plan.append((p, Path(name) / p.relative_to(base)))
    for p in releases():
        plan.append((p, Path('releases') / p.relative_to(SRC / '_releases')))
    keep, skipped, block, mail = [], 0, [], []
    for p, rel in plan:
        if not ok_file(p):
            skipped += 1; continue
        data = p.read_bytes()
        if p.suffix.lower() in TEXT_SUFFIX or p.name.endswith('.example.cmd'):
            for s in secrets:
                if s.encode() in data:
                    block.append(f'{rel}: 이 PC의 실제 키 값이 들어 있음')
            for rx in STRONG:
                if rx.search(data):
                    block.append(f'{rel}: 키 모양({rx.pattern[:24].decode(errors="replace")}…)')
            if EMAIL.search(data):
                mail.append(str(rel))
        keep.append((p, rel, data))
    if block:
        print('\n멈춤: 비밀로 보이는 것이 있어 아무것도 바꾸지 않았어요.')
        for b in sorted(set(block))[:30]:
            print('  -', b)
        sys.exit(3)
    if DST.exists():
        shutil.rmtree(DST)
    lines, total = [], 0
    for p, rel, data in keep:
        out = DST / rel; out.parent.mkdir(parents=True, exist_ok=True); out.write_bytes(data)
        total += len(data); lines.append(f'{hashlib.sha256(data).hexdigest()}  {len(data):>9}  {rel.as_posix()}')
    (DST / 'PACK_MANIFEST.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    shutil.copyfile(Path(__file__).resolve().parent / 'SW_README.md', DST.parent / 'README.md')   # members/SW/README.md
    (DST.parent / '.gitignore').write_text('# SW 폴더 안전장치: 자료·키·결과물은 올리지 않음\n**/data/\n**/out/\n**/.venv*/\n*.sqlite*\n*.db\nlocal-env.cmd\n.env\n*.mp3\n*.mp4\n*.webm\n*.zip\n*.pdf\n', encoding='utf-8')
    by = {}
    for _, rel, data in keep:
        by[rel.parts[0]] = by.get(rel.parts[0], 0) + len(data)
    print(f'\n담음 {len(keep)}개 · {total/1e6:.1f}MB · 뺀 것 {skipped}개(자료·결과물·큰 파일 등)')
    for k, v in sorted(by.items()):
        print(f'  {k:10s} {v/1e6:6.2f}MB')
    if mail:
        print(f'\n알림: 이메일 주소가 보이는 파일 {len(mail)}개 — 공개돼도 괜찮은지 확인하세요:')
        for m in mail[:15]:
            print('  -', m)
    print('\n다음: PR_3_올리기.bat')


if __name__ == '__main__':
    main()
