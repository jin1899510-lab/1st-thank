"""공통 유틸: 설정 읽기, 작업 폴더 경로, ffmpeg/ffprobe 호출."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_config() -> dict:
    path = HERE / "config.json"
    if not path.exists():
        sys.exit(f"[오류] {path} 가 없습니다. config.example.json 을 복사해서 config.json 을 만들어 주세요.")
    return json.loads(path.read_text(encoding="utf-8"))


def job_dir(cfg: dict, client: str, episode: str) -> Path:
    """작업 폴더: {work_root}/{업체}/{편}"""
    d = Path(cfg["work_root"]) / client / episode
    d.mkdir(parents=True, exist_ok=True)
    return d


def draft_name(client: str, episode: str) -> str:
    return f"{client}_{episode}"


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def require_tool(name: str) -> str:
    exe = shutil.which(name)
    if not exe:
        sys.exit(f"[오류] {name} 를 찾을 수 없습니다. FFmpeg 를 설치하고 PATH 에 추가해 주세요.")
    return exe


def run(cmd: list) -> None:
    print("  >", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True)


def probe(video: Path) -> dict:
    """영상 길이(초), 가로, 세로, 회전값을 반환."""
    out = subprocess.run(
        [require_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation:format=duration",
         "-of", "json", str(video)],
        check=True, capture_output=True, text=True,
    ).stdout
    info = json.loads(out)
    st = info["streams"][0]
    w, h = int(st["width"]), int(st["height"])
    rotation = 0
    for sd in st.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(sd["rotation"])
    if abs(rotation) in (90, 270):  # 세로로 찍은 폰 영상
        w, h = h, w
    return {"duration": float(info["format"]["duration"]), "width": w, "height": h}


def hex_to_rgb(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
