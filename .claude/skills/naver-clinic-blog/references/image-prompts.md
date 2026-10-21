# AI 이미지 프롬프트 규칙

## prompts.json 형식

```json
{
 "style_photo": "editorial lifestyle photograph, soft natural window light, muted palette of soft teal, warm white and light grey, clean minimal Korean apartment interior, realistic natural skin texture with visible pores, no heavy retouching, candid moment, 35mm lens, f/2.8, subtle film grain",
 "style_illu": "calm editorial illustration, flat shapes with subtle paper grain, muted palette of soft teal, warm beige and light grey, gentle and respectful tone, simple clean composition",
 "negative": "plastic skin, airbrushed, over-saturated, extra fingers, distorted hands, uncanny face, text, letters, watermark, logo, brand names, before-and-after comparison, hospital or surgery scene, needles, blood, exaggerated acne or lesions",
 "images": {
  "<원고 속 캡션과 정확히 같은 문자열>": {
   "kind": "photo | illu",
   "ratio": "1:1 (썸네일) | 16:9",
   "use": "이 사진이 쓰이는 자리 (예: '3분 안에 보습' 항목)",
   "en": "장면 묘사만 (스타일 문구는 빌더가 kind에 따라 자동으로 붙임)",
   "ko": "한글 프롬프트 (장면 + 짧은 스타일)",
   "text": "카드에 올릴 한글 문구 또는 null"
  }
 }
}
```

`style_*`의 색감은 병원 브랜드 색에 맞춰 바꿔도 된다. 한 프로젝트 안에서는 같은 스타일 문구를 유지해야 사진들이 한 블로그처럼 보인다.

## 글 한 편당 구성 (8장 이상)
- 1장: 대표 썸네일 1:1, 제목 문구 넣을 여백 ("empty space for a title"), `text`에 썸네일 문구
- 1장: 도입 분위기 사진
- 2~3장: 원리 설명용 교육 일러스트 (단면도, 비교 아이콘)
- 3~4장: 해결법 항목별 생활 사진 (그 항목의 행동을 그대로 보여줌)
- 1장: "이럴 땐 진료" 문단용 (달력, 메모 노트, 상담 일러스트)

## 어색하지 않게
- 사람은 한국인, 나이대를 명시 ("Korean woman in her 30s"). 자연스러운 피부결, 과한 보정 금지.
- 손이 나오면 동작을 구체적으로 ("pressing lightly, no rubbing").
- 얼굴이 꼭 필요 없으면 크롭 ("face cropped from nose to jaw").
- 제품은 "unbranded", 메모·안내문은 "handwriting blurred and unreadable".
- 한글 글자는 AI로 넣지 않는다. `text`에 적고 캔바·미리캔버스에서 올리도록 안내.
- 병변·흉터·색소는 사진 대신 "educational cross-section ... flat vector, pastel, no labels".
- 상담 장면은 "generic illustration ... not a real clinic, no medical equipment, no needles".
