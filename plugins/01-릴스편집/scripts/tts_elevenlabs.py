"""편집 계획(plan.json)의 나레이션 줄마다 일레븐랩스 목소리를 만들고, 칸 길이에 맞게 읽는 속도를 조절한다.

사용법:
    ELEVENLABS_API_KEY=... python3 tts_elevenlabs.py <plan.json> <출력폴더> [--voice 목소리ID]

plan.json:
    "voice": "목소리 ID" (없으면 --voice, 그것도 없으면 한국어 공개 목소리 사용량 1위)
    "narration": [{"id": "n1", "text": "읽을 문장", "start": 1.5, "end": 5.0}, ...]

하는 일:
  1. 속도 1.0으로 만들어 길이를 잰다.
  2. 칸(end - start)보다 길면 속도를 올려 다시 만든다 (일레븐랩스 허용 범위 0.7~1.2).
     칸보다 많이 짧으면 속도를 조금 내려 여유를 줄인다.
  3. 1.2배로도 넘치면 "원고 줄이기" 목록에 올린다 (파일은 만들되 끝이 잘릴 수 있음).
결과: <출력폴더>/voice_<id>.mp3, 그리고 plan.json 의 각 줄에 file·duration·speed 를 적는다.
키는 코드에 쓰지 않고 환경변수 ELEVENLABS_API_KEY 에서 읽는다.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

API = "https://api.elevenlabs.io/v1"
MODEL = "eleven_multilingual_v2"
DEFAULT_VOICE = "ZJCNdZEjYwkOElxugmW2"  # 2026-10 기준 한국어 공개 목소리 1년 사용량 1위 (Hyuk)
SPEED_MIN, SPEED_MAX = 0.7, 1.2
FILL = 0.92  # 칸의 92%까지 채우는 것을 목표로 (끝에 숨 쉴 틈)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    return float(out)


def speak(session, voice, text, speed, path):
    resp = session.post(f"{API}/text-to-speech/{voice}", params={"output_format": "mp3_44100_128"}, json={
        "text": text, "model_id": MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "speed": round(speed, 2)},
    }, timeout=120)
    if resp.status_code == 401:
        sys.exit("ELEVENLABS_API_KEY 가 올바르지 않습니다.")
    resp.raise_for_status()
    path.write_bytes(resp.content)
    return duration(path)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    voice = None
    if "--voice" in args:
        i = args.index("--voice")
        voice = args[i + 1]
        del args[i:i + 2]
    plan_path, out = Path(args[0]), Path(args[1])
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("환경변수 ELEVENLABS_API_KEY 가 없습니다.")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    voice = voice or plan.get("voice") or DEFAULT_VOICE
    out.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["xi-api-key"] = key

    too_long = []
    for line in plan.get("narration", []):
        slot = float(line["end"]) - float(line["start"])
        path = out / f"voice_{line['id']}.mp3"
        speed = 1.0
        dur = speak(session, voice, line["text"], speed, path)
        want = slot * FILL
        if dur > want or dur < want * 0.75:
            speed = min(SPEED_MAX, max(SPEED_MIN, speed * dur / want))
            dur = speak(session, voice, line["text"], speed, path)
        if dur > slot:
            too_long.append(f"{line['id']} ({dur:.1f}초 / 칸 {slot:.1f}초): {line['text']}")
        line.update({"file": str(path.resolve()), "duration": round(dur, 2), "speed": round(speed, 2)})
        print(f"  {line['id']}  속도 {speed:.2f}  {dur:.1f}초 / 칸 {slot:.1f}초  {line['text']}")
    plan["voice"] = voice
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    if too_long:
        print("1.2배로 읽어도 칸을 넘는 줄 (원고를 줄이거나 칸을 늘리세요):")
        for t in too_long:
            print("  -", t)


if __name__ == "__main__":
    main()
