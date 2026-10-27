"""캡컷 자동 편집 - 작업 화면.

영상 파일·폴더를 추가하고, 옵션을 고른 뒤 [실행]을 누르면
  1 준비 → 2 음성 인식 → 3 편집 계획(Claude Code) → 4 캡컷 저장 → 5 타임라인
순서로 진행되고, 결과가 캡컷 프로젝트 목록에 바로 저장됩니다.

실행: 저장소 폴더의 '캡컷_자동편집.bat' 더블클릭 (또는 py -3 pipeline/app.py)
"""

import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CONFIG = HERE / "config.json"
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi"}
STEPS = ["1 준비", "2 음성 인식", "3 편집 계획(Claude)", "4 캡컷 저장", "5 타임라인"]
WHISPER_MODELS = ["large-v3-turbo", "medium", "small"]

CLAUDE_PROMPT = """{work} 폴더의 인터뷰 영상 편집 계획을 만들어줘.
.claude/skills/interview-shorts/SKILL.md 의 'outline.json 작성 규칙'과 'outline.json 형식'을 그대로 따라.

- {work}/transcript.txt 를 처음부터 끝까지 읽고, 단어별 시간이 필요하면 transcript.json 을 봐.
- {work}/frames/ 사진으로 얼굴 가로 위치(crop.center_x)를 정해.
- 결과는 {work}/outline.json 파일 하나로만 저장해. 다른 파일은 만들거나 고치지 마.
- 사람에게 질문할 수 없는 자동 실행이야. 애매한 건 스스로 판단하고 notes 에 적어.
- 전체본 만들기: {make_full}
- 릴스 만들기: {make_reels} (릴스 하나당 {reel_max}초 이하)
{extra}"""


def load_config():
    if CONFIG.exists():
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    return json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))


def save_config(cfg):
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def capcut_running():
    if os.name != "nt":
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"], capture_output=True, text=True,
                         errors="replace").stdout
    return "CapCut.exe" in out


def open_path(path):
    if os.name == "nt":
        os.startfile(str(path))  # noqa: S606 - 사용자 PC 의 파일·폴더 열기
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("캡컷 자동 편집")
        self.geometry("980x760")
        self.minsize(860, 640)
        self.cfg = load_config()
        self.jobs = []  # {"client","episode","video"}
        self.log_q = queue.Queue()
        self.proc = None
        self.stop_flag = threading.Event()
        self.worker = None
        self._build()
        self.after(100, self._drain_log)

    # ------------------------------------------------------------ 화면 구성
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)

        # 폴더 설정
        box = ttk.LabelFrame(root, text="폴더 설정", padding=8)
        box.grid(row=0, column=0, sticky="ew", **pad)
        box.columnconfigure(1, weight=1)
        self.var_capcut = tk.StringVar(value=self.cfg.get("capcut_draft_dir", ""))
        self.var_work = tk.StringVar(value=self.cfg.get("work_root", ""))
        for r, (label, var) in enumerate([("캡컷 프로젝트 폴더", self.var_capcut), ("작업 폴더", self.var_work)]):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w")
            ttk.Entry(box, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6)
            ttk.Button(box, text="찾기", command=lambda v=var: self._pick_dir(v)).grid(row=r, column=2)

        # 영상 목록
        box = ttk.LabelFrame(root, text="작업할 영상", padding=8)
        box.grid(row=1, column=0, sticky="nsew", **pad)
        root.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)

        top = ttk.Frame(box)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, text="업체").pack(side="left")
        self.var_client = tk.StringVar(value="한방장어")
        ttk.Entry(top, textvariable=self.var_client, width=14).pack(side="left", padx=(4, 12))
        ttk.Label(top, text="편 (비우면 자동 번호)").pack(side="left")
        self.var_episode = tk.StringVar()
        ttk.Entry(top, textvariable=self.var_episode, width=10).pack(side="left", padx=(4, 12))
        ttk.Button(top, text="파일 추가", command=self._add_files).pack(side="left", padx=2)
        ttk.Button(top, text="폴더 추가", command=self._add_folder).pack(side="left", padx=2)
        ttk.Button(top, text="선택 삭제", command=self._remove_selected).pack(side="left", padx=2)

        self.tree = ttk.Treeview(box, columns=("client", "episode", "video", "status"), show="headings", height=6)
        for col, text, w in [("client", "업체", 110), ("episode", "편", 70), ("video", "영상 파일", 520),
                             ("status", "상태", 140)]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew", pady=6)
        self.tree.bind("<Double-1>", self._edit_episode)
        ttk.Label(box, text="편 이름을 바꾸려면 목록에서 더블클릭하세요.", foreground="#666").grid(row=2, column=0, sticky="w")

        # 작업 방식
        box = ttk.LabelFrame(root, text="작업 방식", padding=8)
        box.grid(row=2, column=0, sticky="ew", **pad)
        for c in range(4):
            box.columnconfigure(c, weight=1)

        self.var_full = tk.BooleanVar(value=True)
        self.var_reels = tk.BooleanVar(value=True)
        self.var_reel_max = tk.IntVar(value=self.cfg.get("reel_max_seconds", 59))
        self.var_beauty = tk.BooleanVar(value=False)
        self.var_model = tk.StringVar(value=self.cfg["whisper"].get("model", "large-v3-turbo"))
        fx = self.cfg.get("effects", {})
        self.var_zoom = tk.BooleanVar(value=bool(fx.get("punch_in_zoom")))
        self.var_anim = tk.BooleanVar(value=bool(fx.get("answer_intro")))
        self.var_hook = tk.BooleanVar(value=True)
        self.var_skip_done = tk.BooleanVar(value=True)

        ttk.Checkbutton(box, text="전체본 만들기 (반복·침묵 정리)", variable=self.var_full).grid(row=0, column=0, sticky="w")
        f = ttk.Frame(box)
        f.grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(f, text="릴스로 나누기, 최대", variable=self.var_reels).pack(side="left")
        ttk.Spinbox(f, from_=15, to=90, width=4, textvariable=self.var_reel_max).pack(side="left")
        ttk.Label(f, text="초").pack(side="left")
        ttk.Checkbutton(box, text="첫 화면 훅 문구", variable=self.var_hook).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(box, text="얼굴 기본 보정 (오래 걸림)", variable=self.var_beauty).grid(row=0, column=3, sticky="w")
        ttk.Checkbutton(box, text="컷마다 확대·줌인 효과", variable=self.var_zoom).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(box, text="글자 등장 애니메이션", variable=self.var_anim).grid(row=1, column=1, sticky="w")
        f = ttk.Frame(box)
        f.grid(row=1, column=2, sticky="w")
        ttk.Label(f, text="음성 인식 정확도").pack(side="left")
        ttk.Combobox(f, values=WHISPER_MODELS, textvariable=self.var_model, width=14, state="readonly").pack(side="left", padx=4)
        ttk.Checkbutton(box, text="이미 한 단계는 건너뛰기", variable=self.var_skip_done).grid(row=1, column=3, sticky="w")

        f = ttk.Frame(box)
        f.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(6, 0))
        ttk.Label(f, text="실행할 단계").pack(side="left")
        self.step_vars = []
        for name in STEPS:
            v = tk.BooleanVar(value=True)
            self.step_vars.append(v)
            ttk.Checkbutton(f, text=name, variable=v).pack(side="left", padx=4)

        ttk.Label(box, text="Claude에게 추가 요청 (예: 릴스는 5개만, 메뉴 이야기 위주로, 업체명은 '한방장어구이')").grid(
            row=3, column=0, columnspan=4, sticky="w", pady=(8, 2))
        self.txt_extra = tk.Text(box, height=3, wrap="word")
        self.txt_extra.grid(row=4, column=0, columnspan=4, sticky="ew")

        # 실행 버튼 + 진행
        bar = ttk.Frame(root)
        bar.grid(row=3, column=0, sticky="ew", **pad)
        self.btn_run = ttk.Button(bar, text="▶ 실행", command=self._run)
        self.btn_run.pack(side="left")
        self.btn_stop = ttk.Button(bar, text="■ 중지", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(bar, text="작업 폴더 열기", command=self._open_work).pack(side="left", padx=6)
        ttk.Button(bar, text="타임라인 표 열기", command=self._open_timeline).pack(side="left")
        self.progress = ttk.Progressbar(bar, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)

        # 로그
        box = ttk.LabelFrame(root, text="진행 상황", padding=6)
        box.grid(row=4, column=0, sticky="nsew", **pad)
        root.rowconfigure(4, weight=1)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self.log = tk.Text(box, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(box, command=self.log.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.log["yscrollcommand"] = sb.set

    # ------------------------------------------------------------ 목록
    def _pick_dir(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or "C:/")
        if d:
            var.set(d)

    def _next_episode(self, client):
        used = {j["episode"] for j in self.jobs if j["client"] == client}
        work = Path(self.var_work.get()) / client
        if work.exists():
            used |= {p.name for p in work.iterdir() if p.is_dir()}
        n = 1
        while f"{n:02d}편" in used:
            n += 1
        return f"{n:02d}편"

    def _add_job(self, video):
        client = self.var_client.get().strip()
        if not client:
            messagebox.showwarning("업체 이름", "업체 이름을 먼저 적어 주세요.")
            return False
        episode = self.var_episode.get().strip() or self._next_episode(client)
        self.var_episode.set("")
        job = {"client": client, "episode": episode, "video": str(video)}
        self.jobs.append(job)
        job["iid"] = self.tree.insert("", "end", values=(client, episode, video, "대기"))
        return True

    def _add_files(self):
        files = filedialog.askopenfilenames(title="영상 파일 선택",
                                            filetypes=[("영상", "*.mp4 *.mov *.m4v *.mkv *.avi"), ("모든 파일", "*.*")])
        for f in files:
            if not self._add_job(f):
                break

    def _add_folder(self):
        d = filedialog.askdirectory(title="영상이 들어 있는 폴더 선택")
        if not d:
            return
        videos = sorted(p for p in Path(d).iterdir() if p.suffix.lower() in VIDEO_EXT)
        if not videos:
            messagebox.showinfo("폴더 추가", "이 폴더에는 영상 파일이 없습니다.")
            return
        for v in videos:
            if not self._add_job(v):
                break

    def _remove_selected(self):
        for iid in self.tree.selection():
            self.jobs = [j for j in self.jobs if j["iid"] != iid]
            self.tree.delete(iid)

    def _edit_episode(self, event):
        iid = self.tree.identify_row(event.y)
        job = next((j for j in self.jobs if j["iid"] == iid), None)
        if not job:
            return
        win = tk.Toplevel(self)
        win.title("편 이름 바꾸기")
        var = tk.StringVar(value=job["episode"])
        ttk.Entry(win, textvariable=var, width=20).pack(padx=12, pady=10)

        def ok():
            job["episode"] = var.get().strip() or job["episode"]
            self.tree.set(iid, "episode", job["episode"])
            win.destroy()
        ttk.Button(win, text="확인", command=ok).pack(pady=(0, 10))

    def _set_status(self, job, text):
        self.after(0, lambda: self.tree.set(job["iid"], "status", text))

    # ------------------------------------------------------------ 로그
    def _write(self, text):
        self.log_q.put(text)

    def _drain_log(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    # ------------------------------------------------------------ 실행
    def _apply_settings(self):
        cfg = self.cfg
        cfg["capcut_draft_dir"] = self.var_capcut.get().strip()
        cfg["work_root"] = self.var_work.get().strip()
        cfg["reel_max_seconds"] = int(self.var_reel_max.get())
        cfg["whisper"]["model"] = self.var_model.get()
        defaults = json.loads((HERE / "config.example.json").read_text(encoding="utf-8"))["effects"]
        fx = cfg.setdefault("effects", {})
        for key in ("punch_in_zoom", "slow_zoom"):
            fx[key] = (fx.get(key) or defaults[key]) if self.var_zoom.get() else None
        for key in ("video_intro", "hook_intro", "question_intro", "answer_intro"):
            fx[key] = (fx.get(key) or defaults[key]) if self.var_anim.get() else None
        save_config(cfg)

    def _run(self):
        if not self.jobs:
            messagebox.showinfo("실행", "먼저 '파일 추가'나 '폴더 추가'로 영상을 넣어 주세요.")
            return
        if not Path(self.var_capcut.get()).is_dir():
            messagebox.showerror("캡컷 폴더", "캡컷 프로젝트 폴더를 찾을 수 없습니다.\n캡컷 > 설정 > 프로젝트 위치를 확인해 주세요.")
            return
        self._apply_settings()
        steps = [i for i, v in enumerate(self.step_vars) if v.get()]
        if 2 in steps and not shutil.which("claude"):
            messagebox.showerror("Claude Code", "'claude' 명령을 찾을 수 없습니다. Claude Code가 설치되어 있는지 확인해 주세요.")
            return
        self.stop_flag.clear()
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.progress.configure(maximum=len(self.jobs) * len(steps), value=0)
        opts = {
            "steps": steps,
            "full": self.var_full.get(),
            "reels": self.var_reels.get(),
            "reel_max": int(self.var_reel_max.get()),
            "beauty": self.var_beauty.get(),
            "hook": self.var_hook.get(),
            "skip_done": self.var_skip_done.get(),
            "extra": self.txt_extra.get("1.0", "end").strip(),
        }
        self.worker = threading.Thread(target=self._work, args=(list(self.jobs), opts), daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_flag.set()
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self._write("[중지 요청됨]")

    def _done(self):
        self.btn_run.configure(state="normal")
        self.btn_stop.configure(state="disabled")

    def _cmd(self, args, cwd=HERE):
        """명령을 실행하고 출력을 진행 상황 창에 보여준다. 성공하면 True."""
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        self._write("> " + " ".join(str(a) for a in args[:6]) + (" ..." if len(args) > 6 else ""))
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.proc = subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, creationflags=flags)
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line.strip() and not line.startswith("  > "):
                self._write("  " + line)
        code = self.proc.wait()
        if code != 0 and not self.stop_flag.is_set():
            self._write(f"  [오류] 종료 코드 {code}")
        return code == 0

    def _work(self, jobs, o):
        py = sys.executable
        for job in jobs:
            if self.stop_flag.is_set():
                break
            work = Path(self.cfg["work_root"]) / job["client"] / job["episode"]
            base = ["--client", job["client"], "--episode", job["episode"]]
            self._write(f"\n===== {job['client']} {job['episode']} =====")
            ok = True
            for step in o["steps"]:
                if self.stop_flag.is_set() or not ok:
                    break
                self._set_status(job, STEPS[step])
                done = o["skip_done"]
                if step == 0:
                    if done and (work / "audio.wav").exists() and (work / "job.json").exists():
                        self._write("  1 준비: 이미 되어 있어 건너뜀")
                    else:
                        ok = self._cmd([py, "step1_prepare.py", *base, "--video", job["video"],
                                        *(["--beauty"] if o["beauty"] else [])])
                elif step == 1:
                    if done and (work / "transcript.json").exists():
                        self._write("  2 음성 인식: 이미 되어 있어 건너뜀")
                    else:
                        self._write("  음성 인식은 영상 길이만큼 걸릴 수 있어요. 창을 닫지 마세요.")
                        ok = self._cmd([py, "step2_transcribe.py", *base])
                elif step == 2:
                    if done and (work / "outline.json").exists():
                        self._write("  3 편집 계획: outline.json 이 있어 그대로 사용")
                    else:
                        extra = o["extra"]
                        if not o["hook"]:
                            extra += "\n- 릴스에 hook 은 넣지 마 (hook 항목 생략)."
                        prompt = CLAUDE_PROMPT.format(
                            work=str(work).replace("\\", "/"), make_full="예" if o["full"] else "아니오",
                            make_reels="예" if o["reels"] else "아니오", reel_max=o["reel_max"],
                            extra=("- 추가 요청: " + extra) if extra else "")
                        self._write("  Claude Code가 대본을 읽고 편집 계획을 세우는 중... (몇 분)")
                        prompt = " ".join(line.strip() for line in prompt.splitlines() if line.strip())
                        ok = self._cmd([shutil.which("claude"), "-p", prompt, "--add-dir", str(work),
                                        "--allowedTools", "Read,Write,Edit,Glob,Grep"], cwd=REPO)
                        ok = ok and (work / "outline.json").exists()
                        if not ok and not self.stop_flag.is_set():
                            self._write("  [오류] outline.json 이 만들어지지 않았습니다.")
                    if ok:
                        ok = self._cmd([py, "step3_make_plan.py", *base])
                elif step == 3:
                    while capcut_running() and not self.stop_flag.is_set():
                        self._write("  캡컷이 켜져 있어요. 캡컷을 닫으면 자동으로 이어서 저장합니다...")
                        self.stop_flag.wait(5)
                    ok = self._cmd([py, "step4_build_capcut.py", *base, "--replace",
                                    *([] if o["full"] else ["--no-full"]),
                                    *([] if o["reels"] else ["--no-reels"])])
                elif step == 4:
                    ok = self._cmd([py, "step5_timeline.py", *base])
                self.after(0, lambda: self.progress.configure(value=self.progress["value"] + 1))
            status = "중지됨" if self.stop_flag.is_set() else ("완료 ✔" if ok else "오류 ✖")
            self._set_status(job, status)
            self.last_work = work
        self._write("\n모든 작업이 끝났습니다. 캡컷을 열면 프로젝트 목록에 보입니다.")
        self.after(0, self._done)

    # ------------------------------------------------------------ 결과 열기
    def _selected_work(self):
        sel = self.tree.selection()
        job = next((j for j in self.jobs if sel and j["iid"] == sel[0]), None) or (self.jobs[-1] if self.jobs else None)
        if job:
            return Path(self.var_work.get()) / job["client"] / job["episode"]
        return getattr(self, "last_work", Path(self.var_work.get()))

    def _open_work(self):
        p = self._selected_work()
        p.mkdir(parents=True, exist_ok=True)
        open_path(p)

    def _open_timeline(self):
        p = self._selected_work() / "timeline.csv"
        if p.exists():
            open_path(p)
        else:
            messagebox.showinfo("타임라인", "아직 타임라인 표가 없습니다. 실행이 끝난 뒤 열어 주세요.")


if __name__ == "__main__":
    App().mainloop()
