"""릴스 분석기 웹 화면. 브라우저에서 계정이나 릴스 링크를 넣고 [수집하기]를 누르면
fetch_reels.py → transcribe_whisper.py → prepare_dissect.py 를 차례로 돌리고 결과를 보여준다.

사용법:
    python3 web_app.py [--port 8765]
    → 브라우저에서 http://127.0.0.1:8765 열기

필요한 것:
    APIFY_TOKEN  환경변수, 또는 플러그인 폴더(02-인스타분석/)의 .env 파일에 APIFY_TOKEN=... 한 줄
                 (.env 는 .gitignore 에 들어 있어 저장소에 올라가지 않는다)
    위스퍼        pip install -r requirements.txt (위스퍼 없이 수집만 할 때는 필요 없음)

추가 설치 없이 파이썬 기본 기능만으로 돈다. 내 컴퓨터(127.0.0.1)에서만 열린다.
해부(왜 잘됐는지 판정)는 Claude가 templates/해부기준.md 대로 한다. 화면의 [해부 요청 문구 복사]를
눌러 Claude에게 붙여넣으면 되고, 해부_결과.json 이 생기면 화면에 해부표와 비교표가 나온다.
"""
import json
import os
import re
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from fetch_reels import default_out_dir
from prepare_dissect import split_groups, views

SCRIPTS = Path(__file__).resolve().parent
PLUGIN = SCRIPTS.parent
MODELS = ("tiny", "base", "small", "medium", "large-v3")
JOBS = {}
JOBS_LOCK = threading.Lock()


def load_dotenv():
    env = PLUGIN / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def results_root():
    # default_out_dir(계정) = <고객설정>/인스타분석/<계정>/<날짜>
    return default_out_dir("_").parent.parent


def list_results():
    root = results_root()
    items = []
    if not root.exists():
        return items
    for raw in root.glob("*/*/reels_raw.json"):
        folder = raw.parent
        items.append({
            "account": folder.parent.name,
            "stamp": folder.name,
            "whisper": (folder / "transcripts_whisper.json").exists(),
            "dissect": (folder / "해부_결과.json").exists(),
        })
    items.sort(key=lambda x: x["stamp"], reverse=True)
    return items


def result_folder(account, stamp):
    # 목록에 있는 폴더만 연다 (경로 조작 방지)
    for item in list_results():
        if item["account"] == account and item["stamp"] == stamp:
            return results_root() / account / stamp
    return None


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def result_detail(folder):
    reels = read_json(folder / "reels_raw.json") or []
    top, bottom = split_groups(reels, 10)
    group = {r["shortCode"]: "상위" for r in top}
    group.update({r["shortCode"]: "하위" for r in bottom})
    ranked = sorted(reels, key=views, reverse=True)
    rows = [{
        "rank": i,
        "code": r.get("shortCode"),
        "url": r.get("url"),
        "date": (r.get("timestamp") or "")[:10],
        "views": views(r),
        "likes": r.get("likesCount"),
        "comments": r.get("commentsCount"),
        "duration": r.get("videoDuration"),
        "caption": (r.get("caption") or "").strip().splitlines()[0] if r.get("caption") else "",
        "ad": bool(r.get("paidPartnership")) or "*광고" in (r.get("caption") or ""),
        "group": group.get(r.get("shortCode"), "중간"),
        "apify_transcript": r.get("transcript") if isinstance(r.get("transcript"), str) else "",
    } for i, r in enumerate(ranked, 1)]

    compare_md = None
    if (folder / "해부_결과.json").exists() and len(reels) > 10:
        subprocess.run([sys.executable, str(SCRIPTS / "compare_groups.py"), str(folder), "10"],
                       capture_output=True, cwd=SCRIPTS)
        path = folder / "상위하위_비교.md"
        compare_md = path.read_text(encoding="utf-8") if path.exists() else None
    return {
        "folder": str(folder),
        "reels": rows,
        "whisper": read_json(folder / "transcripts_whisper.json") or {},
        "dissect": read_json(folder / "해부_결과.json"),
        "compare_md": compare_md,
    }


def run_job(job_id, target, count, whisper, model):
    job = JOBS[job_id]

    def log(line):
        with JOBS_LOCK:
            job["log"].append(line.rstrip())

    def step(title, args):
        log(f"▶ {title}")
        proc = subprocess.Popen([sys.executable, "-u", *args], cwd=SCRIPTS, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        out = []
        for line in proc.stdout:
            if "HF Hub" in line or not line.strip():
                continue
            out.append(line)
            log("  " + line)
        return proc.wait(), "".join(out)

    try:
        code, out = step("1. 릴스 가져오기 (Apify)", ["fetch_reels.py", target, str(count), "--transcript"])
        found = re.search(r"저장 → (.+)", out)
        if code != 0 or not found:
            raise RuntimeError("릴스를 가져오지 못했습니다. 위 메시지를 확인하세요.")
        folder = Path(found.group(1).strip())
        job["result"] = {"account": folder.parent.name, "stamp": folder.name}

        if whisper:
            code, _ = step("2. 위스퍼 받아쓰기 (내 컴퓨터)", ["transcribe_whisper.py", str(folder), "--model", model])
            if code != 0:
                log("  위스퍼 단계가 실패했습니다. 수집 결과는 그대로 볼 수 있습니다.")
        else:
            log("▶ 2. 위스퍼 받아쓰기 — 건너뜀")

        step("3. 해부 자료 만들기", ["prepare_dissect.py", str(folder), "10"])
        job["status"] = "done"
        log("✔ 끝났습니다.")
    except Exception as exc:  # 화면에 이유를 보여주고 끝낸다
        log(f"✖ {exc}")
        job["status"] = "error"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self.send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
        if path == "/api/results":
            return self.send(200, list_results())
        m = re.fullmatch(r"/api/results/([^/]+)/([^/]+)", path)
        if m:
            folder = result_folder(*m.groups())
            return self.send(200, result_detail(folder)) if folder else self.send(404, {"error": "결과를 찾지 못했습니다."})
        m = re.fullmatch(r"/api/jobs/([0-9a-f]+)", path)
        if m and m.group(1) in JOBS:
            with JOBS_LOCK:
                return self.send(200, JOBS[m.group(1)])
        return self.send(404, {"error": "없는 주소입니다."})

    def do_POST(self):
        if urlparse(self.path).path != "/api/collect":
            return self.send(404, {"error": "없는 주소입니다."})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "요청 형식이 올바르지 않습니다."})
        target = str(body.get("target") or "").strip()
        count = int(body.get("count") or 30)
        model = body.get("model") if body.get("model") in MODELS else "small"
        if not target:
            return self.send(400, {"error": "계정 아이디나 릴스 링크를 넣어주세요."})
        if not os.environ.get("APIFY_TOKEN"):
            return self.send(400, {"error": "APIFY_TOKEN이 없습니다. 02-인스타분석/.env 파일에 APIFY_TOKEN=... 을 넣고 서버를 다시 켜세요."})
        if any(j["status"] == "running" for j in JOBS.values()):
            return self.send(409, {"error": "이미 수집 중입니다. 끝난 뒤 다시 눌러주세요."})
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "status": "running", "log": [], "result": None}
        threading.Thread(target=run_job, args=(job_id, target, max(1, min(count, 100)), bool(body.get("whisper")), model),
                         daemon=True).start()
        return self.send(200, {"job": job_id})


PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>릴스 분석기</title>
<style>
:root { --bg: #f6f6f3; --panel: #ffffff; --fg: #1d1f1c; --muted: #6b6f68; --line: #e2e3dd; --accent: #2f6b4f; --accent-soft: #e3efe8; --low: #a0522d; --low-soft: #f5e8df; --bad: #b3261e; }
@media (prefers-color-scheme: dark) { :root { --bg: #161815; --panel: #1f221e; --fg: #ecede8; --muted: #a3a79f; --line: #33372f; --accent: #7cc2a0; --accent-soft: #23362c; --low: #e0a07a; --low-soft: #3a2a20; --bad: #f2867e; color-scheme: dark; } }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 15px/1.6 "Pretendard", "Apple SD Gothic Neo", "Malgun Gothic", system-ui, sans-serif; }
.wrap { max-width: 72rem; margin: 0 auto; padding: 24px max(16px, env(safe-area-inset-left)) 64px; display: grid; gap: 20px; }
h1 { font-size: 1.6rem; margin: 0; letter-spacing: -.01em; }
h2 { font-size: 1.05rem; margin: 0; }
.sub { color: var(--muted); margin: 4px 0 0; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 18px; display: grid; gap: 12px; min-width: 0; }
form { display: grid; grid-template-columns: 1fr auto; gap: 10px; }
.opts { display: flex; flex-wrap: wrap; gap: 16px; align-items: center; color: var(--muted); font-size: .9rem; grid-column: 1 / -1; }
input[type=text], input[type=number], select { font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); color: var(--fg); min-width: 0; }
input[type=number] { width: 5.5rem; }
button { font: inherit; border: 0; border-radius: 8px; padding: 9px 18px; background: var(--accent); color: var(--panel); cursor: pointer; font-weight: 600; }
button.ghost { background: transparent; color: var(--fg); border: 1px solid var(--line); font-weight: 500; }
button:disabled { opacity: .5; cursor: default; }
button:focus-visible, input:focus-visible, select:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
pre.log { margin: 0; background: var(--bg); border-radius: 8px; padding: 12px; max-height: 18rem; overflow: auto; font: 12.5px/1.55 ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; }
.history { display: flex; flex-wrap: wrap; gap: 8px; }
.history button { font-size: .85rem; padding: 6px 12px; }
.history button[aria-pressed=true] { border-color: var(--accent); background: var(--accent-soft); }
.tag { display: inline-block; font-size: .75rem; padding: 0 7px; border-radius: 999px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
.tag.top { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.tag.low { background: var(--low-soft); color: var(--low); border-color: transparent; }
.tablewrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .88rem; font-variant-numeric: tabular-nums; }
th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
td { padding: 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
td.num, th.num { text-align: right; white-space: nowrap; }
tr.reel { cursor: pointer; }
tr.reel:hover td { background: var(--bg); }
tr.detail td { background: var(--bg); }
.lines { display: grid; gap: 2px; font-size: .86rem; }
.lines div { display: grid; grid-template-columns: 9.5rem 1fr; gap: 8px; }
.lines span.t { white-space: nowrap; }
td.date { white-space: nowrap; }
.lines span.t { color: var(--muted); font-variant-numeric: tabular-nums; }
a { color: var(--accent); }
.muted { color: var(--muted); }
.row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
.err { color: var(--bad); }
.md table { margin-top: 4px; }
@media (max-width: 560px) { form { grid-template-columns: 1fr; } .lines div { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>릴스 분석기</h1>
    <p class="sub">계정 아이디나 릴스 링크를 넣으면 릴스를 모으고, 위스퍼로 몇 초에 무슨 말을 했는지 받아쓴 뒤 상위·하위 릴스를 나눠 보여줍니다.</p>
  </header>

  <section class="card">
    <form id="f">
      <input type="text" id="target" placeholder="예: tttt.yeon_  또는  https://www.instagram.com/reel/..." autocomplete="off" required>
      <button type="submit" id="go">수집하기</button>
      <div class="opts">
        <label>개수 <input type="number" id="count" value="30" min="1" max="100"></label>
        <label><input type="checkbox" id="whisper" checked> 위스퍼 받아쓰기 (상위·하위 20개)</label>
        <label>모델 <select id="model"><option>tiny</option><option>base</option><option selected>small</option><option>medium</option><option>large-v3</option></select></label>
      </div>
    </form>
    <p class="err" id="formerr" hidden></p>
    <pre class="log" id="log" hidden></pre>
  </section>

  <section class="card">
    <h2>지난 결과</h2>
    <div class="history" id="history"><span class="muted">불러오는 중…</span></div>
  </section>

  <section id="result" hidden></section>
</div>

<script>
const $ = s => document.querySelector(s);
const fmt = n => n == null ? '' : Number(n).toLocaleString('ko-KR');
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k != null) e.append(k);
  return e;
};
let current = null;

async function loadHistory(select) {
  const items = await (await fetch('/api/results')).json();
  const box = $('#history'); box.replaceChildren();
  if (!items.length) { box.append(el('span', { class: 'muted', text: '아직 결과가 없습니다. 위에서 수집해 보세요.' })); return; }
  items.forEach(it => {
    const label = `@${it.account} · ${it.stamp.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})$/, '$2/$3 $4:$5')}` + (it.whisper ? ' · 위스퍼' : '') + (it.dissect ? ' · 해부' : '');
    const b = el('button', { class: 'ghost', type: 'button', 'aria-pressed': String(current === it.account + '/' + it.stamp), text: label });
    b.onclick = () => openResult(it.account, it.stamp);
    box.append(b);
  });
  if (select) openResult(select.account, select.stamp);
}

function transcriptLines(w, r) {
  const box = el('div', { class: 'lines' });
  if (w) {
    if (!w.segments.length) box.append(el('div', {}, el('span', { class: 't', text: '' }), el('span', { class: 'muted', text: '말 없음 (위스퍼가 말소리를 찾지 못함)' })));
    w.segments.forEach(s => {
      const pct = r.duration ? ` · ${Math.round(s.start / r.duration * 100)}%` : '';
      box.append(el('div', {}, el('span', { class: 't', text: `${s.start.toFixed(1)}~${s.end.toFixed(1)}초${pct}` }), el('span', { text: s.text })));
    });
  } else {
    box.append(el('div', {}, el('span', { class: 't', text: 'Apify' }), el('span', { text: r.apify_transcript || '(받아쓰기 없음)' })));
  }
  return box;
}

function mdTables(md) {
  const wrap = el('div', { class: 'md' });
  let table = null;
  md.split('\n').forEach(line => {
    if (/^\|/.test(line)) {
      const cells = line.split('|').slice(1, -1).map(c => c.trim());
      if (cells.every(c => /^-+$/.test(c))) return;
      if (!table) { table = el('table'); const tr = el('tr'); cells.forEach(c => tr.append(el('th', { text: c }))); table.append(tr); wrap.append(el('div', { class: 'tablewrap' }, table)); return; }
      const tr = el('tr'); cells.forEach((c, i) => tr.append(el('td', { class: i ? 'num' : '', text: c }))); table.append(tr);
    } else {
      table = null;
      if (/^## /.test(line)) wrap.append(el('h2', { text: line.slice(3), style: 'margin-top:12px' }));
    }
  });
  return wrap;
}

async function openResult(account, stamp) {
  current = account + '/' + stamp;
  document.querySelectorAll('#history button').forEach(b => b.setAttribute('aria-pressed', String(b.textContent.startsWith('@' + account) && b.textContent.includes(stamp.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})$/, '$2/$3 $4:$5')))));
  const res = await fetch(`/api/results/${encodeURIComponent(account)}/${encodeURIComponent(stamp)}`);
  const d = await res.json();
  const box = $('#result'); box.hidden = false; box.replaceChildren();
  const card = el('div', { class: 'card' });
  const nW = Object.keys(d.whisper).length;
  const prompt = `plugins/02-인스타분석 SKILL.md 4~5단계대로 ${d.folder} 의 해부_입력.md 를 templates/해부기준.md 기준으로 해부해서 해부_결과.json 을 만들고, 공통 패턴 3개와 상위/하위 비교까지 정리해줘.`;
  const copy = el('button', { class: 'ghost', type: 'button', text: '해부 요청 문구 복사' });
  copy.onclick = async () => { try { await navigator.clipboard.writeText(prompt); copy.textContent = '복사됨 — Claude에게 붙여넣으세요'; } catch { window.prompt('아래 문구를 복사하세요', prompt); } };
  card.append(
    el('div', { class: 'row' },
      el('div', {}, el('h2', { text: `@${account} 릴스 ${d.reels.length}개` }), el('p', { class: 'sub', text: `위스퍼 받아쓰기 ${nW}개 · ${d.dissect ? '해부 완료' : '해부 전'} · 저장 위치 ${d.folder}` })),
      copy),
  );
  if (!d.dissect) card.append(el('p', { class: 'muted', text: '해부(왜 잘됐는지 판정)는 Claude가 해부기준.md 대로 합니다. 위 버튼으로 문구를 복사해 Claude에게 보내면, 해부_결과.json 이 생긴 뒤 이 화면에 비교표가 나옵니다.' }));

  const table = el('table');
  table.append(el('tr', {}, ...['순위', '그룹', '릴스 (캡션 첫 줄)', '게시일', '조회수', '좋아요', '댓글', '길이', '첫 발화'].map((h, i) => el('th', { class: i >= 4 ? 'num' : '', text: h }))));
  d.reels.forEach(r => {
    const w = d.whisper[r.code];
    const first = w ? (w.first_speech_sec == null ? '말 없음' : w.first_speech_sec.toFixed(1) + '초') : '';
    const link = el('a', { href: r.url, target: '_blank', rel: 'noopener', text: r.caption || r.code });
    link.onclick = e => e.stopPropagation();
    const tr = el('tr', { class: 'reel', title: '눌러서 받아쓰기 보기' },
      el('td', { class: 'num', text: String(r.rank) }),
      el('td', {}, el('span', { class: 'tag ' + (r.group === '상위' ? 'top' : r.group === '하위' ? 'low' : ''), text: r.group }), r.ad ? el('span', { class: 'tag', text: '광고', style: 'margin-left:4px' }) : null),
      el('td', {}, link),
      el('td', { class: 'date', text: r.date }),
      el('td', { class: 'num', text: fmt(r.views) }),
      el('td', { class: 'num', text: fmt(r.likes) }),
      el('td', { class: 'num', text: fmt(r.comments) }),
      el('td', { class: 'num', text: r.duration ? r.duration.toFixed(1) + '초' : '' }),
      el('td', { class: 'num', text: first }));
    let open = null;
    tr.onclick = () => {
      if (open) { open.remove(); open = null; return; }
      open = el('tr', { class: 'detail' }, el('td', { colspan: '9' }, transcriptLines(w, r)));
      tr.after(open);
    };
    table.append(tr);
  });
  card.append(el('div', { class: 'tablewrap' }, table));
  box.append(card);

  if (d.compare_md) box.append(el('div', { class: 'card', style: 'margin-top:20px' }, mdTables(d.compare_md)));
}

$('#f').onsubmit = async e => {
  e.preventDefault();
  $('#formerr').hidden = true;
  const res = await fetch('/api/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target: $('#target').value, count: +$('#count').value, whisper: $('#whisper').checked, model: $('#model').value }) });
  const data = await res.json();
  if (!res.ok) { $('#formerr').textContent = data.error; $('#formerr').hidden = false; return; }
  $('#go').disabled = true; $('#go').textContent = '수집 중…';
  const log = $('#log'); log.hidden = false; log.textContent = '';
  const poll = async () => {
    const j = await (await fetch('/api/jobs/' + data.job)).json();
    log.textContent = j.log.join('\n'); log.scrollTop = log.scrollHeight;
    if (j.status === 'running') return setTimeout(poll, 1500);
    $('#go').disabled = false; $('#go').textContent = '수집하기';
    loadHistory(j.result);
  };
  poll();
};

loadHistory();
</script>
</body>
</html>
"""


def main():
    port = 8765
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    load_dotenv()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"릴스 분석기 → http://127.0.0.1:{port}  (끄려면 Ctrl+C)")
    if not os.environ.get("APIFY_TOKEN"):
        print("주의: APIFY_TOKEN이 없어 수집은 안 됩니다. 02-인스타분석/.env 에 APIFY_TOKEN=... 을 넣으세요.")
    print(f"결과 폴더: {results_root()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
