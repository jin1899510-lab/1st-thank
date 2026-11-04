"""제안서 PPTX 점검: 규칙 위반과 화면 문제를 찾는다.

사용법:
    python3 tools/check_pptx.py proposals/nekonomura/output/nekonomura-proposal.pptx

점검 항목:
    1. 금지 문구 (RULES.md 표현 규칙)
    2. 마지막 장의 가격이 앞 장에 나오는지 (다른 금액은 확인 목록으로만 보여 줌, '실비' 문구는 예외)
    3. 다른 고객 이름이 들어갔는지 (proposals/*/slides.md 제목에서 고객 이름을 읽음)
    4. 글자 없는 빈 도형(아이콘 자리 잔여물), 글자를 덮는 버튼 (젠스파크 내보내기에서 자주 생김)
    5. 남은 [확인 필요] 표시
문제가 있으면 종료 코드 1.
"""
import re
import sys
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

ROOT = Path(__file__).resolve().parent.parent
EMU = 914400

FORBIDDEN = {
    "브랜드 블로그": "'파워컨텐츠'로만 쓴다",
    "1건당": "'상담 1건당 비용'은 쓰지 않는다",
    "매일 바뀝": "입찰가는 매일 바뀌지 않는다",
    "매일 바뀌": "입찰가는 매일 바뀌지 않는다",
    "부가세": "원고에 없는 부가세 문구",
    "미노출": "광고 전 업체는 '세팅 예정'으로 쓴다",
    "설문": "설문지 내용은 넣지 않는다",
    "구글폼": "설문지 내용은 넣지 않는다",
}
MONEY = re.compile(r"\d[\d,]*\s*만\s*원|\d[\d,]*만원")
MONEY_OK = re.compile(r"실비|광고비|입찰|클릭당|CPC|추정")  # 같은 문단에 있으면 예외


def norm(amount):
    return re.sub(r"[\s,원]", "", amount)


def client_names(current):
    names = set()
    for md in (ROOT / "proposals").glob("*/slides.md"):
        m = re.match(r"#\s*(.+?)\s*[—-]", md.read_text(encoding="utf-8").splitlines()[0])
        if m:
            names.add(m.group(1).split()[0])
    return {n for n in names if n not in current}


def texts(slide):
    for sh in slide.shapes:
        if sh.has_text_frame:
            for p in sh.text_frame.paragraphs:
                yield sh, "".join(r.text for r in p.runs)
        if getattr(sh, "has_table", False) and sh.has_table:
            for row in sh.table.rows:
                for c in row.cells:
                    yield sh, c.text


def box(sh):
    return sh.left, sh.top, sh.left + sh.width, sh.top + sh.height


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def main(path):
    prs = Presentation(path)
    n = len(prs.slides)
    alltext = " ".join(t for s in prs.slides for _, t in texts(s))
    others = client_names(alltext[:300])
    problems, notes, money_notes = [], [], []
    last_prices = {norm(a) for _, t in texts(prs.slides[n - 1]) if not MONEY_OK.search(t) for a in MONEY.findall(t)}
    for i, s in enumerate(prs.slides, 1):
        for sh, t in texts(s):
            for w, why in FORBIDDEN.items():
                if w in t:
                    problems.append(f"{i}장: 금지 문구 '{w}' — {why}: {t[:60]}")
            for name in others:
                if name in t:
                    problems.append(f"{i}장: 다른 고객 이름 '{name}': {t[:60]}")
            if i < n and not MONEY_OK.search(t):
                for amt in MONEY.findall(t):
                    if norm(amt) in last_prices:
                        problems.append(f"{i}장: 마지막 장의 가격({amt})이 앞 장에 있음: {t[:60]}")
                    else:
                        money_notes.append(f"{i}장: 금액 '{amt}' — 우리 상품 가격이 아닌지 확인: {t[:50]}")
            if "확인 필요" in t:
                notes.append(f"{i}장: [확인 필요] 남아 있음: {t[:60]}")
        text_boxes = [sh for sh in s.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        for sh in s.shapes:
            if sh.shape_type != MSO_SHAPE_TYPE.AUTO_SHAPE or (sh.has_text_frame and sh.text_frame.text.strip()):
                continue
            w, h = sh.width / EMU, sh.height / EMU
            if sh.left >= prs.slide_width or sh.top >= prs.slide_height:
                notes.append(f"{i}장: 슬라이드 밖 도형(id {sh.shape_id}) — 지워도 됨")
                continue
            # 아이콘 자리 잔여물은 0.3–0.6in 정사각형에 가깝다 (막대그래프·장식 바는 제외)
            if not (0.3 <= w <= 0.6 and 0.3 <= h <= 0.6 and 0.7 <= w / h <= 1.4):
                continue
            b = box(sh)
            # 글자를 품은 배지(번호 원 등)는 정상: 글자 상자가 도형 안에 거의 들어가야 함
            if any(b[0] <= t.left + t.width / 2 <= b[2] and b[1] <= t.top + t.height / 2 <= b[3]
                   and t.width <= sh.width * 1.3 for t in text_boxes):
                continue
            near = [t for t in text_boxes if overlaps(b, box(t))]
            where = f" ('{near[0].text_frame.text[:20]}' 근처)" if near else ""
            problems.append(f"{i}장: 글자 없는 빈 도형(id {sh.shape_id}, {w:.2f}×{h:.2f}in){where} — 아이콘 자리 잔여물")
        # 버튼 위에 글자가 가려지는지 (도형이 글자보다 나중에 그려짐)
        tree = list(s.shapes._spTree)
        for sh in s.shapes:
            if sh.shape_type != MSO_SHAPE_TYPE.AUTO_SHAPE or (sh.has_text_frame and sh.text_frame.text.strip()):
                continue
            for t in text_boxes:
                c = (t.left + t.width / 2, t.top + t.height / 2)
                b = box(sh)
                if b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3] and sh.width < 3 * EMU \
                        and tree.index(sh._element) > tree.index(t._element):
                    problems.append(f"{i}장: 도형(id {sh.shape_id})이 글자 '{t.text_frame.text[:20]}'를 덮음")
    print(f"점검: {path} ({n}장)")
    for p in problems:
        print("  ✗", p)
    for p in notes + money_notes:
        print("  ·", p)
    print("  문제 없음" if not problems else f"  문제 {len(problems)}건")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
