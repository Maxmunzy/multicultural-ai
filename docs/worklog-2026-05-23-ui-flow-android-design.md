# 2026-05-23 워크로그 — UI/UX 시연 플로우 교정 + Android 디자인 시스템 적용

**작성일:** 2026-05-23  
**작성자:** jyj  
**작업 범위:** android/design_reference HTML 스펙 교정, MainActivity.java 디자인 시스템 적용  
**브랜치:** `feature/yunjeong-extraction-v5`

---

## 한 줄 요약

실제 서비스 플로우(학부모 트리거 AI 번역)와 어긋나 있던 teacher.html·parent.html을 교정하고, CSS 디자인 토큰(인디고/바이올렛)을 Android 앱에 적용했다. 선생님 발송완료 화면과 학부모 AI CTA 카드를 신규 추가했다.

---

## 작업 배경

### 1. 플로우 오류 발견

README의 실제 API 흐름:
```
선생님 → POST /notice/upload → FCM push → 학부모 → POST /notice/analyze/{id} → AI 번역 결과
```

기존 teacher.html의 화면 구성:
```
작성 → AI 분석 미리보기 → 번역 확인 → 발송
```

**문제**: 선생님이 발송 전에 AI 분석을 보는 화면이 존재했으나, 실제 백엔드에는 이 엔드포인트가 없음. AI 번역은 전적으로 학부모 앱에서 트리거됨. 공모전 심사위원이 demo를 보면 아키텍처를 오해할 수 있음.

### 2. 언어 수 불일치

README 명세: 9개 언어 (vi/en/ru/ms/mn/zh/th/ja + ko_easy)  
UI 표기: 여러 곳에서 "8개 언어" — 3개 파일 5곳

### 3. 불필요한 기능 노출

parent.html Screen 6 "통신문 직접 추가(사진/PDF)" — 현재 시연 범위 밖.  
MainActivity.java "통신문 직접 올리기" 버튼 — 동일.

---

## 작업 내용

### 1. 언어 수 통일 (8 → 9)

| 파일 | 위치 | 수정 내용 |
|---|---|---|
| `android/design_reference/parent.html` | stats 섹션 | `8개` → `9개` (지원 언어) |
| `android/design_reference/parent.html` | 파이프라인 박스 | "8개 언어 번역" → "9개 언어 번역" |
| `android/design_reference/parent.html` | 번역 탭 배너 | "현재 8개 언어 지원 중" → "현재 9개 언어 지원 중" |
| `demo/index.html` | 헤더 subtitle | "가정통신문 AI · 8개 언어" → "9개 언어" |

ko_easy(쉬운 한국어)는 폐지 예정이므로 언어 선택 목록에는 포함하지 않음. 9개는 README 명세 기준 수치.

---

### 2. teacher.html — 실제 플로우로 재편

**기존 5화면**:
```
1·우리반 홈 → 2·통신문 작성(4단계 스텝바) → 3·AI 분석 미리보기 → 4·번역 확인 → 5·회신 현황
```

**수정 후 4화면**:
```
1·우리반 홈 → 2·통신문 작성(2단계) → 3·발송 완료 → 4·회신 현황
```

변경 세부:
- Screen 2 스텝바: 4단계(작성/미리보기/번역확인/발송) → 2단계(작성/발송)
- Screen 2 AI 배너: "텍스트를 확인하고 AI 분석을 시작하세요" → "발송하면 학부모 앱에서 AI 번역이 자동 제공됩니다 · 9개 언어 번역"
- Screen 2 발송 버튼: "발송 전 미리보기 →" → "24명에게 발송"
- Screen 3·4(AI 분석 미리보기, 번역 확인) 전체 제거
- **신규 Screen 3 "발송 완료"**: FCM 푸시 전송 / 9개 언어 / TTS 포함 / 용어사전 340개 칩, 일정·준비물·번역음성 추출 항목 카드
- 플로우 화살표: "발송 전 미리보기" / "번역 미리보기" / "발송 후 현황" → "발송" / "회신 현황"

---

### 3. parent.html — 미구현 화면 제거

- Screen 6 "통신문 추가 (입력 방식)" 전체 삭제
- 해당 screen으로 향하는 "번역 탭" 플로우 화살표 삭제
- 최종 구성: 5화면 (홈 → 원문 → AI 번역 결과 → 회신 → 일정·준비물)

---

### 4. Android 앱 — 디자인 시스템 적용 (MainActivity.java)

#### 4-1. 색상 토큰 업데이트

CSS `daon-shared.css v2` 기준으로 Java 상수 재정의:

| 상수명 | 기존 | 변경 후 | CSS 변수 |
|---|---|---|---|
| `COLOR_PEACH_DEEP` | `#3B67FF` | `#4F46E5` | `--brand` |
| `COLOR_PEACH_INK` | `#1A237E` | `#3730A3` | `--brand-deep` |
| `COLOR_PEACH` | `#DBEAFE` | `#EEF2FF` | `--brand-light` |
| `COLOR_INK` | `#111827` | `#1E1B4B` | `--ink` |
| `COLOR_PAPER2` | `#EEF2FF` | `#F8FAFF` | `--surface2` |

신규 추가:
```java
COLOR_AI       = #7C3AED  // --ai (바이올렛)
COLOR_AI_LIGHT = #F5F3FF  // --ai-light
COLOR_AI_MID   = #DDD6FE  // --ai-mid
```

#### 4-2. 학부모 통신문 상세 화면 (`showNoticeDetail`)

- 우측 상단 "✨ AI 번역" 작은 pill 버튼 제거
- 언어 선택 pill(`langPillBtn`)로 교체
- 노란 힌트 카드("우측 상단 ✨ 버튼을 누르면...") 제거
- **신규 AI CTA 카드** (demo parent.html Screen 2의 `ai-cta` 컴포넌트):
  - 배경: `COLOR_AI_LIGHT` + `COLOR_AI_MID` 테두리
  - 바이올렛 아이콘 박스(44×44dp) + ✨ 이모지
  - 타이틀: "AI 번역하기" / 부제: "9개 언어 자동 번역 · TTS 음성 포함"
  - 풀 width 버튼 → `showAIOverlay(notice)` 호출

#### 4-3. 선생님 발송완료 화면 신규 (`showTeacherSendComplete`)

발송 성공(파일 첨부 / 텍스트 직송 모두) 후 텍스트 결과 표시 대신 전용 화면으로 전환.

구성:
- 제목: "발송 완료 ✓" / 부제: "학부모 앱으로 전달됐습니다"
- 칩 행 1: FCM 푸시 전송 / 9개 언어 / TTS 포함
- 칩 행 2: 용어사전 340개 / Claude Haiku 4.5
- 추출 항목 요약 카드 3개:
  - 📅 일정 — 캘린더 자동 저장
  - 🎒 준비물 — 체크리스트 생성
  - 🌐 번역·음성 — 9개 언어 + TTS
- 버튼: "회신 현황 보기 →" (notImplementedToast) / "새 통신문 작성" / "← 홈으로"

신규 헬퍼 메서드:
- `statusChip(label, bgColor, inkColor)` — 둥근 배지 칩
- `extractSummaryRow(emoji, label, desc, bgColor, accentColor)` — 아이콘 + 설명 + 체크 행

#### 4-4. 학부모 홈 정리

- "📥 통신문 직접 올리기" 버튼 제거 (미구현 기능 노출 차단)

---

## 최종 시연 플로우

```
[선생님 앱]
  1·우리반 홈
    ↓ 새 통신문
  2·통신문 작성 (HWP/PDF 업로드 → "24명에게 발송" 버튼)
    ↓ 발송
  3·발송 완료 (FCM/TTS/9개 언어/340개 용어사전 확인)
    ↓ 회신 현황
  4·회신 현황 트래킹

[학부모 앱]
  1·홈 (FCM 푸시 수신)
    ↓ 탭하여 열기
  2·통신문 원문 (한국어 원문 + AI 번역하기 CTA 카드)
    ↓ AI 번역하기 탭 → 자동 처리 (POST /notice/analyze/{id})
  3·AI 번역 결과 (베트남어 번역 + TTS + 카테고리 카드)
    ↓ 회신하기 탭
  4·회신 작성
    ↓ 일정 탭
  5·일정 + 준비물 체크
```

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `android/design_reference/teacher.html` | 플로우 재편 (5화면→4화면), 스텝바 축소, 발송완료 화면 신규 |
| `android/design_reference/parent.html` | Screen 6 제거 (5화면), 언어 수 3곳 8→9 수정 |
| `demo/index.html` | 헤더 언어 수 8→9 |
| `android/app/src/main/java/com/multicultural/demo/MainActivity.java` | 색상 토큰 업데이트, AI CTA 카드, 발송완료 화면, 불필요 버튼 제거 |

---

## 빌드 및 테스트

Android Studio에서 **Ctrl+F9** (Make Project)로 빌드.  
터미널 빌드(`gradlew`)는 Android Studio가 `app/build/` 디렉터리를 점유하는 동안 `AccessDeniedException` 발생.

검증 항목:
- [ ] 선생님: HWP 업로드 → 발송 → 발송완료 화면 전환 확인
- [ ] 선생님: 텍스트 직송 → 발송 → 발송완료 화면 전환 확인
- [ ] 학부모: 통신문 선택 → AI CTA 카드 표시 → 탭 시 번역 화면 확인
- [ ] 학부모: 홈 화면 "통신문 직접 올리기" 버튼 없음 확인
- [ ] 색상: 앱 전반 인디고 계열 적용 확인 (파란색 잔재 없는지)
- [ ] HTML: teacher.html 브라우저에서 4화면 확인
- [ ] HTML: parent.html 브라우저에서 5화면 확인

---

## 다음 작업 후보

- [ ] Android 빌드 후 실기기 시연 검증
- [ ] teacher.html 탭바 active 인덱스 각 화면별 정합성 확인 (작성=index 1, 현황=index 2)
- [ ] showAIOverlay 화면 상단 caption "✨ AI 분석 결과" 바이올렛(`COLOR_AI`) 색상 적용
- [ ] 발송완료 화면에서 실제 학부모 수(N명)를 API 응답에서 읽어 칩에 반영
