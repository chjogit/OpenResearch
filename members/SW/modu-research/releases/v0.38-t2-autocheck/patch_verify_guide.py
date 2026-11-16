"""v0.38 곁가지(PM 요청): 「확인서로 다시 계산해 보기」 화면을 처음 온 사람도 바로 쓰게 — 언제 쓰나 · 3단계 안내 · 끌어다 놓기 칸 · 「방금 본 답으로 바로 해 보기」 · 결과를 쉬운 말로.
API·계산은 바꾸지 않는다(화면만, 더하기만). 여러 번 돌려도 같은 결과."""
import sys
from pathlib import Path

N = Path(sys.argv[1])


def patch(rel, old, new, mark):
    p = N / rel; s = p.read_text(encoding='utf-8')
    if mark in s:
        print(f'{rel}: 이미 적용됨'); return
    if s.count(old) != 1:
        raise SystemExit(f'{rel}: 바꿀 자리를 정확히 하나 찾지 못함({s.count(old)})')
    p.write_text(s.replace(old, new), encoding='utf-8', newline='')
    print(f'{rel}: 적용')


patch('web/easy.html',
      '''    <input id="vFile" type="file" accept=".json,.html,application/json,text/html">
    <div id="vOut"></div>''',
      '''    <!-- v0.38 확인서 사용법(vGuide) -->
    <div class="vguide" id="vGuide">
      <div class="vwhen"><b>이럴 때 써요</b>
        <ul><li>누가 보내 준 답이 <b>정말 그 근거에서 나온 건지</b> 확인하고 싶을 때</li>
          <li>예전에 본 답이 <b>지금 다시 계산해도 똑같이</b> 나오는지 보고 싶을 때</li>
          <li>팀원·친구와 <b>같은 결과를 보고 있는지</b> 맞춰 보고 싶을 때</li></ul></div>
      <ol class="vsteps">
        <li><b>확인서 파일 받기</b><span>답 화면 아래 「근거 확인서 내려받기」(.json) 또는 「공유용 페이지」(.html). 남이 보낸 파일도 돼요.</span></li>
        <li><b>아래 칸에 넣기</b><span>파일을 끌어다 놓거나, 칸을 눌러 골라요.</span></li>
        <li><b>결과 읽기</b><span>단계마다 「같음」이면 같은 근거로 같은 결과가 다시 나온 거예요.</span></li>
      </ol>
      <label class="vdrop" id="vDrop"><input id="vFile" type="file" accept=".json,.html,application/json,text/html">
        <b>여기에 파일을 끌어다 놓거나 눌러서 고르기</b><span>근거 확인서(.json) 또는 공유용 페이지(.html)</span></label>
      <p class="vtry" id="vTry"></p>
    </div>
    <div id="vOut"></div>''',
      'id="vGuide"')

JS = r'''
/* v0.38 확인서 사용법(vGuide): 연습 버튼 · 끌어다 놓기 · 결과를 쉬운 말로. 계산·API는 그대로. */
function vTryDraw(){
  const box = $('#vTry'); if (!box) return;
  box.innerHTML = E.rid
    ? `<button id="vTryBtn" class="ghost">방금 본 답으로 바로 해 보기</button> <span class="hint">파일 없이 지금 열려 있던 답(${esc(E.ans && E.ans.name || '')})의 확인서로 연습해요.</span>`
    : '<span class="hint">처음이라면: 질문 하나를 해서 답을 본 뒤 여기로 오면, 파일 없이 「방금 본 답으로 바로 해 보기」로 연습할 수 있어요.</span>';
  const b = $('#vTryBtn');
  if (b) b.onclick = async () => {
    b.disabled = true;
    try { const rc = await api('/api/easy/receipt/' + E.rid);
      await verifyFile(new File([JSON.stringify(rc)], 'receipt.json', {type: 'application/json'})); }
    catch(e){ toast(e.message); }
    b.disabled = false;
  };
}
(function(){
  const d = $('#vDrop'); if (!d) return;
  ['dragenter', 'dragover'].forEach(k => d.addEventListener(k, e => { e.preventDefault(); d.classList.add('on'); }));
  ['dragleave', 'drop'].forEach(k => d.addEventListener(k, e => { e.preventDefault(); d.classList.remove('on'); }));
  d.addEventListener('drop', e => { const f = e.dataTransfer && e.dataTransfer.files[0]; if (f) verifyFile(f); });
})();
const _v38_show = show;
show = function(id){ const r = _v38_show(id); if (id === 'verify') vTryDraw(); return r; };
const _v38_verifyFile = verifyFile;
verifyFile = async function(f){
  const r = await _v38_verifyFile(f);
  const h = $('#vOut h3');
  if (h){
    const ok = h.classList.contains('ok');
    h.insertAdjacentHTML('afterend', ok
      ? '<p class="vsay ok">쉽게 말하면: 이 답은 적힌 근거 그대로 다시 계산해도 <b>똑같이</b> 나와요. 결과가 옳다거나 투자해도 된다는 뜻은 아니에요.</p>'
      : $('#vOut table') ? '<p class="vsay ng">쉽게 말하면: 아래 「다름」 단계가 있어요. 그 뒤 자료가 고쳐졌거나(정정 공시 등) 근거 자료가 바뀌었을 수 있어요. 다른 단계의 이름을 보고 원문을 확인해 보세요.</p>'
      : '<p class="vsay ng">쉽게 말하면: 확인서 파일 자체가 처음 만들어진 것과 달라요(누군가 고쳤거나 일부가 잘린 파일). 보낸 사람에게 원본 파일을 다시 받아 넣어 보세요.</p>');
    const th = $('#vOut table th:nth-child(2)'); if (th) th.title = '지문: 그 단계의 자료와 계산을 짧은 문자열로 요약한 것. 한 글자만 달라도 바뀌어요.';
    const th3 = $('#vOut table th:nth-child(3)'); if (th3) th3.title = th.title;
  }
  return r;
};
'''
patch('web/easy.js', "const _v32_openAbout = openAbout;", JS + "const _v32_openAbout = openAbout;", '_v38_verifyFile')

patch('web/easy.css', "/* v0.38 T2-2 새로 나온 공시 */",
      "/* v0.38 확인서 사용법 */\n"
      ".vguide{margin:10px 0 14px}\n"
      ".vwhen{background:#faf8f4;border:1px solid var(--line);border-radius:10px;padding:10px 14px}.vwhen ul{margin:6px 0 0;padding-left:20px}\n"
      ".vsteps{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;padding:0;margin:12px 0;list-style:none;counter-reset:vs}\n"
      ".vsteps li{border:1px solid var(--line);border-radius:10px;padding:10px 12px;counter-increment:vs}\n"
      ".vsteps li b::before{content:counter(vs);display:inline-block;width:22px;height:22px;line-height:22px;text-align:center;border-radius:50%;background:#2d2a26;color:#fff;font-size:12px;margin-right:6px}\n"
      ".vsteps li span{display:block;font-size:13.5px;color:var(--mute);margin-top:4px}\n"
      ".vdrop{display:block;border:2px dashed var(--line);border-radius:12px;padding:22px;text-align:center;cursor:pointer;background:#fff}\n"
      ".vdrop.on{border-color:#c0602f;background:#fdf3ec}.vdrop input{display:block;margin:0 auto 8px}.vdrop span{display:block;font-size:13px;color:var(--mute);margin-top:4px}\n"
      ".vsay{margin:4px 0 10px}\n"
      "@media (max-width:640px){.vsteps{grid-template-columns:1fr}}\n"
      "/* v0.38 T2-2 새로 나온 공시 */",
      'v0.38 확인서 사용법')
