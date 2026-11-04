# AI 이미지 프롬프트 규칙

## 기본값: 모든 이미지 4:5 세로 실사
- `kind: "photo"`, `ratio: "4:5"` (대표 썸네일 포함). 빌더가 영문 프롬프트 끝에 `vertical 4:5 aspect ratio`를 자동으로 붙이고, 미리보기 칸도 4:5로 그린다.
- 썸네일 여부는 캡션이 `대표 썸네일`로 시작하는지로 판단한다.
- 사용자가 다른 비율(16:9, 1:1)이나 일러스트를 원하면 `01_지점_작성지침.md`에 적고 그대로 따른다.

## prompts.json 형식

```json
{
 "style_photo": "editorial lifestyle photograph, photorealistic, soft natural window light, muted palette of soft teal, warm white and light grey, clean minimal Korean interior, realistic natural skin texture with visible pores, no heavy retouching, candid moment, 50mm lens, f/2.8, subtle film grain, vertical portrait framing",
 "style_illu": "photorealistic photograph",
 "negative": "illustration, cartoon, 3d render, CGI, plastic skin, airbrushed, over-saturated, extra fingers, distorted hands, uncanny face, text, letters, watermark, logo, brand names, before-and-after comparison, hospital or surgery scene, medical equipment, needles, syringes, blood, visible acne or lesions, burn wounds, blisters, warts, close-up of skin disease",
 "images": {
  "<원고 속 캡션과 정확히 같은 문자열>": {
   "kind": "photo",
   "ratio": "4:5",
   "use": "이 사진이 쓰이는 자리 (예: '3분 안에 보습' 항목)",
   "en": "장면 묘사만 (스타일·비율 문구는 빌더가 자동으로 붙임)",
   "ko": "한글 프롬프트 (장면 + '4:5 세로 실사 사진')",
   "text": "사진 위에 올릴 한글 문구 또는 null"
  }
 }
}
```

`style_photo`의 색감은 병원 브랜드 색에 맞춰 바꿔도 된다. 한 프로젝트 안에서는 같은 스타일 문구를 유지해야 사진들이 한 블로그처럼 보인다. `negative`의 병변 항목은 진료과에 맞게 바꾼다 (치과면 치아 클로즈업·피 등).

## 글 한 편당 구성 (8장 이상)
- 1장: 대표 썸네일, 위쪽 3분의 1은 제목 공간 ("large empty space in the upper third for a title"), `text`에 썸네일 문구
- 1장: 도입 공감 장면 (생활 속 한 순간)
- 2~3장: 원리 설명 = **비유 사물 실사** (벽돌담, 새싹과 뿌리, 약불 냄비, 깊이가 다른 조약돌, 물건을 늘어놓은 탑뷰 정물). `text`에 비유 설명 문구
- 1장: "하지 마세요" = 해당 물건 탑뷰 정물, `text`에 "○○ 금지"
- 3~4장: 해결법 항목별 생활 사진 (그 항목의 행동을 그대로 보여줌)
- 1장: 상담 장면 = 책상 너머 어깨 뒤 구도, 의사는 가슴 아래만, 얼굴 없음, 의료 장비 없음, 메모장에 펜
- 1장: "진료가 필요한 때" (달력, 메모 등)

## 어색하지 않게
- 사람은 한국인, 나이대를 명시 ("Korean woman in her 30s"). 자연스러운 피부결, 과한 보정 금지.
- 손이 나오면 동작을 구체적으로 ("pressing lightly, no rubbing").
- 얼굴이 꼭 필요 없으면 크롭 ("face cropped from nose to jaw", "face out of frame").
- 피부를 보여야 하는 자리는 "clear natural skin with no visible acne/wound"로 병변 없이.
- 제품은 "unbranded", 메모·화면 글씨는 "blurred and unreadable".
- 한글 글자는 AI로 넣지 않는다. `text`에 적고 캔바·미리캔버스에서 올리도록 안내.
- 캡션에 "일러스트"를 쓰지 않는다 (실사 기본).
