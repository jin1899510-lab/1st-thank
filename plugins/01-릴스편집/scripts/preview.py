"""편집 계획(plan.json)대로 저화질 미리보기 영상과 컷 스토리보드를 만든다 (캡컷 없이 흐름 확인용).

사용법:
    python3 preview.py <plan.json> <카드폴더> <출력폴더>

결과: 미리보기.mp4 (540×960, 자막 포함), 스토리보드.jpg (컷마다 가운데 한 장)
전환·영상 효과·자막 애니메이션은 캡컷에서만 보이므로 여기에는 없다.
media 의 "offset" 은 이 컴퓨터 사본과 원본의 시간 차이(초): 사본 시간 = 원본 시간 + offset.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

FONT = Path(__file__).resolve().parent.parent / "motion" / "public" / "fonts" / "NotoSansKR-900.ttf"


def run(args):
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def esc(s):
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cards, out = Path(sys.argv[2]), Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    parts, mids, t = [], [], 0.0
    for i, c in enumerate(plan["clips"]):
        dur = float(c["dur"])
        if "card" in c:
            src, ss, vol = cards / f"card_{c['card']}.mp4", 0.0, None
        else:
            m = plan["media"][c["src"]]
            src, ss, vol = m["local"], c["start"] + m.get("offset", 0.0), c.get("volume", 0.0)
        vf = "scale=540:960:force_original_aspect_ratio=increase,crop=540:960,fps=30,format=yuv420p"
        if c.get("zoom"):
            z0, z1 = c["zoom"]
            n = max(1, int(dur * 30))
            vf = (f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                  f"zoompan=z='{z0}+({z1}-{z0})*on/{n}':d=1:s=540x960:fps=30,format=yuv420p")
        audio = "[1:a]anull[a]" if vol is None else f"[0:a]volume={vol},aresample=44100,apad[a0];[a0][1:a]amix=inputs=2:duration=shortest[a]"
        part = tmp / f"p{i:03d}.mp4"
        run(["-ss", str(ss), "-t", str(dur), "-i", str(src), "-f", "lavfi", "-t", str(dur), "-i", "anullsrc=r=44100:cl=stereo",
             "-filter_complex", f"[0:v]{vf}[v];{audio}", "-map", "[v]", "-map", "[a]", "-t", str(dur),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-c:a", "aac", str(part)])
        parts.append(part)
        mids.append(t + dur / 2)
        t += dur
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    cat = tmp / "cat.mp4"
    run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(cat)])
    draws = [f"drawtext=fontfile={FONT}:text='{esc(x['text'])}':fontsize={int(x.get('size', 8) * 5.2)}:"
             f"fontcolor={x.get('color', '#ffffff').replace('#', '0x')}:borderw=3:bordercolor=black:"
             f"x=(w-text_w)/2:y={int(x.get('y', .5) * 960)}-text_h/2:enable='between(t,{x['start']},{x['end']})'"
             for x in plan.get("texts", [])]
    voiced = [n for n in plan.get("narration", []) if n.get("file") and Path(n["file"]).exists()]
    if voiced:  # 나레이션을 제자리에 얹는다
        args, mix = ["-i", str(cat)], []
        for k, n in enumerate(voiced, 1):
            args += ["-i", n["file"]]
            ms = int(float(n["start"]) * 1000)
            mix.append(f"[{k}:a]adelay={ms}|{ms},aresample=44100[n{k}]")
        labels = "".join(f"[n{k}]" for k in range(1, len(voiced) + 1))
        mixed = tmp / "mixed.mp4"
        run(args + ["-filter_complex", ";".join(mix) + f";[0:a]{labels}amix=inputs={len(voiced) + 1}:duration=first:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(mixed)])
        cat = mixed
    music = plan.get("music") or {}
    if music.get("file") and Path(music["file"]).exists():  # 배경음악: 말소리 구간은 줄인다 (build_capcut 과 같은 규칙)
        total = sum(float(c["dur"]) for c in plan["clips"])
        wins, t = [(float(n["start"]), float(n["end"])) for n in voiced], 0.0
        for c in plan["clips"]:
            if "card" not in c and float(c.get("volume", 0)) >= 0.9:
                wins.append((t, t + float(c["dur"])))
            t += float(c["dur"])
        vol, duck = float(music.get("volume", 0.5)), float(music.get("duck", 0.15))
        cond = "+".join(f"between(t,{a},{b})" for a, b in wins) or "0"
        fo = float(music.get("fade_out", 1.2))
        mixed = tmp / "music.mp4"
        run(["-i", str(cat), "-stream_loop", "-1", "-i", music["file"], "-filter_complex",
             f"[1:a]atrim=0:{total},volume='if({cond},{duck},{vol})':eval=frame,"
             f"afade=t=in:d={music.get('fade_in', 0.5)},afade=t=out:st={total - fo}:d={fo},aresample=44100[m];"
             "[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(mixed)])
        cat = mixed
    video = out / "미리보기.mp4"
    run(["-i", str(cat), "-vf", ",".join(draws) or "null", "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-c:a", "copy", str(video)])

    thumbs = []
    for k, m in enumerate(mids):
        p = tmp / f"s{k:03d}.jpg"
        run(["-ss", f"{m:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=180:-2", str(p)])
        thumbs.append((m, Image.open(p).copy()))
    w, h = thumbs[0][1].size
    cols = min(11, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * w, rows * (h + 20)), "white")
    d = ImageDraw.Draw(sheet)
    for k, (m, im) in enumerate(thumbs):
        x, y = (k % cols) * w, (k // cols) * (h + 20)
        sheet.paste(im, (x, y + 20))
        d.text((x + 4, y + 4), f"{k + 1}. {m:.1f}s" + (" card" if "card" in plan["clips"][k] else ""), fill="black")
    sheet.save(out / "스토리보드.jpg", quality=88)
    print(f"미리보기 {t:.1f}초 → {video}\n스토리보드 → {out / '스토리보드.jpg'}")


if __name__ == "__main__":
    main()
