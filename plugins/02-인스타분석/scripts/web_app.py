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
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from fetch_reels import default_out_dir
from prepare_dissect import split_groups, views

SCRIPTS = Path(__file__).resolve().parent
PLUGIN = SCRIPTS.parent
EDIT_SCRIPTS = PLUGIN.parent / "01-릴스편집" / "scripts"
MAKE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".mp4", ".mov", ".m4v", ".webm"}
MODELS = ("tiny", "base", "small", "medium", "large-v3")
GROUPS = (5, 10, 15)
LENGTHS = (15, 20, 25, 30, 45)
VOICES = ("hyuk", "random", "none")
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


def group_size(folder):
    # 수집할 때 고른 상위·하위 그룹 크기 (없으면 10)
    saved = read_json(folder / "수집옵션.json") or {}
    return saved.get("groups") if saved.get("groups") in GROUPS else 10


def result_detail(folder):
    reels = read_json(folder / "reels_raw.json") or []
    size = group_size(folder)
    top, bottom = split_groups(reels, size)
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
    if (folder / "해부_결과.json").exists() and len(reels) > size:
        subprocess.run([sys.executable, str(SCRIPTS / "compare_groups.py"), str(folder), str(size)],
                       capture_output=True, cwd=SCRIPTS)
        path = folder / "상위하위_비교.md"
        compare_md = path.read_text(encoding="utf-8") if path.exists() else None
    return {
        "folder": str(folder),
        "groups": size,
        "frames": (folder / "frames").exists(),
        "reels": rows,
        "whisper": read_json(folder / "transcripts_whisper.json") or {},
        "dissect": read_json(folder / "해부_결과.json"),
        "compare_md": compare_md,
    }


def job_log(job, line):
    with JOBS_LOCK:
        job["log"].append(line.rstrip())


def run_step(job, title, args, cwd=SCRIPTS):
    """파이썬 스크립트 하나를 돌리며 출력을 화면 기록에 붙인다."""
    job_log(job, f"▶ {title}")
    proc = subprocess.Popen([sys.executable, "-u", *args], cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                            env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    out = []
    for line in proc.stdout:
        if "HF Hub" in line or not line.strip():
            continue
        out.append(line)
        job_log(job, "  " + line)
    return proc.wait(), "".join(out)


# ── 릴스 만들기: 원고 + 사진·영상 → 제작 요청 (사진 분석·편집은 Claude가 이어서) ──

def make_root():
    # <고객설정>/릴스제작/<업체>/<날짜>
    return results_root().parent / "릴스제작"


def safe_name(text):
    return re.sub(r'[\\/:*?"<>|]+', "_", text).strip(" .")[:60]


def list_makes():
    root, items = make_root(), []
    if not root.exists():
        return items
    for script in root.glob("*/*/원고.txt"):
        folder = script.parent
        if folder.parent.name.startswith("_"):
            continue
        items.append({"store": folder.parent.name, "stamp": folder.name,
                      "ready": (folder / "제작요청.md").exists(), "plan": (folder / "plan.json").exists()})
    items.sort(key=lambda x: x["stamp"], reverse=True)
    return items


def make_folder(store, stamp):
    for item in list_makes():  # 목록에 있는 폴더만 연다 (경로 조작 방지)
        if item["store"] == store and item["stamp"] == stamp:
            return make_root() / store / stamp
    return None


def make_detail(folder):
    options = read_json(folder / "제작옵션.json") or {}
    sources = read_json(folder / "소스목록.json") or {}
    prompt = (f"{folder} 의 제작요청.md 대로 사진·영상(sheets)을 보고 원고에 맞춰 장면을 짜서 "
              f"릴스를 만들고 캡컷 프로젝트「{options.get('store', '')}」에 넣어줘.")
    return {
        "folder": str(folder),
        "options": options,
        "script": (folder / "원고.txt").read_text(encoding="utf-8-sig") if (folder / "원고.txt").exists() else "",
        "source": sources.get("source"),
        "items": sources.get("items", []),
        "ready": (folder / "제작요청.md").exists(),
        "plan": (folder / "plan.json").exists(),
        "prompt": prompt,
    }


def run_make(job_id, folder, source, photo_sec):
    job = JOBS[job_id]
    try:
        code, _ = run_step(job, "사진·영상 정리 (사진 → 세로 영상, 확인용 사진)",
                           ["prepare_sources.py", str(source), str(folder), "--photo-sec", str(photo_sec)], cwd=EDIT_SCRIPTS)
        if code != 0:
            raise RuntimeError("사진·영상을 정리하지 못했습니다. 위 메시지를 확인하세요.")
        job["status"] = "done"
        job_log(job, "✔ 준비 끝. 아래 [Claude에게 보낼 문구 복사]를 눌러 Claude에게 보내면 사진을 보고 릴스를 만들어 캡컷에 넣습니다.")
    except Exception as exc:  # 화면에 이유를 보여주고 끝낸다
        job_log(job, f"✖ {exc}")
        job["status"] = "error"


def run_job(job_id, target, count, opts):
    job = JOBS[job_id]
    groups = opts["groups"]

    def log(line):
        job_log(job, line)

    def step(title, args):
        return run_step(job, title, args)

    try:
        fetch = ["fetch_reels.py", target, str(count), "--transcript"] + (["--shares"] if opts["shares"] else [])
        code, out = step("1. 릴스 가져오기 (Apify)", fetch)
        found = re.search(r"저장 → (.+)", out)
        if code != 0 or not found:
            raise RuntimeError("릴스를 가져오지 못했습니다. 위 메시지를 확인하세요.")
        folder = Path(found.group(1).strip())
        (folder / "수집옵션.json").write_text(json.dumps(opts, ensure_ascii=False, indent=2), encoding="utf-8")
        job["result"] = {"account": folder.parent.name, "stamp": folder.name}

        if opts["whisper"]:
            args = ["transcribe_whisper.py", str(folder), "--model", opts["model"], "--groups", str(groups)]
            code, _ = step("2. 위스퍼 받아쓰기 (내 컴퓨터)", args + (["--prompt", opts["prompt"]] if opts["prompt"] else []))
            if code != 0:
                log("  위스퍼 단계가 실패했습니다. 수집 결과는 그대로 볼 수 있습니다.")
        else:
            log("▶ 2. 위스퍼 받아쓰기 — 건너뜀")

        step("3. 해부 자료 만들기", ["prepare_dissect.py", str(folder), str(groups)])

        if opts["frames"]:
            args = ["extract_frames.py", str(folder), "--groups", str(groups)] + (["--top-only"] if opts["framesTopOnly"] else [])
            code, _ = step("4. 영상 해부 자료 (초반 3초·장면 사진)", args)
            if code != 0:
                log("  영상 해부 자료를 만들지 못했습니다. 수집 결과는 그대로 볼 수 있습니다.")
        else:
            log("▶ 4. 영상 해부 자료 — 건너뜀")
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
        if path == "/api/makes":
            return self.send(200, list_makes())
        m = re.fullmatch(r"/api/makes/([^/]+)/([^/]+)", path)
        if m:
            folder = make_folder(*m.groups())
            return self.send(200, make_detail(folder)) if folder else self.send(404, {"error": "제작 요청을 찾지 못했습니다."})
        m = re.fullmatch(r"/api/makes/([^/]+)/([^/]+)/sheets/([^/]+\.jpg)", path)
        if m:
            folder = make_folder(m.group(1), m.group(2))
            sheet = folder / "sheets" / m.group(3) if folder else None
            if sheet and sheet.is_file():
                return self.send(200, sheet.read_bytes(), "image/jpeg")
        return self.send(404, {"error": "없는 주소입니다."})

    def read_body_json(self):
        try:
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return None

    def make_draft(self):
        draft_id = uuid.uuid4().hex[:12]
        (make_root() / "_올리는중" / draft_id / "소스").mkdir(parents=True, exist_ok=True)
        return self.send(200, {"draft": draft_id})

    def make_upload(self, draft_id):
        name = Path(unquote(urlparse(self.path).query.partition("name=")[2])).name
        folder = make_root() / "_올리는중" / draft_id / "소스"
        length = int(self.headers.get("Content-Length") or 0)
        if not folder.is_dir():
            return self.send(404, {"error": "올리기 준비가 안 됐습니다. 화면을 새로 고쳐 주세요."})
        if Path(name).suffix.lower() not in MAKE_EXT:
            self.rfile.read(length)
            return self.send(400, {"error": f"{name}: 사진(jpg·png·webp)이나 영상(mp4·mov)만 올릴 수 있어요. HEIC는 JPG로 바꿔 주세요."})
        dest, n = folder / name, 1
        while dest.exists():  # 같은 이름이면 뒤에 번호
            dest, n = folder / f"{Path(name).stem}_{n}{Path(name).suffix}", n + 1
        with dest.open("wb") as f:
            left = length
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        return self.send(200, {"saved": dest.name})

    def make_start(self):
        body = self.read_body_json()
        if body is None:
            return self.send(400, {"error": "요청 형식이 올바르지 않습니다."})
        store = safe_name(str(body.get("store") or ""))
        script = str(body.get("script") or "").strip()
        draft = str(body.get("draft") or "")
        if not store:
            return self.send(400, {"error": "업체 이름(캡컷 프로젝트 이름)을 넣어 주세요."})
        if not script:
            return self.send(400, {"error": "원고를 넣어 주세요."})
        draft_dir = make_root() / "_올리는중" / draft / "소스" if re.fullmatch(r"[0-9a-f]{12}", draft) else None
        if draft_dir and draft_dir.is_dir() and any(draft_dir.iterdir()):
            source = None
        else:
            draft_dir = None
            source = Path(str(body.get("folder") or "").strip().strip('"'))
            if not str(body.get("folder") or "").strip() or not source.is_dir():
                return self.send(400, {"error": "사진·영상 폴더 주소를 넣거나 파일을 끌어다 놓아 주세요."})
        if any(j["status"] == "running" for j in JOBS.values()):
            return self.send(409, {"error": "다른 작업이 돌고 있습니다. 끝난 뒤 다시 눌러주세요."})
        try:
            photo_sec = min(max(float(body.get("photoSec") or 3), 1.5), 6)
        except (TypeError, ValueError):
            photo_sec = 3.0
        folder = make_root() / store / datetime.now().strftime("%Y%m%d_%H%M%S")
        folder.mkdir(parents=True)
        if draft_dir:
            shutil.move(str(draft_dir), str(folder / "소스"))
            shutil.rmtree(draft_dir.parent, ignore_errors=True)
            source = folder / "소스"
        options = {
            "store": store,
            "title": str(body.get("title") or "").strip()[:60],
            "length": body.get("length") if body.get("length") in LENGTHS else 30,
            "voice": body.get("voice") if body.get("voice") in VOICES else "hyuk",
            "bgm": bool(body.get("bgm")),
            "hook": bool(body.get("hook")),
            "photoSec": photo_sec,
            "source": str(source),
        }
        (folder / "원고.txt").write_text(script + "\n", encoding="utf-8")
        (folder / "제작옵션.json").write_text(json.dumps(options, ensure_ascii=False, indent=2), encoding="utf-8")
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "status": "running", "log": [], "result": {"store": store, "stamp": folder.name}}
        threading.Thread(target=run_make, args=(job_id, folder, source, photo_sec), daemon=True).start()
        return self.send(200, {"job": job_id})

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/make/draft":
            return self.make_draft()
        m = re.fullmatch(r"/api/make/([0-9a-f]{12})/file", path)
        if m:
            return self.make_upload(m.group(1))
        if path == "/api/make/start":
            return self.make_start()
        if path != "/api/collect":
            return self.send(404, {"error": "없는 주소입니다."})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.send(400, {"error": "요청 형식이 올바르지 않습니다."})
        target = str(body.get("target") or "").strip()
        try:
            count = int(body.get("count") or 30)
        except (TypeError, ValueError):
            count = 30
        opts = {
            "groups": body.get("groups") if body.get("groups") in GROUPS else 10,
            "whisper": bool(body.get("whisper")),
            "model": body.get("model") if body.get("model") in MODELS else "small",
            "prompt": str(body.get("prompt") or "").strip()[:200],
            "frames": bool(body.get("frames")),
            "framesTopOnly": bool(body.get("framesTopOnly")),
            "shares": bool(body.get("shares")),
        }
        if not target:
            return self.send(400, {"error": "계정 아이디나 릴스 링크를 넣어주세요."})
        if not os.environ.get("APIFY_TOKEN"):
            return self.send(400, {"error": "APIFY_TOKEN이 없습니다. 02-인스타분석/.env 파일에 APIFY_TOKEN=... 을 넣고 서버를 다시 켜세요."})
        if any(j["status"] == "running" for j in JOBS.values()):
            return self.send(409, {"error": "이미 수집 중입니다. 끝난 뒤 다시 눌러주세요."})
        job_id = uuid.uuid4().hex[:12]
        JOBS[job_id] = {"id": job_id, "status": "running", "log": [], "result": None}
        threading.Thread(target=run_job, args=(job_id, target, max(1, min(count, 100)), opts), daemon=True).start()
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
[hidden] { display: none !important; }
.panel { grid-column: 1 / -1; display: grid; gap: 10px; }
.optrow { display: grid; grid-template-columns: 11rem minmax(0, 1fr) auto; gap: 10px; align-items: center; }
.optrow.sub { padding-left: 32px; grid-template-columns: 11rem minmax(0, 1fr); }
.optrow.sub input[type=text] { grid-column: 1 / -1; }
.lab { font-weight: 600; font-size: .9rem; display: grid; }
.hint { color: var(--muted); font-weight: 400; font-size: .8rem; }
.seg { display: flex; flex-wrap: wrap; gap: 4px; background: var(--bg); border: 1px solid var(--line); border-radius: 10px; padding: 3px; }
.seg button { flex: 1 1 4rem; background: transparent; color: var(--fg); font-weight: 500; padding: 6px 10px; }
.seg button[aria-pressed=true] { background: var(--accent); color: var(--panel); font-weight: 600; }
.tog { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: start; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; cursor: pointer; }
.tog:has(input:checked) { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); background: var(--accent-soft); }
.tog input { width: 20px; height: 20px; accent-color: var(--accent); margin: 2px 0 0; }
.tog > span { display: grid; gap: 2px; }
.grid2 { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 18rem), 1fr)); gap: 12px; }
.lab input, .lab textarea { margin-top: 4px; font-weight: 400; }
textarea { font: inherit; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--bg); color: var(--fg); width: 100%; resize: vertical; }
.drop { border: 2px dashed var(--line); border-radius: 10px; padding: 18px; text-align: center; display: grid; gap: 4px; cursor: pointer; }
.drop.over, .drop:hover { border-color: var(--accent); background: var(--accent-soft); }
.queue { display: grid; gap: 2px; font-size: .85rem; }
.queue div { display: flex; justify-content: space-between; gap: 8px; }
.sheets { display: grid; gap: 10px; }
.sheets figure { margin: 0; display: grid; gap: 4px; }
.sheets img { max-width: 100%; border-radius: 6px; background: var(--bg); }
.sheets figcaption { font-size: .85rem; }
pre.script { margin: 0; white-space: pre-wrap; background: var(--bg); border-radius: 8px; padding: 12px; font: inherit; font-size: .9rem; }
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
@media (max-width: 560px) { form, .optrow, .optrow.sub { grid-template-columns: 1fr; } .optrow.sub { padding-left: 0; } .lines div { grid-template-columns: 1fr; } }
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
      <div class="panel" id="opts">
        <div class="optrow"><span class="lab">개수<span class="hint">최신 릴스 몇 개를 모을지</span></span><div class="seg" id="count-seg"></div>
          <input type="number" id="count" value="30" min="1" max="100" aria-label="개수 직접 입력"></div>
        <div class="optrow"><span class="lab">상위·하위 그룹<span class="hint">조회수 위·아래 몇 개씩 비교할지</span></span><div class="seg" id="groups-seg"></div></div>
        <label class="tog"><input type="checkbox" id="whisper" checked><span><b>위스퍼 받아쓰기</b><span class="hint">상위·하위 릴스가 몇 초에 무슨 말을 했는지 내 컴퓨터에서 받아씁니다 (무료)</span></span></label>
        <div class="optrow sub" id="whisper-opts"><span class="lab">모델<span class="hint">왼쪽은 빠르고, 오른쪽은 정확</span></span><div class="seg" id="model-seg"></div>
          <input type="text" id="prompt" placeholder="자주 틀리게 받아쓰는 이름 (예: 대대손떡, 기피인절미)" maxlength="200" aria-label="자주 틀리는 이름"></div>
        <label class="tog"><input type="checkbox" id="frames"><span><b>영상 해부 자료 만들기</b><span class="hint">영상을 받아 초반 3초 사진과 장면 전환 사진을 만듭니다 (ffmpeg 필요, 시간이 더 걸림)</span></span></label>
        <div class="optrow sub" id="frames-opts"><span class="lab">범위</span><div class="seg" id="frames-seg"></div></div>
        <label class="tog"><input type="checkbox" id="shares"><span><b>공유 수 가져오기</b><span class="hint">Apify 유료 요금제에서만 됩니다</span></span></label>
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

  <section class="card" id="make">
    <div>
      <h2>릴스 만들기</h2>
      <p class="sub">원고와 찍어 둔 사진·영상을 넣으면, 사진은 세로 영상(천천히 확대)으로 바꾸고 장면을 확인할 사진을 만듭니다.
        그다음 Claude가 사진을 보고 원고에 맞춰 장면을 짜서 캡컷 프로젝트에 넣습니다.</p>
    </div>
    <div class="grid2">
      <label class="lab">업체 이름<span class="hint">캡컷 프로젝트 이름 (업체 하나 = 프로젝트 하나)</span><input type="text" id="m-store" placeholder="예: 화남정 돼지국밥" maxlength="60"></label>
      <label class="lab">편 제목<span class="hint">타임라인 이름 "03 제목" 처럼 들어갑니다</span><input type="text" id="m-title" placeholder="예: 부산 돼지국밥 대전 쇼케이스" maxlength="60"></label>
    </div>
    <label class="lab">원고<span class="hint">한 줄에 한 문장. 나레이션 없이 화면 글자로만 넣을 줄은 앞에 [자막] 을 붙여 주세요.</span>
      <textarea id="m-script" rows="8" placeholder="부산 사람이면 이건 안 올 수가 없지예&#10;전국 최초 돼지국밥 야장이 단 3일 열립니다&#10;[자막] BIFC2 나우어라이빙 · 금~일"></textarea></label>
    <div class="optrow"><span class="lab">사진·영상 폴더<span class="hint">내 PC 폴더 주소 (하위 폴더까지 봅니다)</span></span>
      <input type="text" id="m-folder" placeholder="예: D:\화남정" autocomplete="off"></div>
    <div class="drop" id="m-drop" tabindex="0" role="button" aria-label="사진·영상 올리기">
      <b>또는 여기에 사진·영상(폴더째도 됨)을 끌어다 놓기</b><span class="hint">누르면 파일을 고를 수 있어요 · 올린 파일이 있으면 위 폴더 주소 대신 씁니다</span>
      <input type="file" id="m-file" accept="image/jpeg,image/png,image/webp,video/*,.mov" multiple hidden>
    </div>
    <div class="queue" id="m-queue"></div>
    <div class="optrow"><span class="lab">영상 길이</span><div class="seg" id="m-len-seg"></div></div>
    <div class="optrow"><span class="lab">목소리<span class="hint">일레븐랩스</span></span><div class="seg" id="m-voice-seg"></div></div>
    <div class="optrow"><span class="lab">사진 한 장 길이<span class="hint">사진 → 세로 영상</span></span><div class="seg" id="m-photo-seg"></div></div>
    <label class="tog"><input type="checkbox" id="m-bgm" checked><span><b>배경음악 넣기</b><span class="hint">원고 분위기에 맞는 연주곡 (일레븐랩스, 가사 없음). 말소리 구간은 자동으로 작아짐</span></span></label>
    <label class="tog"><input type="checkbox" id="m-hook" checked><span><b>후킹 제목 + 커버 만들기</b><span class="hint">원고와 맞는 제목을 0초에 띄우고 같은 제목으로 썸네일 커버도</span></span></label>
    <div class="row"><span class="muted" id="m-hint">원고와 사진·영상을 넣고 눌러 주세요.</span><button type="button" id="m-go">사진 분석 준비하기</button></div>
    <p class="err" id="m-err" hidden></p>
    <pre class="log" id="m-log" hidden></pre>
  </section>

  <section class="card">
    <h2>지난 제작 요청</h2>
    <div class="history" id="m-history"><span class="muted">불러오는 중…</span></div>
  </section>

  <section id="m-result" hidden></section>
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
    body: JSON.stringify({ target: $('#target').value, count: OPTS.count, groups: OPTS.groups, whisper: $('#whisper').checked, model: OPTS.model,
      prompt: $('#prompt').value, frames: $('#frames').checked, framesTopOnly: OPTS.framesTopOnly, shares: $('#shares').checked }) });
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

// 수집 옵션: 고른 값은 이 브라우저에 기억해 두고 다음에 그대로 보여준다
const OPTS = { count: 30, groups: 10, model: 'small', framesTopOnly: true };
const CHECKS = ['whisper', 'frames', 'shares'];
const SEGS = { 'count-seg': 'count', 'groups-seg': 'groups', 'model-seg': 'model', 'frames-seg': 'framesTopOnly' };
const MODEL_LABEL = { small: 'small 추천' };
function seg(id, values, label) {
  $('#' + id).replaceChildren(...values.map(v => {
    const b = el('button', { type: 'button', text: label(v) });
    b.dataset.v = String(v);
    b.onclick = () => { OPTS[SEGS[id]] = v; paintOpts(); };
    return b;
  }));
}
function paintOpts() {
  document.querySelectorAll('#opts .seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === String(OPTS[SEGS[b.parentElement.id]]))));
  if (document.activeElement !== $('#count')) $('#count').value = OPTS.count;
  $('#whisper-opts').hidden = !$('#whisper').checked;
  $('#frames-opts').hidden = !$('#frames').checked;
  try {
    const saved = { ...OPTS, prompt: $('#prompt').value };
    CHECKS.forEach(id => { saved[id] = $('#' + id).checked; });
    localStorage.setItem('reels-collect-opts', JSON.stringify(saved));
  } catch {}
}
seg('count-seg', [10, 20, 30, 50, 100], v => v + '개');
seg('groups-seg', [5, 10, 15], v => v + '개씩');
seg('model-seg', ['tiny', 'base', 'small', 'medium', 'large-v3'], v => MODEL_LABEL[v] || v);
seg('frames-seg', [true, false], v => v ? '상위만' : '상위·하위 모두');
try {
  const saved = JSON.parse(localStorage.getItem('reels-collect-opts') || '{}');
  Object.keys(OPTS).forEach(k => { if (k in saved) OPTS[k] = saved[k]; });
  CHECKS.forEach(id => { if (id in saved) $('#' + id).checked = !!saved[id]; });
  if (typeof saved.prompt === 'string') $('#prompt').value = saved.prompt;
} catch {}
$('#count').oninput = () => { const n = Math.round(+$('#count').value); if (n >= 1 && n <= 100) OPTS.count = n; paintOpts(); };
$('#prompt').oninput = paintOpts;
CHECKS.forEach(id => { $('#' + id).onchange = paintOpts; });
paintOpts();

// ── 릴스 만들기 ──
const MOPTS = { length: 30, voice: 'hyuk', photoSec: 3 };
const MSEGS = { 'm-len-seg': 'length', 'm-voice-seg': 'voice', 'm-photo-seg': 'photoSec' };
let draft = null, uploading = 0;
function mseg(id, values, label) {
  $('#' + id).replaceChildren(...values.map(v => {
    const b = el('button', { type: 'button', text: label(v) });
    b.dataset.v = String(v);
    b.onclick = () => { MOPTS[MSEGS[id]] = v; paintMake(); };
    return b;
  }));
}
function paintMake() {
  document.querySelectorAll('#make .seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.v === String(MOPTS[MSEGS[b.parentElement.id]]))));
}
mseg('m-len-seg', [15, 20, 25, 30, 45], v => v + '초');
mseg('m-voice-seg', ['hyuk', 'random', 'none'], v => ({ hyuk: '혁 (기본)', random: '한국 음성 랜덤', none: '없음 (자막만)' })[v]);
mseg('m-photo-seg', [2, 3, 4], v => v + '초');
paintMake();

async function uploadFiles(files) {
  const queue = $('#m-queue');
  if (!draft) draft = (await (await fetch('/api/make/draft', { method: 'POST' })).json()).draft;
  for (const f of files) {
    const row = el('div', {}, el('span', { text: f.name }), el('span', { class: 'muted', text: '올리는 중…' }));
    queue.append(row);
    uploading++; $('#m-go').disabled = true;
    try {
      const res = await fetch(`/api/make/${draft}/file?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
      const d = await res.json();
      row.lastChild.textContent = res.ok ? '올림' : d.error;
      if (!res.ok) row.lastChild.className = 'err';
    } catch { row.lastChild.textContent = '올리지 못했어요'; row.lastChild.className = 'err'; }
    uploading--; $('#m-go').disabled = uploading > 0;
  }
}
async function readEntry(entry) {
  if (entry.isFile) return new Promise(res => entry.file(f => res([f]), () => res([])));
  if (!entry.isDirectory) return [];
  const reader = entry.createReader(), out = [];
  for (;;) {
    const batch = await new Promise(res => reader.readEntries(res, () => res([])));
    if (!batch.length) break;
    for (const e of batch) out.push(...await readEntry(e));
  }
  return out;
}
const drop = $('#m-drop');
drop.onclick = () => $('#m-file').click();
drop.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); $('#m-file').click(); } };
$('#m-file').onchange = () => { const f = [...$('#m-file').files]; $('#m-file').value = ''; uploadFiles(f); };
['dragenter', 'dragover'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(n => drop.addEventListener(n, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', async e => {
  const entries = [...(e.dataTransfer?.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  const files = entries.length ? (await Promise.all(entries.map(readEntry))).flat() : [...(e.dataTransfer?.files || [])];
  uploadFiles(files.filter(f => !f.name.startsWith('.')));
});

async function loadMakes(select) {
  const items = await (await fetch('/api/makes')).json();
  const box = $('#m-history'); box.replaceChildren();
  if (!items.length) { box.append(el('span', { class: 'muted', text: '아직 제작 요청이 없습니다.' })); return; }
  items.forEach(it => {
    const when = it.stamp.replace(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})\d*$/, '$2/$3 $4:$5');
    const b = el('button', { class: 'ghost', type: 'button', text: `${it.store} · ${when}` + (it.plan ? ' · 편집 계획 있음' : it.ready ? ' · Claude 대기' : ' · 준비 안 됨') });
    b.onclick = () => openMake(it.store, it.stamp);
    box.append(b);
  });
  if (select) openMake(select.store, select.stamp);
}
async function openMake(store, stamp) {
  const d = await (await fetch(`/api/makes/${encodeURIComponent(store)}/${encodeURIComponent(stamp)}`)).json();
  const box = $('#m-result'); box.hidden = false; box.replaceChildren();
  const o = d.options || {};
  const copy = el('button', { type: 'button', text: 'Claude에게 보낼 문구 복사' });
  copy.onclick = async () => { try { await navigator.clipboard.writeText(d.prompt); copy.textContent = '복사됨 — Claude에게 붙여넣으세요'; } catch { window.prompt('아래 문구를 복사하세요', d.prompt); } };
  const voice = { hyuk: '혁', random: '한국 음성 랜덤', none: '없음 (자막만)' }[o.voice] || o.voice;
  const card = el('div', { class: 'card' },
    el('div', { class: 'row' },
      el('div', {}, el('h2', { text: `${o.store}${o.title ? ' · ' + o.title : ''}` }),
        el('p', { class: 'sub', text: `${o.length}초 · 목소리 ${voice} · 배경음악 ${o.bgm ? '넣음' : '안 넣음'} · 후킹 제목 ${o.hook ? '넣음' : '안 넣음'} · 사진 ${o.photoSec}초` })),
      d.ready ? copy : null),
    el('p', { class: 'muted', text: d.ready ? `사진·영상 ${d.items.length}개를 정리했습니다. 위 버튼으로 문구를 복사해 Claude에게 보내면 사진을 보고 원고에 맞춰 릴스를 만들어 캡컷에 넣습니다. 저장 위치 ${d.folder}` : '아직 정리가 끝나지 않았습니다.' }),
    el('pre', { class: 'script', text: d.script }));
  if (d.items.length) {
    const grid = el('div', { class: 'sheets' });
    d.items.forEach(it => {
      const name = it.sheet ? it.sheet.split('/').pop() : null;
      grid.append(el('figure', {},
        name ? el('img', { src: `/api/makes/${encodeURIComponent(store)}/${encodeURIComponent(stamp)}/sheets/${encodeURIComponent(name)}`, alt: it.rel, loading: 'lazy' }) : null,
        el('figcaption', { text: `${it.key} · ${it.kind === 'video' ? '영상 ' + (it.duration ? it.duration.toFixed(1) + '초' : '') : '사진' + (it.clip ? ' → 세로 영상' : '')} · ${it.rel}` })));
    });
    card.append(grid);
  }
  box.append(card);
}
$('#m-go').onclick = async () => {
  $('#m-err').hidden = true;
  const body = { store: $('#m-store').value, title: $('#m-title').value, script: $('#m-script').value, folder: $('#m-folder').value,
    draft, ...MOPTS, bgm: $('#m-bgm').checked, hook: $('#m-hook').checked };
  const res = await fetch('/api/make/start', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const data = await res.json();
  if (!res.ok) { $('#m-err').textContent = data.error; $('#m-err').hidden = false; return; }
  draft = null; $('#m-queue').replaceChildren();
  $('#m-go').disabled = true; $('#m-go').textContent = '정리 중…';
  const log = $('#m-log'); log.hidden = false; log.textContent = '';
  const poll = async () => {
    const j = await (await fetch('/api/jobs/' + data.job)).json();
    log.textContent = j.log.join('\n'); log.scrollTop = log.scrollHeight;
    if (j.status === 'running') return setTimeout(poll, 1500);
    $('#m-go').disabled = false; $('#m-go').textContent = '사진 분석 준비하기';
    loadMakes(j.result);
  };
  poll();
};

loadHistory();
loadMakes();
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
