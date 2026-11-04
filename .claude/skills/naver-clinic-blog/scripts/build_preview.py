import html, json, re, sys, glob, os
"""네이버 블로그 원고 미리보기·복사 페이지 빌더.

사용법: python3 build_preview.py <프로젝트 폴더>
프로젝트 폴더 구성:
  config.json   병원명·헤더·원고별 카테고리/짧은 이름·게시 완료 번호
  prompts.json  이미지 프롬프트 (캡션 → 프롬프트)
  naver/*.txt   네이버 붙여넣기용 원고 (파일명 순서 = 원고 번호)
출력: <프로젝트>/preview.html, <프로젝트>/image_prompts.txt
"""
ROOT = sys.argv[1]
CFG = json.load(open(os.path.join(ROOT, 'config.json'), encoding='utf-8'))
PJ = json.load(open(os.path.join(ROOT, 'prompts.json'), encoding='utf-8'))
P = PJ['images']; NEG = PJ['negative']
def full_en(p):
    r = p['ratio'].split()[0]
    shape = 'vertical' if r in ('4:5', '3:4', '2:3', '9:16') else 'square' if r == '1:1' else 'horizontal'
    return f'{p["en"]}, {PJ["style_photo"] if p["kind"] == "photo" else PJ["style_illu"]}, {shape} {r} aspect ratio'
out = os.path.join(ROOT, 'preview.html')
files = sorted(glob.glob(os.path.join(ROOT, 'naver', '*.txt')))
CATS = [p['category'] for p in CFG['posts']]
SHORT = [p['short'] for p in CFG['posts']]
BAR = re.compile(r'^━+$')
e = html.escape

def render(text):
    lines = text.split('\n')
    i = 0; titles = []
    while i < len(lines) and not BAR.match(lines[i]):
        m = re.match(r'^\d\)\s*(.+)', lines[i])
        if m: titles.append(m.group(1))
        i += 1
    out = []; para = []; lst = None; mode = 'body'; tags = []
    def flush():
        nonlocal para, lst
        if para:
            cls = 'fine' if mode == 'disc' else 'p'
            out.append(f'<p class="{cls}">' + '<br>'.join(para) + '</p>'); para = []
        if lst:
            kind, items = lst
            out.append(f'<ul class="{kind}">' + ''.join(f'<li>{x}</li>' for x in items) + '</ul>'); lst = None
    def additem(kind, s):
        nonlocal lst
        if para: flush()
        if not lst or lst[0] != kind:
            flush(); lst = (kind, [])
        lst[1].append(s)
    first_bar = True
    while i < len(lines):
        L = lines[i].rstrip(); s = L.strip()
        if BAR.match(s):
            nxt = lines[i+1].strip() if i+1 < len(lines) else ''
            nn = lines[i+2].strip() if i+2 < len(lines) else ''
            if nxt and BAR.match(nn):
                flush()
                if nxt.startswith('■'):
                    out.append(f'<h2>{e(nxt[1:].strip())}</h2>')
                else:
                    mode = 'info'; out.append(f'<div class="info"><div class="info-name">{e(nxt)}</div><dl>')
                i += 3; continue
            flush()
            if not first_bar and mode == 'body': out.append('<hr class="div">')
            first_bar = False; i += 1; continue
        if mode == 'info' and s.startswith('['):
            out.append('</dl></div>'); mode = 'disc'
        if not s:
            if lst and i+1 < len(lines) and lines[i+1].startswith(' '): pass
            else: flush()
            i += 1; continue
        m = re.match(r'^\[(.+?)\s*-\s*(.+)\]$', s)
        if s.startswith('[이미지'):
            flush(); cap = m.group(2) if m else s; pr = P.get(cap)
            r = pr['ratio'].split()[0] if pr else '16:9'; ar = r.replace(':', '/')
            thumb = cap.startswith('대표 썸네일'); sq = ' sq' if thumb or r != '16:9' else ''
            fig = f'<figure class="ph note{sq}"><div class="ph-box" style="aspect-ratio:{ar}"><span class="ph-tag">{"대표 썸네일" if thumb else "이미지 자리"}</span><span>{e(cap)}</span></div>'
            if pr:
                IMGS.append((cap, pr))
                kind = '실사 사진' if pr['kind'] == 'photo' else '일러스트'
                txt = f'<div class="pr-row"><span class="pr-k">글자 넣기</span><span>{e(pr["text"])}<small>AI로 글자를 만들지 말고 캔바·미리캔버스에서 올리세요</small></span></div>' if pr['text'] else ''
                fig += (f'<details class="prompt"><summary>AI 이미지 프롬프트 · {kind} · {pr["ratio"]}</summary>'
                        f'<div class="pr-row"><span class="pr-k">용도</span><span>{e(pr["use"])}</span></div>'
                        f'<div class="pr-block"><div class="pr-head"><span class="pr-k">영문 프롬프트</span><button type="button" class="btn sm" data-copy>복사</button></div><pre>{e(full_en(pr))}</pre></div>'
                        f'<div class="pr-block"><div class="pr-head"><span class="pr-k">한글 프롬프트</span><button type="button" class="btn sm" data-copy>복사</button></div><pre>{e(pr["ko"])}</pre></div>'
                        f'<div class="pr-block"><div class="pr-head"><span class="pr-k">제외할 요소</span><button type="button" class="btn sm" data-copy>복사</button></div><pre>{e(NEG)}</pre></div>'
                        f'{txt}</details>')
            out.append(fig + '</figure>'); i += 1; continue
        if s.startswith('[지도'):
            flush(); out.append(f'<figure class="ph map note"><div class="ph-box"><span class="ph-tag">네이버 지도</span><span>{e(CFG["map_query"])}</span></div></figure>'); i += 1; continue
        if s.startswith('[확인 필요'):
            flush(); out.append(f'<p class="memo note">확인 필요 · {e(s[1:-1].split(":",1)[-1].strip())}</p>'); i += 1; continue
        if s.startswith('[태그'):
            flush(); tags = lines[i+1].split(); i += 2; continue
        if mode == 'info':
            if ':' in s:
                k, v = s.split(':', 1); out.append(f'<dt>{e(k.strip())}</dt><dd>{e(v.strip())}</dd>')
            elif s.startswith('※'):
                out.append(f'<dd class="wide">{e(s)}</dd>')
            else:
                out.append(f'<dt></dt><dd>{e(s)}</dd>')
            i += 1; continue
        if s.startswith('☐'): additem('check', e(s[1:].strip())); i += 1; continue
        if s.startswith('·'): additem('dots', e(s[1:].strip())); i += 1; continue
        if L.startswith(' ') and lst: lst[1][-1] += ' ' + e(s); i += 1; continue
        if s.startswith('→'):
            if lst: lst[1][-1] += f'<span class="arrow">{e(s[1:].strip())}</span>'
            else: para.append(f'<span class="arrow">{e(s[1:].strip())}</span>')
            i += 1; continue
        mm = re.match(r'^(STEP \d\.|Q\d\.|[①②③④⑤]|\d\.)\s*(.+)$', s)
        if mm:
            flush()
            k = mm.group(1); rest = mm.group(2)
            if k.startswith('Q'):
                out.append(f'<p class="q"><b>{e(k)}</b> {e(rest)}</p>')
            elif ' – ' in rest:
                a, b = rest.split(' – ', 1)
                out.append(f'<h3><span class="k">{e(k)}</span>{e(a)}</h3><p class="p">{e(b)}</p>')
            else:
                out.append(f'<h3><span class="k">{e(k)}</span>{e(rest)}</h3>')
            i += 1; continue
        para.append(e(s)); i += 1
    flush()
    if mode == 'info': out.append('</dl></div>')
    return titles, '\n'.join(out), tags


def segments(raw):
    body = raw[raw.index('━'):].split('[태그')[0]
    body = body.split('\n', 1)[1]
    segs = []; buf = []; memos = []
    def push():
        nonlocal buf, memos
        t = re.sub(r'\n{3,}', '\n\n', '\n'.join(buf)).strip('\n')
        if t.strip(): segs.append(dict(type='text', text=t + '\n', memos=memos))
        buf = []; memos = []
    for L in body.split('\n'):
        s = L.strip()
        m = re.match(r'^\[(.+?)\s*-\s*(.+)\]$', s)
        if s.startswith('[이미지'):
            push(); cap = m.group(2); segs.append(dict(type='img', cap=cap, pr=P.get(cap)))
        elif s.startswith('[지도'):
            push(); segs.append(dict(type='map'))
        elif s.startswith('[확인 필요'):
            memos.append(s[1:-1].split(':', 1)[-1].strip())
        else:
            buf.append(L.rstrip())
    push()
    return segs

def copyrow(label, text, big=False):
    cls = 'pre big' if big else 'pre'
    return (f'<div class="pr-block"><div class="pr-head"><span class="pr-k">{e(label)}</span>'
            f'<button type="button" class="btn sm" data-copy>복사</button></div><pre class="{cls}">{e(text)}</pre></div>')

def paste_html(n, titles, raw, tags):
    segs = segments(raw); parts_on = []; parts_off = []; prompts = []; memos = []; k = 0
    for sg in segs:
        if sg['type'] == 'text':
            parts_on.append(sg['text']); parts_off.append(sg['text']); memos += sg['memos']
        elif sg['type'] == 'img':
            k += 1; pr = sg['pr']
            parts_on.append(f'[사진 {k} 넣는 곳 - 넣은 뒤 이 줄 삭제]\n')
            kind = '실사 사진' if pr['kind'] == 'photo' else '일러스트'
            blk = [f'■ 사진 {k}. {sg["cap"]}', f'용도 : {pr["use"]} / {kind} / 비율 {pr["ratio"]}', '',
                   '[영문 프롬프트]', full_en(pr), '', '[한글 프롬프트]', pr['ko'], '', '[제외할 요소]', NEG]
            if pr['text']: blk += ['', '[글자 넣기 - 캔바·미리캔버스에서]', pr['text']]
            prompts.append('\n'.join(blk))
        else:
            parts_on.append('[네이버 지도 넣는 곳 - 장소 버튼으로 추가한 뒤 이 줄 삭제]\n')
    join = lambda ps: re.sub(r'\n{3,}', '\n\n', '\n'.join(ps)).strip() + '\n'
    on, off = join(parts_on), join(parts_off)
    ptxt = ('\n\n' + '─' * 20 + '\n\n').join(prompts) + '\n'
    memo = ''.join(f'<p class="memo">게시 전 확인 · {e(x)}</p>' for x in memos)
    return (f'<section class="paste" id="paste{n}" hidden>'
      f'<div class="card"><div class="card-h"><h3>글</h3><span class="meta">사진 {k}장 자리</span></div>'
      f'<div class="mini">{copyrow("제목", titles[0])}{copyrow("태그", " ".join(tags))}</div>'
      f'{memo}'
      f'<div class="pr-block whole"><div class="pr-head"><span class="pr-k">본문 전체</span>'
      f'<span class="opts"><label><input type="checkbox" class="opt-mark" id="mark{n}" checked> 사진 위치 표시</label>'
      f'<button type="button" class="btn" data-copy>본문 전체 복사</button></span></div>'
      f'<pre class="pre big on">{e(on)}</pre><pre class="pre big off" hidden>{e(off)}</pre></div></div>'
      f'<div class="card"><div class="card-h"><h3>이미지 프롬프트</h3><span class="meta">{k}개</span></div>'
      f'<div class="pr-block whole"><div class="pr-head"><span class="pr-k">사진 1~{k} 프롬프트 전체</span>'
      f'<button type="button" class="btn" data-copy>프롬프트 전체 복사</button></div>'
      f'<pre class="pre big">{e(ptxt)}</pre></div></div></section>')

posts = []; ALL = []
for n, f in enumerate(files):
    IMGS = []
    raw = open(f, encoding='utf-8').read()
    titles, body, tags = render(raw)
    ALL.append((titles[0], list(IMGS)))
    paste = paste_html(n, titles, raw, tags)
    # copy text: body only (strip title candidates & tag section)
    copy = raw.split('━', 1)[1]; copy = '━' + copy
    copy = copy.split('[태그')[0].rstrip() + '\n'
    posts.append(dict(n=n, titles=titles, body=body, tags=tags, cat=CATS[n], short=SHORT[n], copy=copy, tagline=' '.join(tags), paste=paste))

DONE = {n - 1 for n in CFG.get('done', [])}
tpl = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'template.html'), encoding='utf-8').read()
tpl = tpl.replace('%%PAGE_TITLE%%', e(CFG['page_title'])).replace('%%HEADER_TITLE%%', e(CFG['header_title']))
tabs = ''.join(f'<button class="tab{" done" if p["n"] in DONE else ""}" role="tab" id="tab{p["n"]}" aria-controls="post{p["n"]}" data-i="{p["n"]}"><span class="tn">{"✓" if p["n"] in DONE else p["n"]+1}</span>{e(p["short"])}{"<span class=\"dl\">완료</span>" if p["n"] in DONE else ""}</button>' for p in posts)
status = f'<div class="status"><span class="bar"><span style="width:{len(DONE)*100//len(posts)}%"></span></span><span><b>{len(DONE)}/{len(posts)}</b> 게시 완료</span></div>'
BANNER = '<div class="donebar"><span class="ck">✓</span>네이버 블로그 게시 완료</div>'
arts = ''
for p in posts:
    alts = ''.join(f'<li>{e(t)}</li>' for t in p['titles'][1:])
    chips = ''.join(f'<span class="chip">{e(t)}</span>' for t in p['tags'])
    ban = BANNER if p['n'] in DONE else ''
    arts += f'''<article class="post" id="post{p["n"]}" role="tabpanel" aria-labelledby="tab{p["n"]}" hidden>
{ban}<header class="post-head"><div class="cat">{e(p["cat"])}</div><h1>{e(p["titles"][0])}</h1>
<div class="byline"><span class="avatar" aria-hidden="true">{e(CFG["avatar"])}</span><span><b>{e(CFG["byline"])}</b><small>{e(CFG["byline_sub"])}</small></span></div></header>
<div class="post-body">{p["body"]}</div>
<footer class="post-foot"><div class="chips">{chips}</div>
<details class="alt note"><summary>다른 제목 후보 {len(p["titles"])-1}개</summary><ul>{alts}</ul></details></footer>
</article>{p["paste"].replace('<section class="paste" id="paste' + str(p['n']) + '" hidden>', '<section class="paste" id="paste' + str(p['n']) + '" hidden>' + ban, 1)}'''
data = json.dumps([dict(copy=p['copy'], title=p['titles'][0], tags=p['tagline']) for p in posts], ensure_ascii=False).replace('</', '<\\/')
open(out, 'w', encoding='utf-8').write(tpl.replace('%%STATUS%%', status).replace('%%TABS%%', tabs).replace('%%POSTS%%', arts).replace('%%DATA%%', data))
print('ok', len(posts))

lines = [f"{CFG['clinic_name']} 블로그 · AI 이미지 프롬프트", "",
 "[사용법]",
 "· 영문 프롬프트가 미드저니, 챗GPT(DALL·E), 제미나이 등 대부분의 도구에서 결과가 안정적입니다. 한글만 되는 도구는 한글 프롬프트를 쓰세요.",
 "· '제외할 요소'는 네거티브 프롬프트 칸에 넣습니다. 칸이 없는 도구는 영문 프롬프트 끝에 'Avoid: ...' 형태로 붙이세요.",
 "· 미드저니는 끝에 --ar (각 이미지의 비율, 예: 4:5) --style raw 를 붙이면 블로그 사진 칸 비율과 맞고 덜 인위적으로 나옵니다.",
 "· 한글 글자는 AI가 자주 틀립니다. 글자는 비워 두고 캔바·미리캔버스에서 올리세요.",
 "· 같은 원고의 이미지는 같은 날 같은 도구로 만들면 색감이 통일됩니다.",
 "", "[어색하지 않게 만드는 점검]",
 "· 손가락 개수와 손 모양, 눈·치아, 거울 속 반사가 맞는지 확인",
 "· 피부가 매끈한 플라스틱처럼 보이면 다시 생성 (모공·결이 보이는 쪽이 자연스럽습니다)",
 "· 제품에 상표·글자가 생기면 지우거나 다시 생성", "",
 "[의료광고 주의]",
 "· 시술 전후 비교처럼 보이는 이미지, 실제 환자처럼 보이는 피부 병변 클로즈업은 쓰지 않습니다.",
 "· 실제 의료진이나 병원 내부처럼 보이는 AI 이미지는 만들지 않습니다. 병원 사진이 필요하면 실제 사진을 쓰세요.",
 "· 바늘·시술 장면, 효과를 과장하는 이미지는 넣지 않습니다.", ""]
for title, imgs in ALL:
    lines += ["━━━━━━━━━━━━━━━━━━━━━━", title, "━━━━━━━━━━━━━━━━━━━━━━", ""]
    for k, (cap, pr) in enumerate(imgs, 1):
        lines += [f"■ 이미지 {k}. {cap}", f"용도 : {pr['use']}  /  {'실사 사진' if pr['kind']=='photo' else '일러스트'}  /  비율 {pr['ratio']}", "",
                  "[영문 프롬프트]", full_en(pr), "", "[한글 프롬프트]", pr['ko'], "", "[제외할 요소]", NEG, ""]
        if pr['text']: lines += ["[글자 넣기 - 캔바·미리캔버스에서]", pr['text'], ""]
open(os.path.join(os.path.dirname(out), 'image_prompts.txt'), 'w', encoding='utf-8').write('\n'.join(lines))
print('prompts', sum(len(x[1]) for x in ALL))
