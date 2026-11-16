"""ElevenLabs 내레이션 만들기 (PM 2026-11-16, 설명 영상용). 키는 엔진 local-env.cmd 의 ELEVENLABS_API_KEY(환경 변수)만 쓰고 어디에도 적지 않는다.
쓰는 법 (엔진 가상환경 python):
  tts_make.py sample              → 시험 문장 하나를 한국어 목소리 4개로(out\\sample_*.mp3)
  tts_make.py voices              → 내 계정의 목소리 목록을 voices.txt 에 (이름·ID·언어, 키 없음)
  tts_make.py make [대본파일]      → 대본(기본 narration.txt)의 줄마다 out\\01.mp3, 02.mp3 … 를 만든다
대본 파일: 한 줄 = 한 장면 문장. 빈 줄·# 줄은 건너뜀. 첫 줄에 「voice=목소리ID」, 「model=모델ID」를 적으면 그 값을 씀.
이미 만든 파일은 다시 만들지 않는다(문장이 바뀐 줄만 다시 만듦 → 크레딧 절약). 결과는 last-result.txt."""
import hashlib, json, os, sys, urllib.error, urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = 'https://api.elevenlabs.io'
LOG = []


def say(s):
    LOG.append(s); print(s, flush=True)


def call(path, body=None):
    key = (os.environ.get('ELEVENLABS_API_KEY') or '').strip()
    if not key:
        raise SystemExit('ELEVENLABS_API_KEY 가 없어요. 엔진 폴더 local-env.cmd 에 「set ELEVENLABS_API_KEY=…」 한 줄을 넣어 주세요.')
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={'xi-api-key': key, 'Content-Type': 'application/json', 'Accept': '*/*'},
                                 method='POST' if body is not None else 'GET')
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        msg = e.read()[:300].decode('utf-8', 'replace')
        raise SystemExit(f'ElevenLabs 응답 오류 HTTP {e.code}: {msg}')


def voices():
    js = json.loads(call('/v1/voices'))
    lines = []
    for v in js.get('voices', []):
        lab = v.get('labels') or {}
        lines.append(f"{v.get('name')}\t{v.get('voice_id')}\t{v.get('category')}\t{lab.get('language') or lab.get('accent') or ''}")
    (HERE / 'voices.txt').write_text('이름\tID\t종류\t언어\n' + '\n'.join(lines) + '\n', encoding='utf-8')
    say(f'목소리 {len(lines)}개를 voices.txt 에 적었어요(키 값은 없음). 「cloned」는 복제한 목소리입니다.')
    for l in lines[:30]:
        say('  ' + l)


def make(script):
    p = HERE / script
    rows = [l.strip() for l in p.read_text(encoding='utf-8-sig').splitlines()]
    voice, model = os.environ.get('ELEVENLABS_VOICE', ''), os.environ.get('ELEVENLABS_MODEL', 'eleven_multilingual_v2')
    lines = []
    for l in rows:
        if l.startswith('voice='):
            voice = l[6:].strip(); continue
        if l.startswith('model='):
            model = l[6:].strip(); continue
        if l and not l.startswith('#'):
            lines.append(l)
    if not voice:
        raise SystemExit('목소리 ID가 없어요. 대본 첫 줄에 「voice=목소리ID」를 적어 주세요(voices.txt 참고).')
    out = HERE / 'out'; out.mkdir(exist_ok=True)
    made, kept, chars = 0, 0, 0
    for i, text in enumerate(lines, 1):
        tag = hashlib.sha256(f'{voice}|{model}|{text}'.encode()).hexdigest()[:12]
        f = out / f'{i:02d}.mp3'; meta = out / f'{i:02d}.txt'
        if f.exists() and meta.exists() and meta.read_text(encoding='utf-8').startswith(tag):
            kept += 1; continue
        audio = call(f'/v1/text-to-speech/{voice}?output_format=mp3_44100_128',
                     {'text': text, 'model_id': model, 'voice_settings': {'stability': 0.5, 'similarity_boost': 0.8}})
        f.write_bytes(audio); meta.write_text(f'{tag}\n{text}\n', encoding='utf-8')
        made += 1; chars += len(text)
        say(f'  {i:02d}.mp3 만듦 ({len(text)}자)')
    say(f'끝: 새로 {made}개({chars}자 ≈ 크레딧 {chars}) · 그대로 둔 것 {kept}개 · 모델 {model} · 폴더 {out}')


SAMPLE_TEXT = '모두의리서치는 숫자를 만들지 않습니다. 근거를 보여 줍니다. 삼성전자의 11월 13일 종가는 20만 9천 원, 외국인은 8,216주를 순매수했습니다.'
SAMPLES = [('juan', 'hjCvGtSCRPyjYwe2lDf1'), ('chawoo', 'xMFDeM9Ex3CdGGx9m3uS'), ('hoon', '86GErZIiGJsPO3g7QNxZ'), ('selly', 'ETPP7D0aZVdEj12Aa7ho')]


def sample():
    """같은 시험 문장을 한국어 목소리 4개로 만들어 out/sample_이름.mp3 (이미 있으면 건너뜀)."""
    out = HERE / 'out'; out.mkdir(exist_ok=True)
    model = os.environ.get('ELEVENLABS_MODEL', 'eleven_multilingual_v2')
    for name, vid in SAMPLES:
        f = out / f'sample_{name}.mp3'
        if f.exists():
            say(f'  {f.name} 이미 있음'); continue
        f.write_bytes(call(f'/v1/text-to-speech/{vid}?output_format=mp3_44100_128',
                           {'text': SAMPLE_TEXT, 'model_id': model, 'voice_settings': {'stability': 0.5, 'similarity_boost': 0.8}}))
        say(f'  {f.name} 만듦')
    say(f'시험 문장 {len(SAMPLE_TEXT)}자 × {len(SAMPLES)}목소리 · 모델 {model} · 폴더 {out} — 파일을 더블클릭해 들어 보세요.')


if __name__ == '__main__':
    code = 1
    try:
        a = sys.argv[1:] or ['voices']
        voices() if a[0] == 'voices' else sample() if a[0] == 'sample' else make(a[1] if len(a) > 1 else 'narration.txt')
        code = 0
    except SystemExit as e:
        say(str(e))
    except Exception as e:
        say(f'멈춤: {type(e).__name__}: {str(e)[:200]}')
    finally:
        (HERE / 'last-result.txt').write_text(datetime.now().strftime('%Y-%m-%d %H:%M') + f' (끝 코드 {code})\n' + '\n'.join(LOG) + '\n', encoding='utf-8')
    sys.exit(code)
