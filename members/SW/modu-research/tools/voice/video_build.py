"""모두의리서치 20초 설명 영상 v1 — 장면 프레임을 PIL로 그리고 ffmpeg로 내레이션과 합친다.
쓰는 법: python build.py [음성폴더]   (음성폴더에 01.mp3~04.mp3 가 있으면 그 길이에 맞추고, 없으면 미리보기용 기본 길이·무음)
숫자는 앱 실제 값(2026-11-13, 삼성전자): 종가 209,000원 · 외국인 +8,216주 · 기관 -328,604주 · 수급 대조 40/40."""
import math, shutil, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

W, H, FPS = 1920, 1080, 30
HERE = Path(__file__).resolve().parent
AUD = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / 'audio'
FR = HERE / 'frames'
FONT = {w: f'/usr/share/fonts/opentype/noto/NotoSansCJK-{w}.ttc' for w in ('Regular', 'Medium', 'Bold', 'Black')}
BG, INK, MUTE, BERRY, BERRY_L, GREEN, RED, LINE = '#FBF7FA', '#1E1B26', '#6B6575', '#9B2C5E', '#F3E3EB', '#1F8A5B', '#C0392B', '#E6DCE2'
SUBS = ['질문하면, 근거와 함께 답합니다. 모두의리서치입니다.',
        '공시와 시세, 수급까지 출처를 밝히고, 숫자는 원자료와 하나하나 대조합니다.',
        'AI는 숫자를 만들지 않습니다. 근거에 없는 문장은 스스로 지웁니다.',
        '판단은 당신이, 근거는 모두의리서치가.']
DEFAULT = [4.3, 6.2, 5.6, 3.6]
PAD = 0.2
TEMPO = 1.1   # 20초에 맞추려 말 빠르기 1.1배(음 높이는 그대로)


def f(size, w='Medium'):
    return ImageFont.truetype(FONT[w], size, index=1)   # ttc 1번 = 한국어(KR)


def ease(t):
    t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3


def alpha_color(c, a, bg=BG):
    c = c.lstrip('#'); b = bg.lstrip('#')
    rgb = [int(c[i:i + 2], 16) for i in (0, 2, 4)]; bb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return tuple(int(bb[i] + (rgb[i] - bb[i]) * a) for i in range(3))


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, r, fill=fill, outline=outline, width=width)


def chip(d, x, y, text, fg, bg, size=30, a=1.0):
    ft = f(size, 'Medium'); tw = d.textlength(text, font=ft)
    rrect(d, (x, y, x + tw + 36, y + size + 22), (size + 22) // 2, fill=alpha_color(bg, a))
    d.text((x + 18, y + 9), text, font=ft, fill=alpha_color(fg, a))
    return x + tw + 36


def frame_base(sub, t_in_scene, dur):
    im = Image.new('RGB', (W, H), BG); d = ImageDraw.Draw(im)
    d.text((80, 56), '모두의리서치', font=f(40, 'Black'), fill=BERRY)
    d.text((80 + d.textlength('모두의리서치', font=f(40, 'Black')) + 16, 66), '· 기업분석', font=f(30, 'Medium'), fill=MUTE)
    chip(d, W - 330, 58, '연구용 시연', MUTE, '#EFE9EE', 26)
    # 자막
    a = ease(t_in_scene / 0.3) * ease((dur - t_in_scene) / 0.3)
    ft = f(42, 'Medium'); tw = d.textlength(sub, font=ft)
    bx = (W - tw) / 2 - 36
    rrect(d, (bx, H - 150, bx + tw + 72, H - 70), 18, fill=alpha_color('#1E1B26', 0.92 * a))
    d.text(((W - tw) / 2, H - 140), sub, font=ft, fill=alpha_color('#FFFFFF', a, '#1E1B26') if a > 0.05 else BG)
    return im, d


def scene1(d, t):
    q = '삼성전자 주가 흐름과 누가 샀나?'
    n = int(len(q) * ease(t / 1.4))
    rrect(d, (360, 210, 1560, 310), 50, fill='#FFFFFF', outline=LINE, width=3)
    d.text((420, 232), q[:n] + ('|' if t < 1.6 and int(t * 4) % 2 == 0 else ''), font=f(46, 'Medium'), fill=INK)
    a = ease((t - 1.5) / 0.6)
    if a > 0:
        y0 = 360 + int(40 * (1 - a))
        rrect(d, (360, y0, 1560, y0 + 470), 28, fill=alpha_color('#FFFFFF', a), outline=alpha_color(LINE, a), width=3)
        d.text((410, y0 + 36), '답 카드', font=f(34, 'Bold'), fill=alpha_color(BERRY, a))
        rows = [('자료로 확인', GREEN, '#E3F3EA', '2026-11-13 종가 209,000원'),
                ('자료로 확인', GREEN, '#E3F3EA', '외국인 +8,216주 · 기관 −328,604주 (11-13)'),
                ('계산', BERRY, BERRY_L, '5거래일 누적 외국인 +5,855,908주')]
        for i, (tag, fg, bg, txt) in enumerate(rows):
            b = ease((t - 1.9 - i * 0.35) / 0.4) * a
            if b <= 0:
                continue
            y = y0 + 110 + i * 92
            x = chip(d, 410, y, tag, fg, bg, 28, b)
            d.text((x + 24, y + 2), txt, font=f(40, 'Medium'), fill=alpha_color(INK, b))
        b = ease((t - 3.0) / 0.4) * a
        if b > 0:
            d.text((410, y0 + 400), '출처: 한국투자증권 일별 시세 · 투자자별 매매 (연구용)  |  근거 확인서 보기 ›', font=f(28, 'Regular'), fill=alpha_color(MUTE, b))


def scene2(d, t):
    cards = [('DART 공시', '60분마다 새 공시 확인', '금융감독원 원문'), ('KIS 시세', '일별 종가 · 지수', '한국투자증권 조회'), ('수급', '외국인 · 기관 · 개인 순매수', '투자자별 매매')]
    for i, (h, s1, s2) in enumerate(cards):
        a = ease((t - i * 0.45) / 0.5)
        if a <= 0:
            continue
        x = 200 + i * 520; y = 230 + int(30 * (1 - a))
        rrect(d, (x, y, x + 480, y + 300), 28, fill=alpha_color('#FFFFFF', a), outline=alpha_color(LINE, a), width=3)
        d.text((x + 40, y + 40), h, font=f(52, 'Black'), fill=alpha_color(BERRY, a))
        d.text((x + 40, y + 130), s1, font=f(34, 'Medium'), fill=alpha_color(INK, a))
        d.text((x + 40, y + 190), s2, font=f(28, 'Regular'), fill=alpha_color(MUTE, a))
    a = ease((t - 2.4) / 0.6)
    if a > 0:
        rrect(d, (360, 600, 1560, 800), 28, fill=alpha_color('#E3F3EA', a))
        d.text((420, 630), '바꾸기 전에, 겹치는 날을 1:1로 대조 (점검 8곳 × 5일)', font=f(40, 'Bold'), fill=alpha_color(INK, a, '#E3F3EA'))
        k = int(40 * ease((t - 2.8) / 1.4))
        d.text((420, 700), f'외국인 · 기관 · 개인 순매수   {k}/40 일치', font=f(46, 'Black'), fill=alpha_color(GREEN, a, '#E3F3EA'))
        if k == 40:
            d.text((1440, 650), '✓', font=f(110, 'Black'), fill=GREEN)


def scene3(d, t):
    d.text((360, 200), '보고서 초안 · 문장마다 근거 번호', font=f(36, 'Bold'), fill=MUTE)
    lines = [(True, '11월 13일 종가는 209,000원이다.', 'E2'), (True, '같은 날 외국인은 8,216주를 순매수했다.', 'E4'),
             (False, '외국인이 앞으로도 계속 살 것이다.', '')]
    for i, (ok, txt, ev) in enumerate(lines):
        a = ease((t - i * 0.6) / 0.5)
        if a <= 0:
            continue
        y = 290 + i * 150
        rrect(d, (360, y, 1560, y + 120), 22, fill=alpha_color('#FFFFFF', a), outline=alpha_color(LINE, a), width=3)
        d.text((410, y + 32), txt, font=f(44, 'Medium'), fill=alpha_color(INK if ok else MUTE, a))
        if ok:
            chip(d, 1340, y + 30, ev, BERRY, BERRY_L, 32, a)
        else:
            s = ease((t - 2.2) / 0.6)
            if s > 0:
                tw = d.textlength(txt, font=f(44, 'Medium'))
                d.line((405, y + 62, 405 + tw * s + 10, y + 62), fill=RED, width=7)
            b = ease((t - 2.8) / 0.4)
            if b > 0:
                chip(d, 1180, y + 30, '근거 없음 → 삭제', RED, '#FBE4E1', 30, b)
    a = ease((t - 3.4) / 0.5)
    if a > 0:
        d.text((360, 770), 'AI는 근거 줄만 보고 쓰고, 근거에 없는 숫자·날짜·판단은 엔진이 지웁니다.', font=f(32, 'Regular'), fill=alpha_color(MUTE, a))


def scene4(d, t):
    a = ease(t / 0.6); b = ease((t - 0.9) / 0.6)
    t1, t2 = '판단은 당신이,', '근거는 모두의리서치가.'
    f1 = f(92, 'Black')
    d.text(((W - d.textlength(t1, font=f1)) / 2, 330), t1, font=f1, fill=alpha_color(INK, a))
    d.text(((W - d.textlength(t2, font=f1)) / 2, 470), t2, font=f1, fill=alpha_color(BERRY, b))
    c = ease((t - 1.8) / 0.5)
    if c > 0:
        s = 'KIRI 한국인프라연구원 · 연구용 시연 · 매매 권유가 아닙니다'
        fs = f(30, 'Regular'); d.text(((W - d.textlength(s, font=fs)) / 2, 660), s, font=fs, fill=alpha_color(MUTE, c))


def dur_of(p):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(p)], capture_output=True, text=True).stdout
    return float(out.strip())


def main():
    have = all((AUD / f'{i:02d}.mp3').exists() for i in range(1, 5))
    durs = [dur_of(AUD / f'{i:02d}.mp3') / TEMPO + PAD for i in range(1, 5)] if have else DEFAULT
    if FR.exists():
        shutil.rmtree(FR)
    FR.mkdir()
    k = 0
    for si, (fn, dur) in enumerate(zip((scene1, scene2, scene3, scene4), durs)):
        for j in range(int(round(dur * FPS))):
            t = j / FPS
            im, d = frame_base(SUBS[si], t, dur)
            fn(d, t)
            # 장면 사이 짧은 페이드
            fa = min(1.0, t / 0.25, (dur - t) / 0.25) if si not in (0,) or t > 0.25 else min(1.0, t / 0.25)
            if fa < 1:
                im = Image.blend(Image.new('RGB', (W, H), BG), im, max(0.0, fa))
            im.save(FR / f'{k:05d}.png'); k += 1
    total = sum(durs)
    cmd = ['ffmpeg', '-y', '-v', 'error', '-framerate', str(FPS), '-i', str(FR / '%05d.png')]
    if have:
        lst = HERE / 'aud.txt'
        parts = []
        for i, dd in enumerate(durs, 1):
            pad = HERE / f'pad{i}.wav'
            subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', str(AUD / f'{i:02d}.mp3'), '-af', f'atempo={TEMPO},apad=whole_dur={dd:.3f}', '-ar', '44100', '-ac', '2', str(pad)], check=True)
            parts.append(f"file '{pad}'")
        lst.write_text('\n'.join(parts) + '\n')
        cmd += ['-f', 'concat', '-safe', '0', '-i', str(lst), '-c:a', 'aac', '-b:a', '160k', '-shortest']
    out = HERE / ('모두의리서치_20초_v1.mp4' if have else 'preview_무음.mp4')
    cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', str(out)]
    subprocess.run(cmd, check=True)
    print(f'{out.name} · {total:.1f}초 · 장면 {[round(x, 2) for x in durs]} · 음성 {"있음" if have else "없음(미리보기)"}')


if __name__ == '__main__':
    main()
