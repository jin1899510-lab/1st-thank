"""릴스 영상을 정지 화면으로 잘라 자막(폰트·위치)·화면 전환·초반 3초를 눈으로 해부할 자료를 만든다.

사용법:
    python3 extract_frames.py <결과폴더> [옵션]

    결과폴더  fetch_reels.py가 만든 폴더 (reels_raw.json이 있는 곳)

옵션:
    --groups N      조회수 상위 N개 + 하위 N개 (기본 10)
    --top-only      상위 N개만
    --threshold T   장면 전환 감도 0~1 (기본 0.3, 낮을수록 전환을 더 많이 잡음)

결과 (릴스마다 frames/<코드>/):
    hook.jpg     0~3초를 0.5초 간격 7장으로 이어 붙인 사진 (초반 3초 해부용)
    cuts.jpg     장면이 바뀔 때마다 첫 화면을 이어 붙인 사진 (전환·자막 흐름 해부용)
    scenes.json  전환 시점, 장면별 길이, 3초 안 전환 수, 위스퍼 말 구간과의 겹침
그리고 결과폴더에 영상해부_입력.md (릴스별 수치 + 사진 경로 + 초 단위 받아쓰기)

필요한 것: ffmpeg (윈도우는 https://www.gyan.dev/ffmpeg/builds/ 에서 받아 PATH에 추가),
           pip install pillow
영상은 video/<코드>.mp4 에 보관한다 (인스타 링크는 며칠 뒤 만료).
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests

from prepare_dissect import split_groups, views

HOOK_TIMES = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0]
MIN_SHOT = 0.25  # 이보다 짧은 간격의 전환은 같은 전환으로 본다
THUMB_W = 240


def parse_args(argv):
    opts = {"groups": 10, "top_only": False, "threshold": 0.3}
    rest, i = [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--top-only":
            opts["top_only"] = True
        elif a in ("--groups", "--threshold") and i + 1 < len(argv):
            opts[a[2:]] = float(argv[i + 1]) if a == "--threshold" else int(argv[i + 1])
            i += 1
        else:
            rest.append(a)
        i += 1
    if not rest:
        sys.exit(__doc__)
    return Path(rest[0]), opts


def need_tools():
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg가 없습니다. 설치한 뒤 다시 실행하세요 (사용법은 이 파일 맨 위 설명).")
    try:
        import PIL  # noqa: F401
    except ImportError:
        sys.exit("pillow가 없습니다. 먼저 실행하세요:  pip install pillow")


def download_video(reel, video_dir):
    path = video_dir / f"{reel['shortCode']}.mp4"
    if path.exists() and path.stat().st_size > 0:
        return path
    url = reel.get("videoUrl")
    if not url:
        return None
    resp = requests.get(url, timeout=180)
    if resp.status_code != 200 or not resp.content:
        return None
    path.write_bytes(resp.content)
    return path


def detect_cuts(video, threshold, duration):
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(video),
         "-vf", f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
        capture_output=True, text=True, errors="replace").stderr
    cuts = []
    for t in (float(x) for x in re.findall(r"pts_time:([0-9.]+)", out)):
        if t < MIN_SHOT or (duration and t > duration - MIN_SHOT):
            continue
        if cuts and t - cuts[-1] < MIN_SHOT:
            continue
        cuts.append(round(t, 2))
    return cuts


def grab(video, t, dest):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video),
                    "-frames:v", "1", "-vf", f"scale={THUMB_W}:-2", str(dest)], check=False)
    return dest if dest.exists() else None


def contact_sheet(images, labels, dest, cols):
    from PIL import Image, ImageDraw
    tiles = [Image.open(p).convert("RGB") for p in images]
    if not tiles:
        return None
    w, h = tiles[0].size
    label_h = 22
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + label_h)), "white")
    draw = ImageDraw.Draw(sheet)
    for i, (tile, label) in enumerate(zip(tiles, labels)):
        x, y = (i % cols) * w, (i // cols) * (h + label_h)
        sheet.paste(tile.resize((w, h)), (x, y + label_h))
        draw.text((x + 6, y + 5), label, fill="black")
    sheet.save(dest, quality=85)
    return dest


def speech_overlap(cuts, segments):
    """전환이 말하는 도중에 일어났는지(말 위에 컷), 말 사이 쉼에서 일어났는지 센다."""
    on_speech = sum(1 for c in cuts if any(s["start"] < c < s["end"] for s in segments))
    return {"말하는 도중 전환": on_speech, "말 쉬는 틈 전환": len(cuts) - on_speech}


def process(reel, folder, opts, whisper):
    code = reel["shortCode"]
    video = download_video(reel, folder / "video")
    if not video:
        return None
    duration = reel.get("videoDuration") or 0
    out = folder / "frames" / code
    out.mkdir(parents=True, exist_ok=True)

    hook_imgs = [grab(video, t, out / f"hook_{t:.1f}.jpg") for t in HOOK_TIMES]
    contact_sheet([p for p in hook_imgs if p], [f"{t:.1f}s" for t, p in zip(HOOK_TIMES, hook_imgs) if p],
                  out / "hook.jpg", cols=7)

    cuts = detect_cuts(video, opts["threshold"], duration)
    starts = [0.0] + cuts
    cut_imgs = [grab(video, min(t + 0.15, max(duration - 0.1, 0)), out / f"cut_{t:.2f}.jpg") for t in starts]
    contact_sheet([p for p in cut_imgs if p], [f"{t:.1f}s" for t, p in zip(starts, cut_imgs) if p],
                  out / "cuts.jpg", cols=8)

    ends = cuts + [duration]
    shots = [round(e - s, 2) for s, e in zip(starts, ends)]
    w = (whisper or {}).get(code)
    info = {
        "code": code,
        "duration": duration,
        "cuts": cuts,
        "shot_count": len(starts),
        "avg_shot_sec": round(duration / len(starts), 2) if duration else None,
        "shots_sec": shots,
        "cuts_in_3s": sum(1 for c in cuts if c <= 3.0),
        "first_cut_sec": cuts[0] if cuts else None,
        "first_speech_sec": w["first_speech_sec"] if w else None,
        **(speech_overlap(cuts, w["segments"]) if w else {}),
    }
    (out / "scenes.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    for p in out.glob("hook_*.jpg"):
        p.unlink()
    for p in out.glob("cut_*.jpg"):
        p.unlink()
    return info


def md_block(rank, group, reel, info, whisper):
    code = reel["shortCode"]
    w = (whisper or {}).get(code)
    lines = [
        f"### {group} {rank}. {reel.get('url', '')}",
        "",
        f"- 조회수 {views(reel):,} · 길이 {info['duration']:.1f}초 · 장면 {info['shot_count']}개"
        f" · 장면당 평균 {info['avg_shot_sec']}초 · 3초 안 전환 {info['cuts_in_3s']}번"
        f" · 첫 전환 {info['first_cut_sec'] if info['first_cut_sec'] is not None else '없음'}초",
        f"- 첫 발화 {w['first_speech_sec'] if w and w['first_speech_sec'] is not None else '없음'}초"
        + (f" · 말하는 도중 전환 {info['말하는 도중 전환']}번 / 쉬는 틈 전환 {info['말 쉬는 틈 전환']}번" if w else ""),
        f"- 전환 시점(초): {', '.join(f'{c:.1f}' for c in info['cuts']) or '없음'}",
        f"- 초반 3초 사진: frames/{code}/hook.jpg",
        f"- 장면 전환 사진: frames/{code}/cuts.jpg",
        "",
    ]
    if w and w["segments"]:
        lines += ["```"] + [f"[{s['start']:5.1f}~{s['end']:5.1f}초] {s['text']}" for s in w["segments"]] + ["```", ""]
    return "\n".join(lines)


def main():
    folder, opts = parse_args(sys.argv[1:])
    need_tools()
    reels = json.loads((folder / "reels_raw.json").read_text(encoding="utf-8"))
    whisper_path = folder / "transcripts_whisper.json"
    whisper = json.loads(whisper_path.read_text(encoding="utf-8")) if whisper_path.exists() else None
    (folder / "video").mkdir(exist_ok=True)

    top, bottom = split_groups(reels, opts["groups"])
    groups = [("상위", top)] + ([] if opts["top_only"] else [("하위", bottom)])
    parts = ["# 영상 해부 입력", "",
             "기준: templates/영상해부기준.md. 사진을 보고 영상해부_결과.json 으로 저장.", ""]
    failed = []
    for name, rs in groups:
        parts += [f"## {name} 그룹", ""]
        for i, r in enumerate(rs, 1):
            info = process(r, folder, opts, whisper)
            if not info:
                failed.append(r["shortCode"])
                print(f"  {name} {i}. {r['shortCode']}  영상을 받지 못함 (링크 만료)")
                continue
            print(f"  {name} {i}. {r['shortCode']}  장면 {info['shot_count']}개 · 3초 안 전환 {info['cuts_in_3s']}번")
            parts.append(md_block(i, name, r, info, whisper))
    out = folder / "영상해부_입력.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"사진·전환 정보 저장 → {folder / 'frames'}\n입력 자료 → {out}")
    if failed:
        print(f"영상을 받지 못한 릴스: {', '.join(failed)} — fetch_reels.py를 다시 실행해 새 링크를 받으세요.")


if __name__ == "__main__":
    main()
