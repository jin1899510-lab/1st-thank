# 제안서 도구

| 파일 | 하는 일 |
|---|---|
| `collect.py` | 업체 하나의 기본 자료 수집 → `proposals/<slug>/data/` (매장 정보, 키워드별 플레이스 상위 10곳, 반경 안 경쟁 매장, 통합검색·AI 브리핑·파워링크, 애드로그 히든 키워드·검색량, `summary.md`) |
| `check_pptx.py` | 완성 PPTX 점검: 금지 문구, 마지막 장 가격이 앞 장에 있는지, 다른 고객 이름, 아이콘 자리 빈 도형, 글자를 덮는 버튼, 남은 `[확인 필요]` |
| `naver_place.py` | 네이버 플레이스·모바일 통합검색 수집 함수 |
| `adlog.py` | 애드로그 로그인·플레이스 분석·키워드 검색량 함수 (`ADLOG_ID`, `ADLOG_PW` 필요) |

```bash
python3 tools/collect.py --slug nekonomura --place-id 1573719918 --keywords "장산역 초밥,장산역 연어덮밥"
python3 tools/check_pptx.py proposals/nekonomura/output/nekonomura-proposal.pptx
```

- 네이버 플레이스 목록은 한 번에 상위 10곳만 나온다. 더 깊은 순위는 애드로그 히든 키워드 순위를 쓴다.
- 클라우드 세션에서는 네이버 데이터랩·구글 트렌드·상권분석시스템이 막힌다. 작업 순서는 `.claude/skills/proposal/SKILL.md`.
