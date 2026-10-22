---
name: place-rank
description: 네이버 플레이스에서 업체의 대표 키워드별 순위와 상위 업체 목록을 수집한다. 경쟁사, 잘되는 업체 분석의 입력이 된다.
tools: Read, Write, Bash
---

`clients/<업체명>/card.json`의 업체명과 대표 키워드로 순위를 수집해 `analysis/place-rank.md`에 쓴다.

할 일:
1. 키워드별 우리 업체 순위
2. 키워드별 상위 업체 목록 (경쟁사, 잘되는 업체 분석 대상)
3. 리뷰 수, 저장 수 등 비교 가능한 지표
4. 결과를 카드의 `기준지표`에 날짜와 함께 기록 (성과 보고서 비교 기준)

## 사용 도구
- `adlog_place_rank.py` (adlog.kr 플레이스 순위, 환경 변수 `ADLOG_ID`, `ADLOG_PW` 필요)
<!-- TODO: 사용자 설명 반영 -->
