# 제안서 도구

| 파일 | 하는 일 |
|---|---|
| `collect.py` | 업체 하나의 기본 자료 수집 → `proposals/<slug>/data/` (매장 정보, 키워드별 플레이스 상위 10곳, 반경 안 경쟁 매장, 통합검색·AI 브리핑·파워링크, 애드로그 히든 키워드·검색량, `summary.md`) |
| `check_pptx.py` | 완성 PPTX 점검: 금지 문구, 마지막 장 가격이 앞 장에 있는지, 다른 고객 이름, 아이콘 자리 빈 도형, 글자를 덮는 버튼, 남은 `[확인 필요]` |
| `naver_place.py` | 네이버 플레이스·모바일 통합검색 수집 함수 |
| `browser_collect.py` | 대표님 PC 브라우저(ego-browser)로 수집: 구글 트렌드·네이버 데이터랩(`trends`), 애드로그 검색량·입찰가(`adlog`, 브라우저 로그인 사용), 파워컨텐츠 구매 가능 후보(`pc-candidates`), 파워컨텐츠 광고주(`powercontents`), 경쟁사 광고 문구·쿠폰·이벤트·소식(`competitors`), 애드로그 플레이스 종합분석·히든 키워드·리뷰 + 네이버 리뷰 키워드(`place-analysis`), 휴대폰 화면 캡처(`capture`), 한 번에(`all`) |
| `data/powercontents_keywords_*.csv` | 네이버 파워컨텐츠 구매 가능 키워드 목록 (대표님 제공 엑셀을 변환, 최신 파일을 씀) |
| `naver_ad.py` | 네이버 검색광고 API로 키워드 월간 검색수·클릭·경쟁 정도 (애드로그 호출 한도 없이). 키는 환경 변수 `NAVER_AD_*` 또는 `~/.naver_ad.json` |
| `adlog.py` | 애드로그 로그인·플레이스 분석·키워드 검색량 함수 (`ADLOG_ID`, `ADLOG_PW` 필요) |

```bash
python3 tools/collect.py --slug nekonomura --place-id 1573719918 --keywords "장산역 초밥,장산역 연어덮밥"
python3 tools/check_pptx.py proposals/nekonomura/output/nekonomura-proposal.pptx
python tools/browser_collect.py trends --slug song-law --keywords "노란봉투법,중대재해처벌법,기술유출,공직선거법"
python tools/browser_collect.py pc-candidates --slug song-law --middle 법률 --pattern "중대재해|노동|배임|기술유출" --exclude "이혼|상속"
python tools/browser_collect.py adlog --slug song-law --keywords "중대재해 변호사,노동 변호사"
python tools/browser_collect.py powercontents --slug song-law --keywords "기술유출,경업금지"
python tools/browser_collect.py competitors --slug nekonomura --keywords "장산역 초밥,해운대 초밥"
python tools/browser_collect.py capture --slug song-law --keywords "중대재해 변호사"
```

- `browser_collect.py`는 에고라이트 브라우저가 켜져 있어야 한다. 애드로그는 그 브라우저에 로그인돼 있어야 한다 (비밀번호는 저장하지 않음). 결과 파일 이름은 각 명령 설명(파일 맨 위)에 있다.
- 네이버 플레이스 목록은 한 번에 상위 10곳만 나온다. 더 깊은 순위는 애드로그 히든 키워드 순위를 쓴다.
- 클라우드 세션에서는 네이버 데이터랩·구글 트렌드·상권분석시스템이 막힌다. 작업 순서는 `.claude/skills/proposal/SKILL.md`.
