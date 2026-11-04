---
name: proposal
description: 감사한 마케팅 제안서 작업 순서. 대표님이 "시작하자", "새 업체", "제안서 만들자"라고 하거나 업체 정보를 주면 이 순서로 진행한다. 상권분석·업종분석·키워드×채널 조사·검색 트렌드·성공 사례·원고(slides.md)·젠스파크 PPTX·점검까지.
---

# 제안서 작업 순서

규칙은 `proposals/RULES.md`, 시작 질문은 `CLAUDE.md`를 따른다. 이 문서는 **순서와 도구**만 정한다.

## 0. 시작 질문
- `CLAUDE.md`의 시작 질문 1–8을 묻는다 (8번: 상권분석시스템 자료 첨부 요청).
- `CLAUDE.md`의 '다음 작업 시작 때 한 번 물어볼 것'이 남아 있으면 같이 묻는다.
- `proposals/clients.md`에서 같은 상가·같은 상권·같은 업종 고객이 있는지 보고, 있으면 대표님께 알린다 (업종별 지역 한정 약속).

## 1. 기본 수집 (스크립트)
```bash
python3 tools/collect.py --slug <영문이름> --place-id <플레이스 ID> \
  --keywords "지역+업종, 지역+대표메뉴, 역이름+업종, 동네+맛집, ..." --radius 500
```
- 플레이스 ID: 플레이스 링크의 숫자. `naver.me` 단축 링크는 `curl -sI`로 따라가서 숫자를 찾는다.
- 키워드는 10–25개: 지역(역·동·구) × 업종·대표 메뉴·점심·혼밥 등.
- 결과: `proposals/<slug>/data/summary.md` 먼저 읽는다. 애드로그 히든 키워드에서 다른 지역·엉뚱한 키워드가 잡혀 있는지 본다.
- 리뷰 날짜(개업·메뉴 변경 시기)는 `https://m.place.naver.com/restaurant/<ID>/review/visitor` 의 APOLLO 상태에서 `VisitorReview:` 항목으로 확인.

## 2. 채널 조사 (스크립트 밖)
| 채널 | 방법 |
|---|---|
| 구글 지도 | `gsk maps-search "<상호>" --query_type place --engine maps`, 주요 키워드도 |
| 구글·웹 | `gsk search "<상호> <지역>"`, `gsk search "<키워드>"` → 인스타·당근·114 등 다른 채널의 상호·메뉴·전화 불일치 확인 |
| AI 검색 | `gsk task create super_agent` 로 손님 질문 4개 (예: "<역> 근처 <메뉴> 맛집 추천") → 추천 가게 목록·출처, 우리 매장 언급 여부 |
| 당근 | `daangn.com/kr/local-profile/` 페이지 제목·메뉴 |
| 인스타 | 클라우드에서는 막힘. `gsk search "site:instagram.com <계정>"`로 게시물 설명만 확인 |

결과는 `data/`에 텍스트로 저장한다 (`gm_*.txt`, `gs_*.txt`, `ai_search_*.md`).

## 3. 검색 트렌드 (브라우저)
- 구글 트렌드 + 네이버 데이터랩 검색어트렌드, 조건은 RULES.md '검색 트렌드' 항목.
- 대표님 PC 브라우저(ego-browser, Aside 등)가 연결돼 있으면 직접 조회한다. 아니면 조회 요청문을 드리고 결과 파일을 받는다. 클라우드에서는 403·429로 막힌다.
- 수치를 추정해서 채우지 않는다.

## 4. 상권분석
- 대표님이 상권분석시스템 자료를 주면 그 수치를 우선 쓴다.
- 없으면 공개 자료: 행정안전부 주민등록 인구(동별 인구·세대·연령), 네이버 지도 아파트 단지 수, 지하철·학교·쇼핑 거리, 지역 개발 기사.
- 같은 건물·상권의 이전 제안서가 있으면 그 자료를 재사용하고 출처를 그대로 적는다.

## 5. 성공 사례
- RULES.md '성공 사례 분석 방법' 그대로. 주변 매장(쿠폰·소식·가격 정책)은 1단계 `competitors.json`에서 바로 뽑을 수 있다.
- 근거가 약하면 약하다고 쓴다.

## 6. 원고
- `proposals/<slug>/slides.md` — 기존 제안서(`proposals/nekonomura/slides.md`)의 장 구성을 틀로 쓴다.
- 상품은 대표님이 말한 것 → 없으면 노션 상품 기준. 가격은 마지막 장만.
- 쓰고 나서 금지 문구 확인: `grep -nE "브랜드 블로그|1건당|매일 바|미노출|부가세|설문|구글폼" proposals/<slug>/slides.md`
- **검토 에이전트**: `proposal-reviewer` 에이전트(`.claude/agents/proposal-reviewer.md`)에 원고와 `data/`를 넘겨 검토받는다. 쓴 쪽과 분리된 검토라 숫자 불일치·근거 없는 단정·다른 고객 정보 섞임을 잡는다. [치명]·[숫자]는 모두 고치고, [근거 없음]은 근거를 찾거나 문장을 약하게 고치거나 `[확인 필요]`로 바꾼다.
- 대표님께 `[확인 필요]` 목록과 함께 보내고 확정을 받는다. 확정 전에는 젠스파크를 부르지 않는다.

## 7. 젠스파크 생성 (업체당 1회)
- `gsk task create slides --args-file X.json`, X.json = `{"task_name", "query": 지시 + 원고 전체, "instructions"}`.
  - instructions에 꼭 넣을 것: 가격은 마지막 장만, 표 숫자 그대로, 새 문구(부가세 등) 금지, `[확인 필요]`는 글자로만(배지·도형 금지), 링크는 클릭되게, 메타 정보·출처 목록은 슬라이드로 만들지 않음.
- `gsk task status <run_id>` 로 `data.state`가 `succeeded`가 될 때까지 기다린다.
- `gsk task export <project_id> -o proposals/<slug>/output/<slug>-proposal.pptx`
- project_id는 원고 맨 위나 대화에 남겨 둔다.

## 8. 점검 → 수정
```bash
python3 tools/check_pptx.py proposals/<slug>/output/<slug>-proposal.pptx
```
- ✗ 항목은 모두 고친다 (python-pptx: 문단 단위 교체, 빈 도형 삭제, 버튼은 글자 뒤로).
- 화면도 본다: `soffice --headless --convert-to pdf` → `pdftoppm -r 40 -png` → 6장씩 묶어 확인.
- 원고에 없는 문구, 다른 고객 이름이 들어갔는지 반드시 확인한다.
- 대표님이 젠스파크 화면을 쓰면 같은 수정을 `gsk task ask`로 한 번에 보낸다 (RULES.md 크레딧 순서 6).

## 9. 전달·저장
- PPTX를 대표님께 보내고, 반영한 것 / 파일에서만 고친 것 / `[확인 필요]` 남은 것을 나눠 보고한다.
- `slides.md`와 `data/`는 커밋·push한다 (`output/`은 git 제외).
- `proposals/clients.md`에 업체 줄을 추가하거나 상태를 고친다. 계약 고객의 월간 성과는 `proposals/cases.md`에 쌓는다.
