"""원고 + 촬영 소스(사진·영상) 폴더로 릴스 제작 요청을 준비한다.

사용법:
    python3 prepare_sources.py <소스폴더> <작업폴더> [--photo-sec 3] [--no-clips]

    소스폴더  촬영 원본(사진·영상)이 있는 폴더. 하위 폴더까지 본다.
    작업폴더  원고.txt, 제작옵션.json 이 들어 있는 폴더 (분석기 화면이 만든다)

하는 일:
  1. 소스 목록: 사진·영상마다 가로·세로·길이를 잰다 (ffprobe).
  2. 사진 → 영상: 사진마다 9:16 세로 영상(천천히 확대, 기본 3초)을 만든다.
     가로 사진은 흐린 배경 위에 통째로 얹는다. 결과는 <소스폴더>/릴스_사진영상/ 에 둔다
     (캡컷 설치 때 원본 폴더 안에서 찾을 수 있게).
  3. 확인용 사진: 영상은 6장, 사진은 1장을 sheets/ 에 만든다 → Claude가 보고 장면을 고른다.
  4. 소스목록.json 과 제작요청.md 를 작업폴더에 쓴다.

필요한 것: ffmpeg, ffprobe
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
CLIP_DIR = "릴스_사진영상"
W, H, FPS = 1080, 1920, 30


def parse_args(argv):
    opts = {"photo_sec": 3.0, "clips": True}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-clips":
            opts["clips"] = False
        elif a == "--photo-sec" and i + 1 < len(argv):
            opts["photo_sec"] = float(argv[i + 1])
            i += 1
        else:
            rest.append(a)
        i += 1
    if len(rest) < 2:
        sys.exit(__doc__)
    return Path(rest[0]), Path(rest[1]), opts


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                          "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, errors="replace").stdout
    info = json.loads(out or "{}")
    stream = (info.get("streams") or [{}])[0]
    w, h = stream.get("width"), stream.get("height")
    rot = stream.get("tags", {}).get("rotate") or next(
        (s.get("rotation") for s in stream.get("side_data_list", []) if "rotation" in s), 0)
    if w and h and abs(int(float(rot or 0))) % 180 == 90:  # 휴대폰 세로 영상은 돌려서 저장된 경우가 많다
        w, h = h, w
    dur = info.get("format", {}).get("duration")
    return w, h, round(float(dur), 2) if dur not in (None, "N/A") else None


def photo_clip(src, dest, sec, wide):
    frames = int(sec * FPS)
    zoom = f"zoompan=z='min(1+0.10*on/{frames},1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS}"
    if wide:  # 가로 사진: 흐린 배경 + 가운데 통째로
        vf = (f"[0:v]split[a][b];[a]scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},boxblur=40[bg];"
              f"[b]scale={W*2}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,{zoom}")
        args = ["-filter_complex", vf]
    else:
        args = ["-vf", f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},{zoom}"]
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), *args,
                    "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(dest)], check=True)


def sheet(src, dest, kind, dur):
    if kind == "photo":
        vf = "scale=480:-2"
    else:  # 영상은 고르게 6장
        step = max((dur or 6) / 6, 0.2)
        vf = f"fps=1/{step:.3f},scale=200:-2,tile=6x1"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-vf", vf,
                    "-frames:v", "1", "-q:v", "4", str(dest)], check=False)
    return dest.exists()


def fmt_sec(s):
    return f"{s:.1f}초" if s else "-"


def main():
    source, work, opts = parse_args(sys.argv[1:])
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg가 없습니다. 설치한 뒤 다시 실행하세요.")
    if not source.is_dir():
        sys.exit(f"소스 폴더가 없습니다: {source}")
    # 메모장에서 저장한 파일도 읽히게 utf-8-sig (앞의 BOM 무시)
    script = (work / "원고.txt").read_text(encoding="utf-8-sig") if (work / "원고.txt").exists() else ""
    options = json.loads((work / "제작옵션.json").read_text(encoding="utf-8-sig")) if (work / "제작옵션.json").exists() else {}
    sheets = work / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    clip_dir = source / CLIP_DIR

    files = sorted(p for p in source.rglob("*")
                   if p.is_file() and p.suffix.lower() in VIDEO_EXT | PHOTO_EXT
                   and CLIP_DIR not in p.relative_to(source).parts and not p.name.startswith("."))
    skipped = sorted(p.name for p in source.rglob("*") if p.is_file() and p.suffix.lower() in {".heic", ".heif"})
    if not files:
        sys.exit("소스 폴더에 사진·영상이 없습니다 (jpg·png·webp·mp4·mov).")

    items = []
    for n, f in enumerate(files, 1):
        kind = "video" if f.suffix.lower() in VIDEO_EXT else "photo"
        w, h, dur = probe(f)
        item = {"key": f"m{n:02d}", "kind": kind, "rel": f.relative_to(source).as_posix(), "local": str(f),
                "width": w, "height": h, "duration": dur if kind == "video" else None}
        if kind == "photo" and opts["clips"] and w and h:
            clip_dir.mkdir(exist_ok=True)
            dest = clip_dir / f"{f.stem}.mp4"
            photo_clip(f, dest, opts["photo_sec"], wide=w / h > 0.75)
            item["clip"] = {"rel": dest.relative_to(source).as_posix(), "local": str(dest),
                            "width": W, "height": H, "duration": opts["photo_sec"]}
        item["sheet"] = f"sheets/{n:02d}_{f.stem}.jpg" if sheet(f, sheets / f"{n:02d}_{f.stem}.jpg", kind, dur) else None
        items.append(item)
        print(f"  {n}. {item['rel']}  {kind}  {w}×{h}  {fmt_sec(item['duration'])}" + ("  → 영상으로 변환" if "clip" in item else ""))

    (work / "소스목록.json").write_text(json.dumps({"source": str(source), "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 릴스 제작 요청", "",
             f"- 업체(캡컷 프로젝트): {options.get('store') or '(빈칸)'}",
             f"- 편 제목(타임라인): {options.get('title') or '(빈칸)'}",
             f"- 소스 폴더(설치 때 --source): {source}",
             f"- 옵션: {json.dumps({k: v for k, v in options.items() if k not in ('store', 'title')}, ensure_ascii=False)}",
             "", "## 원고", "", "```", script.strip(), "```", "",
             "## 소스", "",
             "sheets/ 의 확인용 사진을 보고 원고 장면에 맞춘다. 사진은 clip(9:16 영상)을 쓴다.", "",
             "| 키 | 종류 | 파일 | 크기 | 길이 | 확인용 사진 | 사진→영상 |", "|---|---|---|---|---|---|---|"]
    for it in items:
        lines.append(f"| {it['key']} | {'영상' if it['kind'] == 'video' else '사진'} | {it['rel']} | {it['width']}×{it['height']} "
                     f"| {fmt_sec(it['duration'])} | {it['sheet'] or '-'} | {it['clip']['rel'] if it.get('clip') else '-'} |")
    if skipped:
        lines += ["", f"HEIC 사진은 읽을 수 없어 뺐습니다 (JPG로 바꿔 다시): {', '.join(skipped)}"]
    lines += ["", "## 할 일 (Claude)", "",
              "plugins/01-릴스편집/skills/reels-edit/SKILL.md 2~3단계대로 plan.json 을 이 폴더에 쓰고 "
              "render_cards.py → (나레이션) tts_elevenlabs.py → build_capcut.py → install_capcut.py --source 위 소스 폴더 순서로 캡컷에 넣는다."]
    (work / "제작요청.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"제작 요청 → {work / '제작요청.md'}")
    if skipped:
        print(f"HEIC {len(skipped)}개는 읽을 수 없어 뺐습니다.")


if __name__ == "__main__":
    main()
