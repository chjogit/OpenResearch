"""원천 자료(_sources) 보관본 만들기 (PM 2026-11-16). 원본 폴더는 읽기만 하고 아무것도 바꾸지 않는다.
쓰는 법: python backup_sources.py [구글 드라이브 폴더]   (생략하면 PC의 「내 드라이브」를 자동으로 찾음)
1) _sources 전체(증권사 보고서·DART 원문·Neon 사본·datalab)를 압축본 한 개로 만든다
   - 이미 압축된 파일(pdf·zip·gz·tgz)은 그대로 담고, 글자 파일(jsonl·json 등)만 압축한다
   - 글자 파일 안에 키 모양(sk-ant-…)이나 비밀번호가 든 DB 주소가 있으면 담지 않고 알려 준다
2) 압축본을 다시 열어 모든 파일의 sha256을 원본과 대조한다
3) 구글 드라이브 데스크톱(「내 드라이브」)이 있으면 그리로 복사하고, 복사본도 sha256 대조한다
   없으면 압축본 위치를 열어 주니 drive.google.com 에 끌어다 놓으면 된다
※ 증권사 보고서 PDF가 들어 있으므로 박사님 개인 드라이브에만 두고 공유하지 마세요(저작권).
※ 이 도구는 아무것도 지우지 않습니다."""
import datetime, hashlib, json, os, re, shutil, sys, zipfile
from pathlib import Path

ROOT = Path(os.environ.get('MODU_SRC_ROOT') or Path(__file__).resolve().parents[2])
SRC = ROOT / '_sources'
DEST = Path(os.environ.get('MODU_BACKUP_DIR') or ROOT.parent / '_백업_모두의리서치')
STAMP = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
NAME = f'모두의리서치_원천자료_{STAMP}.zip'
STORED = ('.pdf', '.zip', '.gz', '.tgz', '.png', '.jpg', '.jpeg')
TEXT = ('.jsonl', '.json', '.txt', '.html', '.csv', '.sha256', '.md', '.bak-before-rename')
SECRET_RE = re.compile(rb'(sk-ant-[A-Za-z0-9_\-]{20,}|postgres(?:ql)?://[^\s"\'/:@]+:[^\s"\'@]+@)')
CHUNK = 1 << 20


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(CHUNK), b''):
            h.update(b)
    return h.hexdigest()


def files():
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames.sort()
        for f in sorted(filenames):
            p = Path(dirpath) / f
            yield p.relative_to(ROOT).as_posix(), p


def find_drive():
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    if os.name == 'nt':
        for L in 'DEFGHIJKLMNOPQRSTUVWXYZ':
            for n in ('내 드라이브', 'My Drive'):
                p = Path(f'{L}:/') / n
                if p.is_dir():
                    return p
    for p in (Path.home() / '내 드라이브', Path.home() / 'My Drive', Path.home() / 'Google Drive'):
        if p.is_dir():
            return p
    return None


def main():
    if not SRC.is_dir():
        print('원천 자료 폴더가 없습니다:', SRC); sys.exit(1)
    DEST.mkdir(parents=True, exist_ok=True)
    need = sum(p.stat().st_size for _, p in files())
    free = shutil.disk_usage(DEST).free
    print(f'원천 자료 {need/1e9:.2f}GB · 저장할 곳 남은 공간 {free/1e9:.1f}GB')
    if free < need * 1.1:
        print('남은 공간이 부족합니다. 멈춥니다.'); sys.exit(1)
    out = DEST / NAME
    part = out.with_suffix('.zip.part')
    manifest, skipped, n = {}, [], 0
    with zipfile.ZipFile(part, 'w', allowZip64=True) as z:
        for rel, p in files():
            low = p.name.lower()
            if low.endswith(TEXT) and SECRET_RE.search(p.read_bytes()):
                skipped.append(rel); continue
            mode = zipfile.ZIP_STORED if low.endswith(STORED) else zipfile.ZIP_DEFLATED
            z.write(p, rel, compress_type=mode)
            manifest[rel] = sha_file(p)
            n += 1
            if n % 2000 == 0:
                print(f'  담는 중… {n}개')
        info = {'만든 시각': STAMP, '원본 폴더': str(SRC), '파일 수': len(manifest),
                '원본 크기(GB)': round(need / 1e9, 3), '비밀 모양이 있어 뺀 파일': skipped,
                '주의': '증권사 보고서 PDF 포함 — 개인 보관용, 공유 금지(저작권)'}
        z.writestr('00_보관정보.json', json.dumps(info, ensure_ascii=False, indent=1))
        z.writestr('00_SHA256SUMS.txt', ''.join(f'{h}  {r}\n' for r, h in manifest.items()))
        z.writestr('00_복원방법.txt', RESTORE)
    print('압축본을 다시 열어 대조하는 중…')
    bad = []
    with zipfile.ZipFile(part) as z:
        for rel, h in manifest.items():
            d = hashlib.sha256()
            with z.open(rel) as f:
                for b in iter(lambda: f.read(CHUNK), b''):
                    d.update(b)
            if d.hexdigest() != h:
                bad.append(rel)
    if bad:
        print('대조 실패:', bad[:5]); part.rename(out.with_suffix('.zip.FAILED')); sys.exit(1)
    part.rename(out)
    zsha = sha_file(out)
    out.with_name(out.name + '.sha256').write_text(f'{zsha}  {out.name}\n', encoding='utf-8')
    print(f'보관본 완료: {out}')
    print(f'  파일 {len(manifest)}개 · {out.stat().st_size/1e9:.2f}GB · 모든 파일 sha256 일치')
    if skipped:
        print(f'  ⚠ 비밀 모양이 있어 담지 않은 파일 {len(skipped)}개: {skipped[:5]}')

    drive = find_drive()
    if not drive:
        print('\n구글 드라이브 데스크톱(「내 드라이브」)을 찾지 못했습니다.')
        print('  drive.google.com 을 열고, 방금 열리는 폴더의 zip 과 .sha256 두 파일을 끌어다 놓으세요.')
        if os.name == 'nt':
            os.startfile(str(DEST)); os.startfile('https://drive.google.com/drive/my-drive')
        return
    target = drive / '모두의리서치_보관본'
    target.mkdir(parents=True, exist_ok=True)
    print(f'\n구글 드라이브로 복사 중: {target}')
    shutil.copyfile(out, target / out.name)
    shutil.copyfile(out.with_name(out.name + '.sha256'), target / (out.name + '.sha256'))
    if sha_file(target / out.name) != zsha:
        print('  ⚠ 드라이브 복사본 대조 실패. 다시 실행해 주세요.'); sys.exit(1)
    print('  드라이브 복사본 sha256 일치. 작업표시줄 구글 드라이브 아이콘에서 「업로드 완료」를 확인하세요.')


RESTORE = """모두의리서치 원천 자료 보관본 복원 방법
1. 이 zip을 빈 폴더에 풉니다.
2. 풀린 _sources 폴더를 프로젝트 폴더(2차_모두의리서치_cluade) 안으로 옮깁니다(기존 것이 있으면 이름을 바꿔 두고).
3. 00_SHA256SUMS.txt 로 파일이 보관 때와 같은지 확인할 수 있습니다.
4. _sources/neon/LATEST.txt 가 엔진이 읽는 최신 사본을 가리킵니다.
※ 증권사 보고서 PDF 포함 — 개인 보관용, 공유 금지.
"""

if __name__ == '__main__':
    main()
