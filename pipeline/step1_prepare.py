"""1단계: 영상 정보 확인, 음성 추출, 장면 확인용 사진 추출, (선택) 기본 보정.

사용 예:
  python step1_prepare.py --client 한방장어 --episode 01편 --video "D:/원본/20260923_141411.mp4"
  python step1_prepare.py --client 한방장어 --episode 01편 --video "..." --beauty
"""

import argparse
from pathlib import Path

from common import job_dir, load_config, probe, require_tool, run, write_json

FRAME_COUNT = 12  # 얼굴 위치·장면 확인용 사진 수

# 화면 전체에 거는 기본 보정: 피부결을 부드럽게(경계는 유지) + 살짝 밝고 화사하게
BEAUTY_FILTER = "bilateral=sigmaS=3:sigmaR=0.06,eq=brightness=0.03:saturation=1.06"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True, help="업체 이름 (예: 한방장어)")
    ap.add_argument("--episode", required=True, help="편 이름 (예: 01편)")
    ap.add_argument("--video", required=True, help="원본 영상 경로")
    ap.add_argument("--beauty", action="store_true", help="FFmpeg 기본 보정본을 만들어 편집에 사용 (시간이 오래 걸림)")
    args = ap.parse_args()

    cfg = load_config()
    ffmpeg = require_tool("ffmpeg")
    src = Path(args.video).resolve()
    if not src.exists():
        raise SystemExit(f"[오류] 영상을 찾을 수 없습니다: {src}")

    out = job_dir(cfg, args.client, args.episode)
    info = probe(src)
    print(f"[1/3] 영상 정보: {info['width']}x{info['height']}, {info['duration']:.1f}초")

    print("[2/3] 음성 추출 (Whisper 용 16kHz 모노)")
    run([ffmpeg, "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", out / "audio.wav"])

    print(f"[3/3] 장면 확인용 사진 {FRAME_COUNT}장 추출")
    frames = out / "frames"
    frames.mkdir(exist_ok=True)
    for i in range(FRAME_COUNT):
        t = info["duration"] * (i + 0.5) / FRAME_COUNT
        run([ffmpeg, "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", src, "-frames:v", "1",
             "-vf", "scale=640:-2", frames / f"frame_{i:02d}_{int(t):05d}s.jpg"])

    edit_video = src
    if args.beauty:
        edit_video = out / "retouched.mp4"
        print("[추가] 기본 보정본 생성 중... (CPU 인코딩이라 영상 길이보다 오래 걸릴 수 있음)")
        run([ffmpeg, "-y", "-v", "error", "-stats", "-i", src, "-vf", BEAUTY_FILTER,
             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-c:a", "copy", edit_video])

    write_json(out / "job.json", {
        "client": args.client,
        "episode": args.episode,
        "source": str(src),
        "edit_video": str(edit_video),
        "beauty": args.beauty,
        **info,
    })
    print(f"\n완료: {out}")


if __name__ == "__main__":
    main()
