"""카드 JSON(cards/notice_<번호>.json)을 1080x1350 카드뉴스 이미지로 만든다.

사용법:
    python3 card_news.py cards/notice_1139.json

결과:
    output/cards/<번호>/card_01.png ...  카드 이미지
    output/cards/<번호>/index.html       전체 미리보기
"""
import html
import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT_DIR = Path(__file__).parent / "output" / "cards"
CHROMIUM = "/opt/pw-browsers/chromium"

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&display=swap');
* { margin: 0; box-sizing: border-box; }
body { background: #e9edf2; font-family: 'Noto Sans KR', 'WenQuanYi Zen Hei', sans-serif; }
.card { width: 1080px; height: 1350px; padding: 110px 96px; position: relative;
        display: flex; flex-direction: column; background: #fff; color: #111; overflow: hidden; }
.card + .card { margin-top: 40px; }
.page { position: absolute; right: 96px; bottom: 80px; font-size: 30px; color: #9aa3ad; font-weight: 700; }
.brand { position: absolute; left: 96px; bottom: 80px; font-size: 30px; color: #03c75a; font-weight: 900; }
.label { display: inline-block; align-self: flex-start; padding: 14px 30px; border-radius: 999px;
         background: #e6f9ee; color: #03a54b; font-size: 34px; font-weight: 700; }
h1 { font-size: 92px; line-height: 1.25; font-weight: 900; letter-spacing: -2px; white-space: pre-line; }
h2 { font-size: 76px; line-height: 1.3; font-weight: 900; letter-spacing: -1.5px; white-space: pre-line; margin-top: 56px; }
.body { margin-top: auto; margin-bottom: 120px; }
.body p { font-size: 42px; line-height: 1.5; padding: 30px 0; border-top: 3px solid #eef1f4; color: #333; }
.cover { background: #03c75a; color: #fff; justify-content: center; }
.cover .label { background: rgba(255,255,255,.2); color: #fff; margin-bottom: 64px; }
.cover .sub { margin-top: 56px; font-size: 40px; opacity: .9; }
.cover .brand, .cover .page { color: rgba(255,255,255,.85); }
ol { list-style: none; padding: 0; margin-top: auto; margin-bottom: 120px; counter-reset: n; }
ol li { counter-increment: n; display: flex; gap: 32px; align-items: center; padding: 34px 0;
        border-top: 3px solid #eef1f4; font-size: 42px; line-height: 1.45; white-space: pre-line; }
ol li::before { content: counter(n); flex: none; width: 76px; height: 76px; border-radius: 50%;
                background: #03c75a; color: #fff; font-weight: 900; font-size: 40px;
                display: flex; align-items: center; justify-content: center; }
.end { background: #111; color: #fff; justify-content: center; }
.end .url { margin-top: 64px; font-size: 34px; color: #03c75a; word-break: break-all; }
.end .note { margin-top: 40px; font-size: 36px; color: #aab2bb; }
"""


def esc(text: str) -> str:
    return html.escape(text)


def render_card(card: dict, page: str) -> str:
    kind = card["type"]
    foot = f'<div class="brand">플레이스 공지 브리핑</div><div class="page">{page}</div>'
    if kind == "cover":
        inner = (f'<div class="label">{esc(card["tag"])}</div><h1>{esc(card["title"])}</h1>'
                 f'<div class="sub">{esc(card.get("sub", ""))}</div>')
    elif kind == "point":
        rows = "".join(f"<p>{esc(b)}</p>" for b in card.get("body", []))
        inner = (f'<div class="label">{esc(card["label"])}</div><h2>{esc(card["title"])}</h2>'
                 f'<div class="body">{rows}</div>')
    elif kind == "list":
        items = "".join(f"<li>{esc(i)}</li>" for i in card["items"])
        inner = (f'<div class="label">{esc(card["label"])}</div><h2>{esc(card["title"])}</h2>'
                 f"<ol>{items}</ol>")
    elif kind == "end":
        inner = (f'<h1>{esc(card["title"])}</h1><div class="url">{esc(card["url"])}</div>'
                 '<div class="note">매일 아침 9시, 새 플레이스 공지를 핵심만 정리해 드려요</div>')
    else:
        raise ValueError(f"알 수 없는 카드 type: {kind}")
    return f'<section class="card {kind}">{inner}{foot}</section>'


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("사용법: python3 card_news.py cards/notice_<번호>.json")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cards = spec["cards"]
    total = len(cards)

    out = OUT_DIR / str(spec["id"])
    out.mkdir(parents=True, exist_ok=True)
    sections = "".join(render_card(c, f"{i}/{total}") for i, c in enumerate(cards, 1))
    page_html = (f'<!doctype html><html lang="ko"><head><meta charset="utf-8">'
                 f"<style>{CSS}</style></head><body>{sections}</body></html>")
    index = out / "index.html"
    index.write_text(page_html, encoding="utf-8")

    launch = {"executable_path": CHROMIUM} if os.path.exists(CHROMIUM) else {}
    with sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1080, "height": 1350})
        page.goto(index.as_uri())
        page.wait_for_load_state("networkidle")
        page.evaluate("document.fonts.ready")
        for i, el in enumerate(page.query_selector_all(".card"), 1):
            el.screenshot(path=str(out / f"card_{i:02d}.png"))
        browser.close()
    print(f"{total}장 저장: {out}")


if __name__ == "__main__":
    main()
