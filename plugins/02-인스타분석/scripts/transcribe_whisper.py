"""릴스 음성을 내 컴퓨터에서 위스퍼(faster-whisper)로 받아쓴다. 몇 초에 무슨 말을 했는지까지 나온다.

사용법:
    python3 transcribe_whisper.py <결과폴더> [옵션]

    결과폴더  fetch_reels.py가 만든 폴더 (reels_raw.json이 있는 곳)

옵션:
    --groups N    조회수 상위 N개 + 하위 N개만 받아쓰기 (기본 10, 해부할 릴스만)
    --all         30개 전부 받아쓰기
    --model 이름  tiny / base / small / medium / large-v3 (기본 small)
                  클수록 정확하지만 느리다. 한국어는 small 이상 추천.
    --prompt 글   자주 틀리는 고유명사를 알려주기 (예: "성시경, 부캉이, 융캉찌에")
    --force       이미 받아쓴 릴스도 다시 받아쓰기

결과:
    audio/<코드>.mp4            릴스 음성 사본 (인스타 링크는 며칠 뒤 만료되므로 보관)
    transcripts_whisper.json    릴스별 받아쓰기 (구간별 시작·끝 초, 첫 발화 시점)
    → prepare_dissect.py가 자동으로 읽어서 해부_입력.md에 시간과 함께 넣는다.

무료로 동작한다 (OpenAI API 키 필요 없음). 처음 한 번만 설치:
    pip install faster-whisper
처음 실행할 때 모델 파일을 내려받는다 (small 약 0.5GB). 그다음부터는 인터넷 없이 돈다.
ffmpeg는 따로 설치하지 않아도 된다.
"""
import json
import sys
import time
from pathlib import Path

import requests

from prepare_dissect import split_groups

MODELS = ("tiny", "base", "small", "medium", "large-v3")


def parse_args(argv):
    opts = {"groups": 10, "all": False, "model": "small", "prompt": None, "force": False}
    rest = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--all", "--force"):
            opts[a[2:]] = True
        elif a in ("--groups", "--model", "--prompt") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 1
        else:
            rest.append(a)
        i += 1
    if not rest:
        sys.exit(__doc__)
    opts["groups"] = int(opts["groups"])
    if opts["model"] not in MODELS:
        sys.exit(f"--model 은 {', '.join(MODELS)} 중 하나여야 합니다.")
    return Path(rest[0]), opts


def load_model(name):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("위스퍼가 설치되어 있지 않습니다. 먼저 실행하세요:  pip install faster-whisper")
    print(f"위스퍼 모델({name}) 준비 중… 처음이면 모델을 내려받느라 몇 분 걸립니다.")
    return WhisperModel(name, device="cpu", compute_type="int8")


def download_audio(reel, audio_dir):
    """음성만 있는 audioUrl을 먼저 쓰고(작음), 없으면 videoUrl을 쓴다."""
    path = audio_dir / f"{reel['shortCode']}.mp4"
    if path.exists() and path.stat().st_size > 0:
        return path
    for key in ("audioUrl", "videoUrl"):
        url = reel.get(key)
        if not url:
            continue
        resp = requests.get(url, timeout=120)
        if resp.status_code == 200 and resp.content:
            path.write_bytes(resp.content)
            return path
    return None


def split_lines(words, max_secs=4.0, gap_secs=0.6):
    """위스퍼가 20초짜리 한 덩어리로 줄 때가 있어서, 단어 시간으로 문장·쉼 단위로 다시 자른다."""
    lines, cur = [], []
    for w in words:
        if cur and (w.start - cur[-1].end > gap_secs or w.end - cur[0].start > max_secs):
            lines.append(cur)
            cur = []
        cur.append(w)
        if w.word.strip()[-1] in ".?!":
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    return [
        {"start": round(ws[0].start, 1), "end": round(ws[-1].end, 1), "text": "".join(w.word for w in ws).strip()}
        for ws in lines
    ]


def transcribe(model, path, prompt):
    segments, info = model.transcribe(
        str(path),
        language="ko",
        vad_filter=True,  # 음악만 나오는 구간을 건너뛰어 첫 발화 시점이 정확해지고 헛말이 줄어든다
        word_timestamps=True,
        condition_on_previous_text=False,
        initial_prompt=prompt,
    )
    words = [w for s in segments for w in (s.words or []) if w.word.strip()]
    segs = split_lines(words)
    first = words[0].start if words else None
    return {
        "language": info.language,
        "duration": round(info.duration, 1),
        "first_speech_sec": round(first, 1) if first is not None else None,
        "text": " ".join(s["text"] for s in segs),
        "segments": segs,
    }


def main():
    folder, opts = parse_args(sys.argv[1:])
    reels = json.loads((folder / "reels_raw.json").read_text(encoding="utf-8"))
    if opts["all"]:
        targets = reels
    else:
        top, bottom = split_groups(reels, opts["groups"])
        targets = top + bottom

    out_path = folder / "transcripts_whisper.json"
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    todo = [r for r in targets if opts["force"] or r["shortCode"] not in done]
    if not todo:
        print(f"이미 모두 받아썼습니다 → {out_path} (다시 하려면 --force)")
        return

    audio_dir = folder / "audio"
    audio_dir.mkdir(exist_ok=True)
    model = load_model(opts["model"])

    failed = []
    for n, reel in enumerate(todo, 1):
        code = reel["shortCode"]
        path = download_audio(reel, audio_dir)
        if not path:
            failed.append(code)
            print(f"  [{n}/{len(todo)}] {code}  음성을 받지 못함 (링크 만료)")
            continue
        started = time.time()
        result = transcribe(model, path, opts["prompt"])
        result["model"] = opts["model"]
        done[code] = result
        # 한 개 끝날 때마다 저장해서, 중간에 끊겨도 다음 실행 때 이어서 한다
        out_path.write_text(json.dumps(done, ensure_ascii=False, indent=2), encoding="utf-8")
        first = result["first_speech_sec"]
        first_txt = f"첫 발화 {first:.1f}초" if first is not None else "말 없음"
        print(f"  [{n}/{len(todo)}] {code}  {first_txt}  ({time.time() - started:.0f}초 걸림)  {result['text'][:40]}")

    print(f"받아쓰기 {len(todo) - len(failed)}개 저장 → {out_path}")
    if failed:
        print(f"음성을 받지 못한 릴스 {len(failed)}개: {', '.join(failed)}")
        print("인스타 링크가 만료된 것입니다. fetch_reels.py를 다시 실행해 새 링크를 받은 뒤 이 스크립트를 다시 돌리세요.")


if __name__ == "__main__":
    main()
