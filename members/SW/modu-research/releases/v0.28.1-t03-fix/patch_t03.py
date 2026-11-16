import sys
p=sys.argv[1]; s=open(p,encoding='utf-8').read()
if 't03ill' in s: print('already'); sys.exit()
a="""  } else if (i.code === 'cutoff_default'){"""
b="""  } else if (i.code === 'assumption_invalid' && n && n.type === 'T03'){
    const empty = !Object.keys(n.config.model || {}).length;
    msg = empty ? '가치평가(N02)에 쓸 가정이 비어 있어요. 이 앱은 가정을 대신 지어내지 않아요.' : `가치평가 가정에 고칠 곳이 있어요: ${i.message.replace('가정 입력 오류: ', '')}`;
    fix = '체험만 하려면 「학습용 예시」로 채우세요(결과에 「실제 추정 아님」 표시). 직접 넣으려면 설정을 열고, 가치평가가 필요 없으면 빼도 돼요.';
    acts.push(['t03ill', n.id, '학습용 예시로 채우기'], ['t03open', n.id, '설정 열기'], ['t03del', n.id, '가치평가(T03·N02) 빼기']);
"""+a
assert s.count(a)==1; s=s.replace(a,b)
a2="""    if (a === 'edge'){"""
b2="""    if (a === 't03ill'){ const n = nodeById(arg), t = TEMPLATES[n.config.method || 'dcf'] || TEMPLATES.dcf;
      Object.assign(n.config, {model: JSON.parse(JSON.stringify(t.ill)), input_kind:'illustrative_assumptions', label: '학습용 ' + (n.config.method||'dcf').toUpperCase(),
        shares: '5900000000', share_basis: '학습용 예시 주식 수 (실제 희석주식수 아님)', assumptions_note: '계산 흐름 체험용 임의 가정. 실제 기업가치 추정이 아님'});
      touch(); renderAll(); toast('학습용 예시를 채웠어요. 가치평가 결과에는 「실제 추정 아님」이 붙어요.'); }
    if (a === 't03open'){ S.sel = arg; S.selEdge = null; S.tab = 'config'; renderAll(); }
    if (a === 't03del'){ const drop = new Set([arg, ...S.doc.edges.filter(e => e.from_node === arg && e.to_port === 'assumptions').map(e => e.to_node).filter(id => (nodeById(id) || {}).type === 'N02')]);
      S.doc.nodes = S.doc.nodes.filter(x => !drop.has(x.id)); S.doc.edges = S.doc.edges.filter(e => !drop.has(e.from_node) && !drop.has(e.to_node)); if (drop.has(S.sel)) S.sel = null;
      touch(); renderAll(); toast(`가치평가 노드 ${drop.size}개를 뺐어요. 나머지 분석은 그대로 실행돼요.`); }
"""+a2
assert s.count(a2)==1; s=s.replace(a2,b2)
open(p,'w',encoding='utf-8').write(s); print('patched')
