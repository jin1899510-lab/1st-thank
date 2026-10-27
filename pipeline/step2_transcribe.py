"""2단계: Whisper 로 음성을 시간별 텍스트로 변환.

결과:
  transcript.json  문장(구간)별 시작/끝 시간과 단어별 시간
  transcript.txt   Claude 가 읽기 쉬운 "[시작-끝] 문장" 목록

사용 예:
  python step2_transcribe.py --client 한방장어 --episode 01편
"""

import argparse
import time
import wave

import numpy as np

from common import fmt_time, job_dir, load_config, write_json


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--model", help="config.json 의 whisper.model 대신 사용할 모델 (예: medium, small)")
    args = ap.parse_args()

    cfg = load_config()
    wcfg = cfg["whisper"]
    out = job_dir(cfg, args.client, args.episode)
    audio = out / "audio.wav"
    if not audio.exists():
        raise SystemExit("[오류] audio.wav 가 없습니다. step1_prepare.py 를 먼저 실행해 주세요.")

    from faster_whisper import WhisperModel  # 설치 확인을 실행 시점으로 미룸

    model_name = args.model or wcfg["model"]
    print(f"Whisper 모델 불러오는 중: {model_name} ({wcfg['device']}, {wcfg['compute_type']})")
    print("  처음 실행할 때는 모델을 내려받느라 몇 분 걸립니다.")
    model = WhisperModel(model_name, device=wcfg["device"], compute_type=wcfg["compute_type"])

    started = time.time()
    # 16kHz 모노 wav 를 직접 읽어서 넘김 (PyAV 버전 차이로 인한 오류 방지)
    with wave.open(str(audio), "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    samples = pcm.astype(np.float32) / 32768.0

    segments, info = model.transcribe(
        samples,
        language=wcfg.get("language", "ko"),
        word_timestamps=True,
        vad_filter=True,  # 말 없는 구간 건너뛰기
        vad_parameters={"min_silence_duration_ms": 500},
    )

    result, lines = [], []
    for seg in segments:  # 제너레이터라 여기서 실제 인식이 진행됨
        item = {
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
            "words": [{"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word}
                      for w in (seg.words or [])],
        }
        result.append(item)
        line = f"[{item['start']:.2f}-{item['end']:.2f}] {item['text']}"
        lines.append(line)
        print(f"  {fmt_time(seg.start)} / {fmt_time(info.duration)}  {item['text']}")

    write_json(out / "transcript.json", {"language": info.language, "duration": info.duration, "segments": result})
    (out / "transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n완료: 문장 {len(result)}개, {time.time() - started:.0f}초 걸림 → {out / 'transcript.txt'}")


if __name__ == "__main__":
    main()
