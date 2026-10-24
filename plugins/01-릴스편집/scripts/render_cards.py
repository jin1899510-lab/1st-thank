"""편집 계획(plan.json)의 모션그래픽 카드를 Remotion으로 영상(mp4)으로 만든다.

사용법:
    python3 render_cards.py <plan.json> <출력폴더>

plan.json 의 "cards" 항목 하나 = 카드 영상 하나:
    {"id": "price", "kind": "price|list|counter|ending", "seconds": 1.4,
     "background": "배경으로 흐리게 깔 사진 경로", "accent": "#ff5a36",
     "eyebrow": "작은 머리글", "title": "큰 글자", "lines": ["줄1", "줄2"],
     "number": 50, "unit": "가지+"}

카드 배경은 흐리게 깔리므로 촬영 영상의 한 장면이면 충분하다.
같은 내용(속성이 모두 같은)의 카드는 다시 그리지 않고 저장해 둔 것을 쓴다.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

MOTION = Path(__file__).resolve().parent.parent / "motion"
FONTS = {
    "NotoSansKR-500.ttf": "https://fonts.gstatic.com/s/notosanskr/v40/PbyxFmXiEBPT4ITbgNA5Cgms3VYcOA-vvnIzztgyeLQ.ttf",
    "NotoSansKR-900.ttf": "https://fonts.gstatic.com/s/notosanskr/v40/PbyxFmXiEBPT4ITbgNA5Cgms3VYcOA-vvnIzzkM1eLQ.ttf",
}
CHROME_CANDIDATES = [
    "/opt/pw-browsers/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell",
]


def ensure_setup():
    if not (MOTION / "node_modules").exists():
        subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=MOTION, check=True, shell=sys.platform == "win32")
    fonts = MOTION / "public" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        if not (fonts / name).exists():
            import requests
            (fonts / name).write_bytes(requests.get(url, timeout=120).content)


def render(card, out_dir, cache_dir):
    bg_dir = MOTION / "public" / "bg"
    bg_dir.mkdir(parents=True, exist_ok=True)
    props = {k: v for k, v in card.items() if k not in ("id",)}
    if card.get("background"):
        src = Path(card["background"])
        dst = bg_dir / (hashlib.sha1(str(src).encode()).hexdigest()[:12] + src.suffix)
        shutil.copyfile(src, dst)
        props["background"] = "bg/" + dst.name
    code = b"".join(f.read_bytes() for f in sorted((MOTION / "src").glob("*")))  # 템플릿을 고치면 다시 그린다
    key = hashlib.sha1(json.dumps(props, sort_keys=True, ensure_ascii=False).encode() + code).hexdigest()[:16]
    cached = cache_dir / f"{key}.mp4"
    if not cached.exists():
        cmd = ["npx", "remotion", "render", "src/index.ts", "Card", str(cached), "--codec=h264", "--crf=20",
               "--props=" + json.dumps(props, ensure_ascii=False), "--log=error"]
        chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None)
        if chrome:
            cmd.append("--browser-executable=" + chrome)
        subprocess.run(cmd, cwd=MOTION, check=True, shell=sys.platform == "win32")
    out = out_dir / f"card_{card['id']}.mp4"
    shutil.copyfile(cached, out)
    return out


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    plan = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out_dir = Path(sys.argv[2])
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = MOTION / "out" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    ensure_setup()
    for card in plan.get("cards", []):
        path = render(card, out_dir, cache_dir)
        print(f"  카드 {card['id']} → {path.name}")


if __name__ == "__main__":
    main()
