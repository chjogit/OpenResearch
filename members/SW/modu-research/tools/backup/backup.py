"""모두의리서치 날짜별 백업 (PM 2026-11-15). 원본 폴더는 읽기만 하고 아무것도 바꾸지 않는다.
쓰는 법: python backup.py [백업을 둘 폴더]   (생략하면 프로젝트 폴더 옆 「_백업_모두의리서치」)
- 담는 것: 엔진(코드·화면·시험·문서·데이터베이스), 전태님 화면(코드·회원 DB), 시연 켜기/끄기, _releases(패치·원본·기록), _tools
- 빼는 것: 비밀(local-env.cmd, .env), 가상환경(.venv*), 캐시, 로그, DART 원문 사본(_sources, 1.4GB — 이미 배포 묶음 zip으로 보관됨)
- 데이터베이스(nodes.sqlite, db.sqlite3)는 켜져 있어도 안전하게 복사(sqlite 백업 기능) 후 무결성 검사
- 안전장치: 파일 안에 API 키 모양(sk-ant-)이 있으면 담지 않고 알려 줌
- 끝나면 압축본을 다시 열어 모든 파일의 sha256을 대조"""
import datetime, hashlib, json, os, re, sqlite3, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # 2차_모두의리서치_cluade
DEST = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / '_백업_모두의리서치'
STAMP = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
OUT = DEST / f'모두의리서치_백업_{STAMP}.zip'

INCLUDE = ['modu-research-nodes', '_screen_jt', '_releases', '_tools']
SKIP_DIRS = {'.venv', '.venv-AI', '.uv-cache', '__pycache__', '.pytest_cache', 'node_modules', '.git'}
SKIP_PREFIX = ('_backup_before_',)
SKIP_FILES = {'local-env.cmd', '.env', 'stop-token.txt'}
SKIP_REL = {'modu-research-nodes/data/backup'}
SKIP_SUFFIX = ('.log', '.pyc')
SQLITE = {'modu-research-nodes/data/nodes.sqlite', '_screen_jt/모두의리서치_화면/db.sqlite3'}
SECRET_RE = re.compile(rb'sk-ant-[A-Za-z0-9_\-]{20,}')   # 실제 키 모양만(설명 글의 「sk-ant-」 글자는 통과)


def walk():
    for top in INCLUDE:
        base = ROOT / top
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            rel_dir = Path(dirpath).relative_to(ROOT).as_posix()
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(SKIP_PREFIX)
                                 and f'{rel_dir}/{d}' not in SKIP_REL)
            for f in sorted(filenames):
                rel = f'{rel_dir}/{f}'
                if f in SKIP_FILES or f.endswith(SKIP_SUFFIX) or (f.startswith('.env') and f != '.env.example'):
                    continue
                yield rel, Path(dirpath) / f


def sqlite_copy(src):
    tmp = Path(tempfile.mkdtemp()) / 'copy.sqlite'
    with sqlite3.connect(f'file:{src}?mode=ro', uri=True) as a, sqlite3.connect(tmp) as b:
        a.backup(b)
    with sqlite3.connect(tmp) as c:
        ok = c.execute('PRAGMA integrity_check').fetchone()[0]
    return tmp, ok


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest, skipped_secret, db_checks = {}, [], {}
    part = OUT.with_suffix('.zip.part')
    with zipfile.ZipFile(part, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for rel, p in walk():
            if rel in SQLITE:
                tmp, ok = sqlite_copy(p)
                db_checks[rel] = ok
                data = tmp.read_bytes()
            else:
                data = p.read_bytes()
                if SECRET_RE.search(data):
                    skipped_secret.append(rel)
                    continue
            z.writestr(rel, data)
            manifest[rel] = hashlib.sha256(data).hexdigest()
        info = {'만든 시각': STAMP, '원본 폴더': str(ROOT), '파일 수': len(manifest),
                '데이터베이스 검사': db_checks, '키 모양이 있어 뺀 파일': skipped_secret,
                '빠진 것(일부러)': 'local-env.cmd, .env, 가상환경(.venv*), 캐시, 로그, _sources(DART 원문 사본 — 배포 묶음 zip에 있음)'}
        z.writestr('00_백업정보.json', json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr('00_SHA256SUMS.txt', ''.join(f'{h}  {r}\n' for r, h in manifest.items()))
        z.writestr('00_복원방법.txt', RESTORE)
    bad = []
    with zipfile.ZipFile(part) as z:
        if z.testzip() is not None:
            bad.append('압축 손상')
        for rel, h in manifest.items():
            if hashlib.sha256(z.read(rel)).hexdigest() != h:
                bad.append(rel)
    if bad:
        print('백업 검증 실패:', bad[:5]); part.rename(OUT.with_suffix('.zip.FAILED')); sys.exit(1)
    part.rename(OUT)
    size = OUT.stat().st_size / 1e6
    print(f'백업 완료: {OUT}')
    print(f'  파일 {len(manifest)}개 · {size:.1f}MB · 압축본 다시 열어 sha256 전부 일치')
    for rel, ok in db_checks.items():
        print(f'  데이터베이스 {rel}: {ok}')
    if skipped_secret:
        print(f'  ⚠ 키 모양(sk-ant-)이 있어 담지 않은 파일 {len(skipped_secret)}개: {skipped_secret[:5]}')
    olds = sorted(DEST.glob('모두의리서치_백업_*.zip'))
    total = sum(p.stat().st_size for p in olds) / 1e6
    print(f'  백업 폴더에 지금 {len(olds)}개 · 합계 {total:.0f}MB (오래된 것은 직접 지우세요. 이 도구는 아무것도 지우지 않습니다)')


RESTORE = """모두의리서치 백업 복원 방법
1. 이 zip을 빈 폴더에 풉니다(원래 폴더에 덮어쓰지 마세요).
2. 풀린 폴더의 modu-research-nodes, _screen_jt, _releases, _tools 를 원래 프로젝트 폴더로 옮깁니다.
3. 빠진 것을 다시 채웁니다:
   - modu-research-nodes/local-env.cmd : 키(DART·KIS·Claude)를 직접 다시 넣기 (local-env.example.cmd 참고)
   - _screen_jt/모두의리서치_화면/.env : SECRET_KEY 새로 만들고 나머지 줄은 .env.example 참고
   - 가상환경: 엔진은 setup.cmd, 화면은 시연PC 설치안내대로 requirements.txt 설치
   - DART 원문 사본(_sources/dart_docs): 배포 묶음 modu-research-dart-docs_*.zip 에서 풀기
4. 00_SHA256SUMS.txt 로 파일이 백업 때와 같은지 확인할 수 있습니다.
"""

if __name__ == '__main__':
    main()
