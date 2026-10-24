"""fetch_reels.py 결과(reels_raw.json)를 조회수 순으로 나눠 해부용 자료를 만든다.

사용법:
    python3 prepare_dissect.py <결과폴더> [그룹크기]

    결과폴더  fetch_reels.py가 만든 폴더 (reels_raw.json이 있는 곳)
    그룹크기  상위·하위 그룹 각각의 릴스 수 (기본 10)

결과:
    해부_입력.md  상위/하위 그룹별 릴스 정보(숫자, 캡션, 받아쓰기)
                  transcribe_whisper.py를 먼저 돌렸으면 위스퍼 받아쓰기를 초 단위로 넣는다
                  → Claude가 templates/해부기준.md 대로 해부해 해부_결과.json 작성

하위 그룹까지 만들려면 fetch_reels.py로 그룹크기×2개 이상 가져와야 한다 (예: 30개).
"""
import json
import sys
from pathlib import Path


def views(r):
    return r.get("videoPlayCount") or r.get("videoViewCount") or 0


def transcript_text(r):
    t = r.get("transcript")
    if isinstance(t, list):
        return "\n".join(str(x.get("text", x)) if isinstance(x, dict) else str(x) for x in t)
    return t or ""


def split_groups(reels, size):
    ranked = sorted(reels, key=views, reverse=True)
    top = ranked[:size]
    bottom = ranked[size:][-size:]
    return top, bottom


def whisper_lines(w, duration):
    """위스퍼 결과를 [시작~끝초 | 전체의 %] 줄로 만든다."""
    if not w["segments"]:
        return ["(말 없음 — 위스퍼가 음성을 찾지 못함)"]
    total = duration or w.get("duration") or 0
    lines = []
    for s in w["segments"]:
        pct = f" | {s['start'] / total * 100:.0f}%" if total else ""
        lines.append(f"[{s['start']:5.1f}~{s['end']:5.1f}초{pct}] {s['text']}")
    return lines


def reel_block(rank, r, whisper=None):
    caption = (r.get("caption") or "").strip()
    first_line = caption.splitlines()[0] if caption else ""
    dur = f"{r['videoDuration']:.1f}" if isinstance(r.get("videoDuration"), (int, float)) else "불명"
    lines = [
        f"### {rank}. {r.get('url', '')}",
        "",
        "| 게시일 | 조회수 | 좋아요 | 댓글 | 공유 | 길이(초) |",
        "|---|---|---|---|---|---|",
        f"| {(r.get('timestamp') or '')[:10]} | {views(r):,} | {r.get('likesCount', '')} | "
        f"{r.get('commentsCount', '')} | {r.get('sharesCount', '불명')} | {dur} |",
        "",
        f"**캡션 첫 줄:** {first_line or '불명'}",
        "",
        "**캡션 전체:**",
        "```",
        caption or "(없음)",
        "```",
        "",
    ]
    w = (whisper or {}).get(r.get("shortCode"))
    if w:
        first = w["first_speech_sec"]
        lines += [
            f"**첫 발화:** {f'{first:.1f}초' if first is not None else '없음'}"
            f" ({'3초 안' if first is not None and first <= 3 else '3초 밖 또는 말 없음'})",
            "",
            "**받아쓰기 (위스퍼, 초 단위):**",
            "```",
            *whisper_lines(w, r.get("videoDuration")),
            "```",
            "",
            "**받아쓰기 (Apify, 참고):**",
        ]
    else:
        lines += ["**받아쓰기:**"]
    lines += [
        "```",
        transcript_text(r) or "(없음 — fetch_reels.py --transcript 로 다시 가져오면 생김)",
        "```",
        "",
    ]
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    folder = Path(sys.argv[1])
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    reels = json.loads((folder / "reels_raw.json").read_text(encoding="utf-8"))

    top, bottom = split_groups(reels, size)
    whisper_path = folder / "transcripts_whisper.json"
    whisper = json.loads(whisper_path.read_text(encoding="utf-8")) if whisper_path.exists() else None
    parts = [
        "# 해부 입력",
        "",
        f"전체 {len(reels)}개 중 조회수 상위 {len(top)}개 / 하위 {len(bottom)}개.",
        "기준: templates/해부기준.md. 결과는 같은 폴더의 해부_결과.json 으로 저장.",
        "받아쓰기: " + ("위스퍼(초 단위) + Apify(참고)" if whisper else
                     "Apify만 (시간 없음 — transcribe_whisper.py를 돌리면 초 단위로 들어감)"),
        "",
        "## 상위 그룹",
        "",
    ]
    parts += [reel_block(i, r, whisper) for i, r in enumerate(top, 1)]
    parts += ["## 하위 그룹", ""]
    if bottom:
        parts += [reel_block(i, r, whisper) for i, r in enumerate(bottom, 1)]
    else:
        parts += [f"(없음 — 릴스가 {size}개 이하라 하위 그룹을 만들 수 없음)", ""]

    out = folder / "해부_입력.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"상위 {len(top)}개 / 하위 {len(bottom)}개 → {out}")


if __name__ == "__main__":
    main()
