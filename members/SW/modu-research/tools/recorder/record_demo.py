"""모두의리서치 화면 자동 녹화 (PM 2026-11-16, 설명 영상용). 실제 앱(127.0.0.1:8765)을 자동으로 조작하며 녹화한다.
- 보이는 화살표 커서가 부드럽게 움직이고, 클릭할 때 동그란 파동이 퍼진다(페이지에 그림만 덧입힘, 앱은 바꾸지 않음).
- 브라우저는 보이지 않는 창(headless)으로 열려 PC 화면을 가리지 않는다. 결과: out\\demo_날짜.webm + steps.json(장면 시각)
- 키·계정 화면은 열지 않는다. AI 초안은 쓰지 않고 규칙 초안(AI 호출 0회)만 보여 준다.
쓰는 법: (녹화용 가상환경 python) record_demo.py [--show]   --show: 브라우저 창을 보이게"""
import json, sys, time
from datetime import datetime
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:8765'
VW, VH = 1440, 810
CURSOR = r"""
(() => {
  if (window.__mrCursor) return; window.__mrCursor = 1;
  const mk = () => {
    const c = document.createElement('div');
    c.id = '__mr_cursor';
    c.innerHTML = '<svg width="34" height="40" viewBox="0 0 34 40"><path d="M3 2 L3 32 L11 25 L17 38 L23 35 L17 22 L28 22 Z" fill="#1E1B26" stroke="#fff" stroke-width="2.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'0', top:'0', zIndex:2147483647, pointerEvents:'none', transform:'translate(-3px,-2px)', filter:'drop-shadow(0 2px 3px rgba(0,0,0,.35))'});
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      const r = document.createElement('div');
      Object.assign(r.style, {position:'fixed', left:(e.clientX-6)+'px', top:(e.clientY-6)+'px', width:'12px', height:'12px', borderRadius:'50%',
        border:'3px solid #9B2C5E', zIndex:2147483646, pointerEvents:'none', transition:'all .55s ease-out', opacity:'0.9'});
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => Object.assign(r.style, {left:(e.clientX-34)+'px', top:(e.clientY-34)+'px', width:'68px', height:'68px', opacity:'0'}));
      setTimeout(() => r.remove(), 700);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mk); else mk();
})();
"""
STEPS, T0 = [], [0.0]
POS = [VW / 2, VH / 2]


def mark(name):
    STEPS.append({'step': name, 't': round(time.time() - T0[0], 2)}); print(f'{STEPS[-1]["t"]:6.1f}s  {name}', flush=True)


def glide(page, x, y, ms=700):
    n = max(8, int(ms / 16)); sx, sy = POS
    for i in range(1, n + 1):
        k = i / n; e = 1 - (1 - k) ** 3
        page.mouse.move(sx + (x - sx) * e, sy + (y - sy) * e); page.wait_for_timeout(16)
    POS[:] = [x, y]


def click(page, loc, pause=350, ms=700):
    loc.scroll_into_view_if_needed(); page.wait_for_timeout(200)
    b = loc.bounding_box()
    glide(page, b['x'] + b['width'] / 2, b['y'] + b['height'] / 2, ms)
    page.wait_for_timeout(pause); page.mouse.down(); page.wait_for_timeout(90); page.mouse.up()


def scroll(page, dy, steps=30):
    for _ in range(steps):
        page.mouse.wheel(0, dy / steps); page.wait_for_timeout(22)


def main():
    show = '--show' in sys.argv
    out = HERE / 'out'; out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        try:
            br = p.chromium.launch(channel='msedge', headless=not show)
        except Exception:
            br = p.chromium.launch(headless=not show)
        ctx = br.new_context(viewport={'width': VW, 'height': VH}, device_scale_factor=1, locale='ko-KR',
                             record_video_dir=str(out), record_video_size={'width': VW, 'height': VH})
        ctx.add_init_script(CURSOR)
        page = ctx.new_page()
        T0[0] = time.time()
        page.goto(BASE + '/research/'); page.wait_for_load_state('networkidle'); page.mouse.move(*POS)
        mark('근거 리서치 첫 화면'); page.wait_for_timeout(1800)
        click(page, page.locator('#co-q')); page.keyboard.type('삼성', delay=160); page.wait_for_timeout(700)
        mark('회사 고르기'); click(page, page.locator('#co-list button[data-t="005930"]')); page.wait_for_timeout(900)
        mark('주제 카드: 주가 흐름·매매 주체'); click(page, page.locator('#view button[data-card="price"]'), pause=500)
        page.wait_for_selector('#draft-go', timeout=60000); page.wait_for_timeout(1500)
        mark('답 카드'); scroll(page, 380); page.wait_for_timeout(1800)
        mark('근거 서랍'); click(page, page.locator('#view button:has-text("근거 ›")').first); page.wait_for_timeout(3200)
        click(page, page.locator('button[aria-label="근거 서랍 닫기"]')); page.wait_for_timeout(700)
        mark('보고서 초안(규칙, AI 0회)'); click(page, page.locator('#draft-go'), pause=500)
        page.wait_for_function("() => (document.querySelector('#draft-out')||{}).innerText && !document.querySelector('#draft-out').innerText.includes('만드는 중')", timeout=60000)
        page.wait_for_timeout(500); page.locator('#draft-out').scroll_into_view_if_needed(); page.wait_for_timeout(3000)
        mark('여러 회사 한꺼번에'); click(page, page.locator('a[href="#/batch"]').first); page.wait_for_timeout(2600)
        mark('관심회사 공시함'); click(page, page.locator('a[href="#/watch"]').first); page.wait_for_timeout(2600)
        mark('끝'); page.wait_for_timeout(600)
        vid = page.video.path() if page.video else None
        ctx.close(); br.close()
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = out / f'demo_{stamp}.webm'
    if vid and Path(vid).exists():
        Path(vid).rename(dst)
    (out / f'demo_{stamp}.steps.json').write_text(json.dumps(STEPS, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'녹화 완료: {dst}  ({STEPS[-1]["t"]:.0f}초, 장면 {len(STEPS)}개)')


if __name__ == '__main__':
    main()
