"""대표님 PC 브라우저(ego-browser)로 수집하는 자료. 클라우드에서 막히는 것들을 여기서 모은다.

사용법 (저장 위치: proposals/<slug>/data/):
    python tools/browser_collect.py trends --slug song-law \
        --keywords "노란봉투법,중대재해처벌법,기술유출,공직선거법" \
        [--naver-groups "노란봉투법:노란봉투법,노란봉투법 시행;중대재해처벌법:중대재해처벌법,중대재해"]
        → trend_google_timeline.csv, trend_google_region.csv, trend_google_related.md,
          trend_naver_datalab.xlsx/.csv, trend_naver_conditions.md, trend_summary.md

    python tools/browser_collect.py adlog --slug song-law --keywords "중대재해 변호사,노동 변호사" [--out adlog_keyword_bids.json]
        → 애드로그 파워링크 입찰가 분석(월간 검색수·클릭·경쟁·순위별 입찰가). 브라우저에 애드로그 로그인 필요.

    python tools/browser_collect.py pc-candidates --slug song-law --middle 법률 \
        --pattern "중대재해|노동|배임|기술유출|개인정보" [--exclude "이혼|상속"]
        → powercontents_candidates.json (구매 가능 목록에서 고른 후보, 브라우저 안 씀)

    python tools/browser_collect.py powercontents --slug song-law --keywords "기술유출,경업금지" [--out naver_powercontents_purchasable.json]
        → 네이버 모바일 '브랜드 콘텐츠'(파워컨텐츠) 광고주 + 구매 가능 목록 여부

    python tools/browser_collect.py capture --slug song-law --keywords "중대재해 변호사,기술유출" [--url https://...]
        → data/capture/ 에 네이버 모바일 검색 화면(또는 URL) 캡처 PNG

    python tools/browser_collect.py competitors --slug nekonomura --keywords "장산역 초밥,해운대 초밥" [--place-ids "123,456"]
        → competitor_ads.json, competitor_events.md: 키워드별 파워링크 광고 문구(혜택 단어 표시),
          경쟁 매장 플레이스 쿠폰·편의·소식(이벤트·할인 표시). --place-ids 없으면 ranks.json 상위 매장

    python tools/browser_collect.py place-analysis --slug nekonomura --place-id 1573719918 [--competitor-ids "123,456"] [--top 5]
        → place_analysis.json / .md: 우리·경쟁 매장의 애드로그 종합분석(키워드 순위)·히든 키워드·최근 방문자 리뷰,
          네이버 리뷰 '이런 점이 좋았어요'·메뉴·특징 언급 수. 경쟁 매장은 ranks.json 상위에서 자동 (애드로그 로그인 필요)

    python tools/browser_collect.py all --slug song-law --trend-keywords "..." --keywords "..."
        → trends + adlog + powercontents 를 한 번에 (pc-candidates 결과가 있으면 그 키워드도 포함)

- 수치는 조회한 그대로 저장하고 추정하지 않는다. 트렌드 수치는 기간 최고점 = 100 비교 값이다.
- 파워컨텐츠 구매 가능 목록: tools/data/powercontents_keywords_*.csv 중 가장 최근 파일.
"""
import argparse
import collections
import csv
import json
import re
import statistics as st
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"


def data_dir(slug):
    d = ROOT / "proposals" / slug / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def js_path(p):
    return str(p).replace("\\", "/")


def run_ego(script, timeout=900):
    """ego-browser nodejs 로 스크립트를 실행하고, 스크립트가 파일로 남긴 결과 JSON을 돌려준다."""
    import tempfile
    import uuid
    rp = str(Path(tempfile.gettempdir()) / f"ego_result_{uuid.uuid4().hex}.json")
    script = script.replace("__RESULT_PATH__", js_path(rp))
    r = subprocess.run(["ego-browser", "nodejs"], input=script.encode("utf-8"),
                       capture_output=True, timeout=timeout)
    if Path(rp).exists():
        res = json.loads(Path(rp).read_text(encoding="utf-8"))
        Path(rp).unlink()
        return res
    out = r.stdout.decode("utf-8", "replace")
    err = r.stderr.decode("utf-8", "replace")
    raise RuntimeError(f"ego-browser 실행 실패 (code {r.returncode})\n{out[-2000:]}\n{err[-2000:]}")


def ego_script(space, body):
    """한 번 쓰고 닫는 TaskSpace 안에서 body 를 실행. body 는 result 변수에 결과를 담는다."""
    return f"""
const task = await taskSpace({json.dumps(space)});
const page = task.page("p1");
let result = null;
try {{
{body}
}} finally {{
  await task.finish({{ keep: [] }});
}}
const fs = await import("node:fs/promises");
await fs.writeFile("__RESULT_PATH__", JSON.stringify(result), "utf8");
console.log("done");
"""


def split_kw(s):
    return [k.strip() for k in (s or "").split(",") if k.strip()]


def latest_pc_list():
    files = sorted((TOOLS / "data").glob("powercontents_keywords_*.csv"))
    if not files:
        return None, {}
    f = files[-1]
    rows = {r["키워드"]: r for r in csv.DictReader(open(f, encoding="utf-8-sig"))}
    return f, rows


# ---------------------------------------------------------------- trends
def trends(slug, keywords, naver_groups=None):
    d = data_dir(slug)
    today = date.today().isoformat()
    kws = keywords[:5]
    groups = []
    if naver_groups:
        for g in naver_groups.split(";"):
            name, _, subs = g.partition(":")
            groups.append([name.strip(), subs.strip() or name.strip()])
    else:
        groups = [[k, k] for k in kws]
    groups = groups[:5]
    body = f"""
const D = {json.dumps(js_path(d) + "/")};
const kws = {json.dumps(kws, ensure_ascii=False)};
const groups = {json.dumps(groups, ensure_ascii=False)};
result = {{ google: {{}}, naver: {{}} }};
// 구글 트렌드: 대한민국 · 지난 12개월 · 주간
await page.goto("https://trends.google.com/trends/explore?date=today%2012-m&geo=KR&hl=ko&q=" + encodeURIComponent(kws.join(",")), {{ timeout: 60000 }});
await page.waitForSelector("css=button.widget-actions-item.export >> nth=0", {{ timeout: 30000 }});
await page.waitForTimeout(3000);
const dl = async (i, name) => {{
  const w = page.waitForEvent("download", {{ timeout: 30000 }});
  await page.click(`css=button.widget-actions-item.export >> nth=${{i}}`, {{ label: "download trends CSV" }});
  const f = await w; await f.saveAs(D + name); return name;
}};
result.google.timeline = await dl(0, "trend_google_timeline.csv");
result.google.region = await dl(1, "trend_google_region.csv");
for (let i = 0; i < 10; i++) {{ await page.mouse.move(600, 500); await page.mouse.wheel(0, 500); }}
await page.waitForTimeout(2500);
result.google.widgets = await page.evaluate(() => [...document.querySelectorAll("widget, trends-widget")].map(w => w.innerText));
// 네이버 데이터랩: 1년 · 주간 · 전체(기기·성별·연령 선택 안 함 = 전체)
await page.goto("https://datalab.naver.com/keyword/trendSearch.naver", {{ timeout: 60000 }});
await page.waitForSelector("css=input[placeholder='주제어 1 입력']", {{ timeout: 30000 }});
for (let i = 0; i < groups.length; i++) {{
  await page.fill(`css=input[placeholder='주제어 ${{i+1}} 입력']`, groups[i][0]);
  await page.evaluate(([i, v]) => {{
    const box = document.querySelectorAll("input[placeholder^='주제어 " + (i+1) + "에 해당하는']")[0];
    box.value = v; box.dispatchEvent(new Event("input", {{ bubbles: true }})); box.dispatchEvent(new Event("change", {{ bubbles: true }}));
  }}, [i, groups[i][1]]);
}}
await page.click("text=1년 >> nth=0", {{ label: "select 1 year" }});
await page.click("#timeDimensionTitle", {{ label: "open interval menu" }});
await page.waitForTimeout(400);
await page.click("css=li._item_week > a", {{ label: "choose weekly" }});
await page.click("text=네이버 검색 데이터 조회", {{ label: "run DataLab query" }});
await page.waitForURL(/trendResult/, {{ timeout: 30000 }});
await page.waitForTimeout(3000);
result.naver.url = await page.url();
const w2 = page.waitForEvent("download", {{ timeout: 30000 }});
await page.click("text=다운로드 >> nth=0", {{ label: "download DataLab excel" }});
const f2 = await w2; await f2.saveAs(D + "trend_naver_datalab.xlsx");
result.naver.xlsx = "trend_naver_datalab.xlsx";
"""
    res = run_ego(ego_script(f"collect {slug} trends", body))

    # 구글 관련 검색어
    related, cur = {}, None
    for t in res["google"]["widgets"]:
        s = t.strip()
        if s in kws:
            cur = s
            continue
        if cur and s.startswith("관련 검색어") and cur not in related:
            lines = [x.strip() for x in s.splitlines() if x.strip()]
            items = []
            for i in range(len(lines) - 2):
                if lines[i].isdigit() and (lines[i + 2].startswith("+") or lines[i + 2] in ("급등", "Breakout")):
                    items.append(f"{lines[i + 1]} {lines[i + 2]}")
            related[cur] = items
    # 구글 지역
    reg = list(csv.reader(open(d / "trend_google_region.csv", encoding="utf-8")))
    reg_rows = [r for r in reg[3:] if len(r) > 1]
    # 네이버 엑셀 → CSV
    import openpyxl
    import warnings
    warnings.filterwarnings("ignore")
    xr = list(openpyxl.load_workbook(d / "trend_naver_datalab.xlsx").active.iter_rows(values_only=True))
    hdr_i = next(i for i, r in enumerate(xr) if r and r[0] == "날짜")
    names = [xr[hdr_i][i] for i in range(1, len(xr[hdr_i]), 2) if xr[hdr_i][i]]
    nrows = [r for r in xr[hdr_i + 1:] if r and r[0]]
    with open(d / "trend_naver_datalab.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["주(시작일)"] + names)
        for r in nrows:
            w.writerow([r[0]] + [round(float(r[1 + 2 * j]), 2) for j in range(len(names))])
    period = xr[3][1] if len(xr) > 3 else ""

    # 요약 (최고점 주, 1년 전 4주 → 최근 4주)
    g = list(csv.reader(open(d / "trend_google_timeline.csv", encoding="utf-8")))
    ghdr_i = next(i for i, r in enumerate(g) if r and r[0] in ("주", "Week"))
    gh = g[ghdr_i]
    grows = [r for r in g[ghdr_i + 1:] if len(r) == len(gh)]

    def stat(vals, dates):
        v = [float(str(x).replace("<1", "0.5")) for x in vals]
        mx = max(v)
        f4, l4 = st.mean(v[:4]), st.mean(v[-4:])
        ch = f"{round((l4 - f4) / f4 * 100)}%" if f4 else "-"
        top = sorted(zip(v, dates), reverse=True)[:3]
        return {"avg": round(st.mean(v), 2), "max": mx, "peak_weeks": [f"{dt} {round(x, 1)}" for x, dt in top],
                "first4": round(f4, 2), "last4": round(l4, 2), "change": ch}

    summ = {"google": {}, "naver": {}}
    for j, h in enumerate(gh[1:], 1):
        summ["google"][h.split(":")[0]] = stat([r[j] for r in grows], [r[0] for r in grows])
    for j, n in enumerate(names):
        summ["naver"][n] = stat([r[1 + 2 * j] for r in nrows], [r[0] for r in nrows])

    md = [f"# 검색 트렌드 요약 ({today}, ego-browser 조회)", "",
          "- 수치는 기간 최고점 = 100으로 둔 비교 값 (실제 검색 횟수 아님)",
          f"- 구글: 대한민국 · 지난 12개월 · 주간 ({grows[0][0]} ~ {grows[-1][0]}) — `trend_google_timeline.csv`",
          f"- 네이버 데이터랩: {period} · 전체 기기·성별·연령 — `trend_naver_datalab.csv`", "",
          "| 서비스 | 검색어 | 1년 평균 | 많이 찾은 주 (상위 3) | 1년 전 4주 → 최근 4주 | 변화율 |", "|---|---|---|---|---|---|"]
    for svc, label in (("google", "구글"), ("naver", "네이버")):
        for k, s in summ[svc].items():
            md.append(f"| {label} | {k} | {s['avg']} | {', '.join(s['peak_weeks'])} | {s['first4']} → {s['last4']} | {s['change']} |")
    md += ["", "## 구글 관련 검색어 (급상승)"]
    for k in kws:
        md.append(f"- {k}: " + (", ".join(related.get(k, [])) or "없음"))
    md += ["", "## 구글 지역 (검색어별 비율, 상위 5)", "| 지역 | " + " | ".join(h.split(":")[0] for h in reg[2][1:]) + " |",
           "|---" * len(reg[2]) + "|"]
    for r in sorted(reg_rows, key=lambda r: -int((r[1] or "0").rstrip("%") or 0))[:5]:
        md.append("| " + " | ".join(r) + " |")
    md += ["", "- 지역 비율은 그 지역 안에서 비교 검색어끼리 나눈 비율이며 실제 검색량 크기가 아니다."]
    (d / "trend_summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (d / "trend_google_related.md").write_text(
        "# 구글 트렌드 관련 검색어(급상승)\n\n" + "\n".join(f"- {k}: " + ", ".join(v) for k, v in related.items()) + "\n",
        encoding="utf-8")
    cond = [f"# 네이버 데이터랩 조회 조건 ({today}, ego-browser)", "", f"- 결과 URL: {res['naver']['url']}",
            f"- 기간: {period}, 범위·성별·연령: 전체", "- 주제어와 하위 검색어:"]
    cond += [f"  - {n}: {s}" for n, s in groups]
    (d / "trend_naver_conditions.md").write_text("\n".join(cond) + "\n", encoding="utf-8")
    print(f"트렌드 저장: {d}/trend_summary.md 외 6개")
    return summ


# ---------------------------------------------------------------- adlog
def adlog(slug, keywords, out_name="adlog_keyword_bids.json"):
    d = data_dir(slug)
    body = f"""
const kws = {json.dumps([k.replace(" ", "") for k in keywords], ensure_ascii=False)};
await page.goto("https://www.adlog.kr/adlog/naver_keyword_bid.php", {{ timeout: 60000 }});
const logged = (await page.evaluate(() => document.body.innerText)).includes("로그아웃");
if (!logged) {{ result = {{ error: "애드로그 로그인이 필요합니다. 에고라이트 브라우저에서 adlog.kr 에 로그인한 뒤 다시 실행하세요." }}; }}
else {{
  const bad = [];
  for (const kw of kws) {{
    const body = new URLSearchParams({{ api_section: "11", api_type: "40", group_no: "0", keyword: kw, keyword2: "", ad_bid: "10" }}).toString();
    const r = await page.fetch("/adlog/ajax_search.php", {{ method: "POST", headers: {{ "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "x-requested-with": "XMLHttpRequest" }}, body, timeout: 60000 }});
    if (!String(r.body).includes('"0000"')) bad.push(kw);
    await page.waitForTimeout(1300);
  }}
  await page.goto("https://www.adlog.kr/adlog/naver_keyword_bid.php", {{ timeout: 60000 }});
  const rows = await page.evaluate(() => [...document.querySelector("table").querySelectorAll("tr")].map(tr => [...tr.querySelectorAll("th,td")].map(c => c.innerText.trim().replace(/\\s+/g, " "))));
  const want = new Set(kws); const out = {{}};
  for (const r of rows.slice(1)) if (r.length > 17 && want.has(r[1]) && !out[r[1]]) out[r[1]] = Object.fromEntries(rows[0].slice(1, 18).map((h, i) => [h, r[i + 1]]));
  result = {{ rows: kws.filter(k => out[k]).map(k => out[k]), missing: kws.filter(k => !out[k]), bad }};
}}
"""
    res = run_ego(ego_script(f"collect {slug} adlog", body), timeout=60 + 5 * len(keywords))
    if res.get("error"):
        sys.exit(res["error"])
    obj = {"source": f"애드로그 파워링크 입찰가 분석 (naver_keyword_bid.php), {date.today().isoformat()} ego-browser 조회. "
                     "검색수=네이버 검색광고 월간 검색수('< 10'은 10회 미만), 입찰가=파워링크 순위별 예상 입찰가",
           "rows": res["rows"], "missing": res["missing"]}
    (d / out_name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"애드로그 {len(res['rows'])}개 저장: {d / out_name}" + (f" (못 받은 키워드: {', '.join(res['missing'])})" if res["missing"] else ""))
    return obj


# ---------------------------------------------------------------- powercontents
def pc_candidates(slug, middle, pattern, exclude=None):
    f, rows = latest_pc_list()
    if not rows:
        sys.exit("tools/data/powercontents_keywords_*.csv 가 없습니다. 대표님께 최신 구매 가능 목록 엑셀을 받으세요.")
    pat, exc = re.compile(pattern), re.compile(exclude) if exclude else None
    hits = [r for r in rows.values() if (not middle or r["중분류"] == middle or r["대분류"] == middle)
            and pat.search(r["키워드"]) and not (exc and exc.search(r["키워드"]))]
    obj = {"list_file": f.name, "middle": middle, "pattern": pattern, "exclude": exclude,
           "keywords": [{"키워드": r["키워드"], "대분류": r["대분류"], "중분류": r["중분류"],
                         "구매가능일": r["구매가능일"], "기존/신규": r["기존/신규"], "비고": r["비고"]} for r in hits]}
    out = data_dir(slug) / "powercontents_candidates.json"
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"구매 가능 후보 {len(hits)}개 ({f.name}): {out}")
    return [r["키워드"] for r in hits]


def powercontents(slug, keywords, out_name="naver_powercontents_purchasable.json"):
    f, rows = latest_pc_list()
    body = f"""
const kws = {json.dumps(keywords, ensure_ascii=False)};
result = {{}};
for (const kw of kws) {{
  await page.goto("https://m.search.naver.com/search.naver?query=" + encodeURIComponent(kw), {{ timeout: 60000 }});
  await page.waitForTimeout(1500);
  const t = await page.evaluate(() => document.body.innerText);
  const i = t.indexOf("브랜드 콘텐츠\\n");
  if (i < 0) {{ result[kw] = null; continue; }}
  const j = t.indexOf("브랜드 콘텐츠\\n더보기", i + 5);
  const lines = t.slice(i + 8, j > 0 ? j : i + 3000).split("\\n").map(s => s.trim()).filter(Boolean);
  const ads = []; for (let k = 1; k < lines.length; k++) if (/^\\d{{4}}\\.\\d{{2}}\\.\\d{{2}}\\.$/.test(lines[k])) ads.push({{ advertiser: lines[k - 1], date: lines[k], title: (lines[k + 1] || "").slice(0, 60) }});
  result[kw] = ads;
  await page.waitForTimeout(800);
}}
"""
    res = run_ego(ego_script(f"collect {slug} powercontents", body), timeout=60 + 8 * len(keywords))
    obj = {"collected": date.today().isoformat(),
           "note": "네이버 모바일 통합검색 '브랜드 콘텐츠'(파워컨텐츠) 영역. null = 영역 없음. purchasable = 구매 가능 목록에 있음(띄어쓰기 빼고 대조)",
           "list_file": f.name if f else None,
           "keywords": {k: {"purchasable": (k.replace(" ", "") in rows) if rows else None, "ads": v} for k, v in res.items()}}
    out = data_dir(slug) / out_name
    out.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in obj["keywords"].items():
        ads = v["ads"]
        print(f"  {k} [{'구매가능' if v['purchasable'] else '구매불가' if v['purchasable'] is False else '?'}] "
              + ("광고 없음" if not ads else ", ".join(a["advertiser"] for a in ads)))
    print(f"저장: {out}")
    return obj


# ---------------------------------------------------------------- capture
def capture(slug, keywords, urls=None):
    d = data_dir(slug) / "capture"
    d.mkdir(exist_ok=True)
    targets = [(k, "https://m.search.naver.com/search.naver?query=" + k) for k in keywords] + [(u, u) for u in (urls or [])]
    names = [re.sub(r"[^\w가-힣]+", "_", n)[:40] for n, _ in targets]
    body = f"""
const targets = {json.dumps([[n, u] for n, (_, u) in zip(names, targets)], ensure_ascii=False)};
const D = {json.dumps(js_path(d) + "/")};
result = [];
// 휴대폰 화면 크기로 찍는다 (대표님 휴대폰에서 보는 모양)
await page.cdp("Emulation.setDeviceMetricsOverride", {{ width: 390, height: 844, deviceScaleFactor: 2, mobile: true }});
for (const [n, u] of targets) {{
  await page.goto(u, {{ timeout: 60000 }});
  await page.waitForTimeout(2000);
  result.push(await page.screenshot({{ path: D + n + ".png" }}));
}}
"""
    res = run_ego(ego_script(f"collect {slug} capture", body), timeout=60 + 15 * len(targets))
    print("캡처 저장:\n  " + "\n  ".join(res))
    return res


# ---------------------------------------------------------------- competitors (광고·이벤트)
TABS = {"홈", "소식", "메뉴", "예약", "리뷰", "사진", "지도", "주변", "정보", "쿠폰", "알림받기"}
OFFER = re.compile(r"쿠폰|할인|이벤트|무료|증정|사은품|적립|\d+ ?%|첫 ?방문|첫 ?상담|예약|톡톡|리뷰|1\+1|특가|혜택|선착순|체험|당일|24시|야간|주말|공휴일|단체|포장|배달|경로|학생|생일|신메뉴|시즌|한정")

COMPETITOR_JS = r"""
const kws = __KWS__;
const ids = __IDS__;
result = { ads: {}, places: {} };
for (const kw of kws) {
  await page.goto("https://m.search.naver.com/search.naver?query=" + encodeURIComponent(kw), { timeout: 60000 });
  await page.waitForTimeout(1500);
  result.ads[kw] = await page.evaluate(() => {
    const boxes = []; const seen = new Set();
    for (const a of document.querySelectorAll('a[href*="ader.naver.com"]')) {
      const box = a.closest("li") || a.parentElement; if (!box || seen.has(box)) continue; seen.add(box);
      boxes.push(box.innerText.replace(/\n+/g, " | ").slice(0, 500));
    }
    const t = document.body.innerText; const i = t.indexOf("브랜드 콘텐츠\n");
    const pc = i < 0 ? null : t.slice(i + 8, i + 1200).split("\n브랜드 콘텐츠\n더보기")[0];
    return { powerlink: boxes.slice(0, 8), powercontents: pc };
  });
  await page.waitForTimeout(700);
}
for (const id of ids) {
  const r = {};
  await page.goto("https://m.place.naver.com/place/" + id + "/home", { timeout: 60000 });
  await page.waitForTimeout(2000);
  r.home = await page.evaluate(() => document.body.innerText.slice(0, 6000));
  await page.goto("https://m.place.naver.com/place/" + id + "/feed", { timeout: 60000 });
  await page.waitForTimeout(2000);
  r.feed = await page.evaluate(() => document.body.innerText.slice(0, 8000));
  result.places[id] = r;
  await page.waitForTimeout(700);
}
"""


def competitors(slug, keywords, place_ids, top_n=8):
    """경쟁사가 어떻게 광고하고, 어떤 쿠폰·이벤트·소식으로 손님을 끌어오는지 모은다."""
    d = data_dir(slug)
    ids = list(place_ids or [])
    if not ids and (d / "ranks.json").exists():
        own = None
        if (d / "place.json").exists():
            own = json.loads((d / "place.json").read_text(encoding="utf-8")).get("id")
        for v in json.loads((d / "ranks.json").read_text(encoding="utf-8")).values():
            for t in v.get("top", [])[:top_n]:
                if t["id"] != own and t["id"] not in ids:
                    ids.append(t["id"])
        ids = ids[:top_n * 2]
    body = COMPETITOR_JS.replace("__KWS__", json.dumps(keywords, ensure_ascii=False)).replace("__IDS__", json.dumps(ids))
    res = run_ego(ego_script(f"collect {slug} competitors", body),
                  timeout=120 + 10 * len(keywords) + 15 * len(ids))
    places = {}
    for pid, r in res["places"].items():
        home = [x.strip() for x in r["home"].splitlines()]
        name = home[1] if len(home) > 1 else pid
        coupons = []
        if "쿠폰" in home:
            i = home.index("쿠폰")
            for line in home[i + 1:i + 12]:
                if line in ("주소", "다운로드"):
                    break
                if line and line not in TABS:
                    coupons.append(line)
        conv = next((home[i + 1] for i, l in enumerate(home) if l == "편의" and i + 1 < len(home)), "")
        feed = [x.strip() for x in r["feed"].splitlines()]
        posts, cur = [], []
        start = feed.index("정보") + 1 if "정보" in feed else 0
        for line in feed[start:]:
            if re.fullmatch(r"\d{4}\.\d{2}\.\d{2}\.", line):
                lines = [x for x in cur if x and x != name and not re.fullmatch(r"좋아요|\d+명|더보기|전체|공지|이벤트|알림", x)]
                if lines:
                    title = re.sub(r"^(알림|이벤트|NEW\(new\)|NEW|쿠폰)", "", lines[0])
                    text = " ".join(lines)[:200]
                    posts.append({"date": line, "title": title, "offer": bool(OFFER.search(text)), "text": text})
                cur = []
            elif not re.fullmatch(r"\d{4}년 \d{1,2}월 \d{1,2}일", line):
                cur.append(line)
        places[pid] = {"name": name, "coupons": coupons, "convenience": conv,
                       "posts": posts[:12], "offer_posts": [p for p in posts if p["offer"]][:8]}
    ads = {}
    for kw, a in res["ads"].items():
        ads[kw] = {"powerlink": [{"text": t, "offers": sorted(set(OFFER.findall(t)))} for t in a["powerlink"]],
                   "powercontents": a["powercontents"]}
    obj = {"collected": date.today().isoformat(),
           "note": "네이버 모바일 파워링크·브랜드 콘텐츠 광고 문구, 경쟁 매장 플레이스 쿠폰·편의·소식(최근 12개). offer = 혜택·이벤트 단어 포함",
           "ads": ads, "places": places}
    (d / "competitor_ads.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 경쟁사 광고·이벤트 ({date.today().isoformat()}, ego-browser)", "", "## 키워드별 파워링크 광고 문구 (혜택 단어)"]
    for kw, a in ads.items():
        md.append(f"### {kw}")
        rows = [f"- {x['text'][:160]}" + (f"  **[{', '.join(x['offers'])}]**" if x["offers"] else "") for x in a["powerlink"]]
        md += rows or ["- 파워링크 없음"]
    md += ["", "## 경쟁 매장 쿠폰·이벤트·소식", "| 매장 | 쿠폰 | 혜택·이벤트 소식 (날짜) | 최근 소식 수 · 마지막 날짜 |", "|---|---|---|---|"]
    for pid, p in places.items():
        offers = "; ".join(f"{x['title'][:40]} ({x['date']})" for x in p["offer_posts"][:4]) or "-"
        last = max(x["date"] for x in p["posts"]) if p["posts"] else "-"
        md.append(f"| {p['name']} | {' / '.join(p['coupons'])[:80] or '-'} | {offers} | {len(p['posts'])} · {last} |")
    md += ["", "- 쿠폰·소식은 플레이스 화면에 보이는 그대로다. 매출·전환 효과는 공개 자료가 없으면 '운영 방식만 확인'으로 쓴다."]
    (d / "competitor_events.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"경쟁사 광고 {len(ads)}개 키워드 · 매장 {len(places)}곳 저장: {d / 'competitor_events.md'}")
    return obj



# ---------------------------------------------------------------- place-analysis (애드로그 플레이스 + 리뷰)
PLACE_JS = r"""
const ids = __IDS__;
await page.goto("https://www.adlog.kr/adlog/naver_place_hidden_keyword.php", { timeout: 60000 });
const logged = (await page.evaluate(() => document.body.innerText)).includes("로그아웃");
result = { logged, places: {} };
const post = async (path, body, json) => String((await page.fetch("/adlog/" + path, json
  ? { method: "POST", headers: { "content-type": "application/json", "x-requested-with": "XMLHttpRequest" }, body: JSON.stringify(body), timeout: 90000 }
  : { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded; charset=UTF-8", "x-requested-with": "XMLHttpRequest" }, body: new URLSearchParams(body).toString(), timeout: 90000 })).body);
if (logged) {
  for (const id of ids) {
    const r = {};
    try { r.info = await post("ajax_place_detail_info.php", { place_id: id }, true); } catch (e) { r.info = ""; }
    try { r.compare = await post("ajax_place_compare.php", { place_id: id, mode: "history", days: 30 }, true); } catch (e) { r.compare = ""; }
    try { r.hidden = await post("naver_place_hidden_keyword_exec.php", { api_section: "10", api_type: "92", api_industry: "", keyword2: id, check_rank: "20" }); } catch (e) { r.hidden = ""; }
    try { r.visits = await post("ajax_place_review.php", { place_id: id, mode: "visit", sort: "recent" }); } catch (e) { r.visits = ""; }
    result.places[id] = r;
    await page.waitForTimeout(1200);
  }
}
for (const id of ids) {
  await page.goto("https://m.place.naver.com/place/" + id + "/review/visitor", { timeout: 60000 });
  await page.waitForTimeout(2500);
  (result.places[id] = result.places[id] || {}).review_page = await page.evaluate(() => document.body.innerText.slice(0, 6000));
  await page.waitForTimeout(700);
}
"""


def _jl(s):
    try:
        return json.loads(s) if s and s.strip() else None
    except Exception:
        return None


def place_analysis(slug, place_id, competitor_ids=None, top_n=5):
    """우리 매장 + 경쟁 매장: 애드로그 종합분석(키워드 순위)·히든 키워드·최근 방문자 리뷰, 네이버 리뷰 키워드·메뉴·특징."""
    d = data_dir(slug)
    ids = [place_id] + [c for c in (competitor_ids or []) if c != place_id]
    if not competitor_ids and (d / "ranks.json").exists():
        for v in json.loads((d / "ranks.json").read_text(encoding="utf-8")).values():
            for t in v.get("top", [])[:top_n]:
                if t["id"] not in ids:
                    ids.append(t["id"])
        ids = ids[:1 + top_n]
    res = run_ego(ego_script(f"collect {slug} place-analysis", PLACE_JS.replace("__IDS__", json.dumps(ids))),
                  timeout=120 + 40 * len(ids))
    if not res["logged"]:
        print("애드로그 로그인이 안 돼 있어 네이버 리뷰 화면만 모았습니다. 에고라이트에서 adlog.kr 로그인 후 다시 실행하면 순위·히든 키워드도 받습니다.")
    today = date.today()
    out = {}
    for pid in ids:
        r = res["places"].get(pid, {})
        info = _jl(r.get("info")) or {}
        comp = (_jl(r.get("compare")) or {}).get(str(pid), {})
        ranks = sorted(({"keyword": k, "rank": v.get("place_rank"), "change": v.get("place_change")} for k, v in comp.items()),
                       key=lambda x: x["rank"] if isinstance(x["rank"], int) else 9999)
        hidden_html = (_jl(r.get("hidden")) or {}).get("items", "")
        htxt = re.sub(r"(\s*\|\s*)+", " | ", re.sub(r"<[^>]+>", " | ", hidden_html))
        hidden = []
        m = re.search(r"히든 키워드 \d+개 \|.*?전체 키워드 복사 \|(.*)", htxt)
        if m:
            hidden = [x.strip() for x in m.group(1).split("|") if x.strip()][:40]
        visits = (_jl(r.get("visits")) or {}).get("visit_arr") or []
        dates = [v[1] for v in visits if len(v) > 1]

        def within(days):
            return sum(1 for x in dates if (today - date.fromisoformat(x)).days <= days)
        page_t = [x.strip() for x in r.get("review_page", "").splitlines()]
        good, joined = [], ""
        if "이런 점이 좋았어요" in page_t:
            i = page_t.index("이런 점이 좋았어요")
            joined = next((x for x in page_t[i:i + 4] if "참여" in x), "")
            for j in range(i, min(i + 40, len(page_t) - 2)):
                if page_t[j].startswith('"') and page_t[j + 1] == "이 키워드를 선택한 인원":
                    good.append(f"{page_t[j].strip(chr(34))} {page_t[j + 2]}")

        def block(title, stop):
            if title not in page_t:
                return []
            i = len(page_t) - 1 - page_t[::-1].index(title) if title == "특징" else page_t.index(title)
            if title == "메뉴" and "특징" in page_t:
                f = page_t.index("특징")
                cand = [k for k in range(f) if page_t[k] == "메뉴"]
                i = cand[-1] if cand else i
            items = []
            for x in page_t[i + 1:i + 30]:
                if x in stop:
                    break
                mm = re.fullmatch(r"(\D+?)([\d,]+)", x)
                if mm:
                    items.append(f"{mm.group(1)} {mm.group(2)}")
            return items
        out[pid] = {"name": info.get("place_name") or (page_t[1] if len(page_t) > 1 else pid),
                    "category": info.get("place_category"), "rep_keywords": info.get("place_detail_keyword"),
                    "visit_reviews": info.get("place_visit_cnt"), "blog_reviews": info.get("place_blog_cnt"),
                    "keyword_ranks": ranks[:30], "hidden_keywords": hidden,
                    "recent_reviews": {"sample": len(dates), "last30": within(30), "last90": within(90), "latest": max(dates) if dates else None,
                                       "types": dict(collections.Counter(v[2] for v in visits if len(v) > 2))},
                    "liked": good, "liked_joined": joined,
                    "menu_mentions": block("메뉴", {"특징", "추천순"})[:10], "features": block("특징", {"추천순", "최신순"})[:10]}
    obj = {"collected": today.isoformat(), "place_id": place_id,
           "note": "애드로그(종합분석 키워드 순위·히든 키워드·최근 방문자 리뷰 표본) + 네이버 리뷰 화면(이런 점이 좋았어요·메뉴·특징 언급 수)",
           "places": out}
    (d / "place_analysis.json").write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    md = [f"# 플레이스·리뷰 분석 ({today.isoformat()}, ego-browser · 애드로그)", "",
          "| 매장 | 방문자/블로그 리뷰 | 최근 리뷰 (표본 중 30일·90일) | 상위 키워드 순위 (애드로그) | 히든 키워드 수 | 이런 점이 좋았어요 (상위 3) |",
          "|---|---|---|---|---|---|"]
    for pid, p in out.items():
        top = ", ".join(f"{x['keyword']} {x['rank']}위" for x in p["keyword_ranks"][:3]) or "-"
        rr = p["recent_reviews"]
        mark = " (우리)" if pid == place_id else ""
        md.append(f"| {p['name']}{mark} | {p['visit_reviews'] or '-'} / {p['blog_reviews'] or '-'} | {rr['last30']}·{rr['last90']} (표본 {rr['sample']}, 최근 {rr['latest'] or '-'}) | {top} | {len(p['hidden_keywords'])} | {', '.join(p['liked'][:3]) or '-'} |")
    md += ["", "## 매장별 상세"]
    for pid, p in out.items():
        md += [f"### {p['name']}" + (" (우리)" if pid == place_id else ""),
               f"- 대표키워드: {p['rep_keywords'] or '-'}",
               f"- 히든 키워드: {', '.join(p['hidden_keywords']) or '-'}",
               f"- 키워드 순위(상위 10): " + (", ".join(f"{x['keyword']} {x['rank']}위({x['change']:+d})" if isinstance(x['change'], int) else f"{x['keyword']} {x['rank']}위" for x in p["keyword_ranks"][:10]) or "-"),
               f"- 리뷰 키워드: {p['liked_joined']} — " + (", ".join(p["liked"]) or "-"),
               f"- 메뉴 언급: {', '.join(p['menu_mentions']) or '-'} / 특징 언급: {', '.join(p['features']) or '-'}",
               f"- 최근 방문자 리뷰 유형(표본): {p['recent_reviews']['types'] or '-'}", ""]
    md.append("- 순위는 애드로그가 추적한 키워드 기준. 최근 리뷰 수는 애드로그가 준 표본 안에서 센 값이다.")
    (d / "place_analysis.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"플레이스·리뷰 분석 {len(out)}곳 저장: {d / 'place_analysis.md'}")
    return obj


def main():
    ap = argparse.ArgumentParser(description="ego-browser 로 제안서 자료 수집")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("trends"); t.add_argument("--slug", required=True); t.add_argument("--keywords", required=True); t.add_argument("--naver-groups")
    a = sub.add_parser("adlog"); a.add_argument("--slug", required=True); a.add_argument("--keywords", required=True); a.add_argument("--out", default="adlog_keyword_bids.json")
    c = sub.add_parser("pc-candidates"); c.add_argument("--slug", required=True); c.add_argument("--middle", default=""); c.add_argument("--pattern", required=True); c.add_argument("--exclude")
    p = sub.add_parser("powercontents"); p.add_argument("--slug", required=True); p.add_argument("--keywords", required=True); p.add_argument("--out", default="naver_powercontents_purchasable.json")
    s = sub.add_parser("capture"); s.add_argument("--slug", required=True); s.add_argument("--keywords", default=""); s.add_argument("--url", action="append")
    cp = sub.add_parser("competitors"); cp.add_argument("--slug", required=True); cp.add_argument("--keywords", default=""); cp.add_argument("--place-ids", default=""); cp.add_argument("--top", type=int, default=8)
    pa = sub.add_parser("place-analysis"); pa.add_argument("--slug", required=True); pa.add_argument("--place-id", required=True); pa.add_argument("--competitor-ids", default=""); pa.add_argument("--top", type=int, default=5)
    al = sub.add_parser("all"); al.add_argument("--slug", required=True); al.add_argument("--trend-keywords", required=True); al.add_argument("--keywords", required=True); al.add_argument("--naver-groups")
    x = ap.parse_args()
    if x.cmd == "trends":
        trends(x.slug, split_kw(x.keywords), x.naver_groups)
    elif x.cmd == "adlog":
        adlog(x.slug, split_kw(x.keywords), x.out)
    elif x.cmd == "pc-candidates":
        pc_candidates(x.slug, x.middle, x.pattern, x.exclude)
    elif x.cmd == "powercontents":
        powercontents(x.slug, split_kw(x.keywords), x.out)
    elif x.cmd == "capture":
        capture(x.slug, split_kw(x.keywords), x.url)
    elif x.cmd == "competitors":
        competitors(x.slug, split_kw(x.keywords), split_kw(x.place_ids), x.top)
    elif x.cmd == "place-analysis":
        place_analysis(x.slug, x.place_id, split_kw(x.competitor_ids), x.top)
    elif x.cmd == "all":
        kws = split_kw(x.keywords)
        cand = data_dir(x.slug) / "powercontents_candidates.json"
        pc_kws = [k["키워드"] for k in json.loads(cand.read_text(encoding="utf-8"))["keywords"]] if cand.exists() else []
        trends(x.slug, split_kw(x.trend_keywords), x.naver_groups)
        adlog(x.slug, list(dict.fromkeys(kws + pc_kws)))
        powercontents(x.slug, list(dict.fromkeys(kws + pc_kws)))
        competitors(x.slug, kws, [])


if __name__ == "__main__":
    main()
