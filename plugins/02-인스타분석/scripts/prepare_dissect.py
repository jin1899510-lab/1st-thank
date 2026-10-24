"""fetch_reels.py 결과(reels_raw.json)를 조회수 순으로 나눠 해부용 자료를 만든다.

사용법:
    python3 prepare_dissect.py <결과폴더> [그룹크기]

    결과폴더  fetch_reels.py가 만든 폴더 (reels_raw.json이 있는 곳)
    그룹크기  상위·하위 그룹 각각의 릴스 수 (기본 10)

결과:
    해부_입력.md  상위/하위 그룹별 릴스 정보(숫자, 캡션, 받아쓰기)
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


def reel_block(rank, r):
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
        "**받아쓰기:**",
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
    parts = [
        "# 해부 입력",
        "",
        f"전체 {len(reels)}개 중 조회수 상위 {len(top)}개 / 하위 {len(bottom)}개.",
        "기준: templates/해부기준.md. 결과는 같은 폴더의 해부_결과.json 으로 저장.",
        "",
        "## 상위 그룹",
        "",
    ]
    parts += [reel_block(i, r) for i, r in enumerate(top, 1)]
    parts += ["## 하위 그룹", ""]
    if bottom:
        parts += [reel_block(i, r) for i, r in enumerate(bottom, 1)]
    else:
        parts += [f"(없음 — 릴스가 {size}개 이하라 하위 그룹을 만들 수 없음)", ""]

    out = folder / "해부_입력.md"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"상위 {len(top)}개 / 하위 {len(bottom)}개 → {out}")


if __name__ == "__main__":
    main()
