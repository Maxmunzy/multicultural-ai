# 2026-05-27 워크로그 — Android 앱 demo HTML 전면 반영

**작성일:** 2026-05-27  
**작성자:** jyj  
**작업 범위:** `android/app/src/main/java/com/multicultural/demo/MainActivity.java`  
**브랜치:** `feature/yunjeong-extraction-v5`

---

## 한 줄 요약

demo HTML(teacher.html 4화면 · parent.html 5화면)에 정의된 UI/UX를 Android MainActivity.java에 전면 반영. 선생님 Screen 1(우리반 홈 대시보드)이 미구현 상태였으므로 신규 추가하고, 나머지 화면은 디자인 갭을 해소했다.

---

## 작업 배경

이전 세션(2026-05-23)에서 demo HTML 플로우 교정 + 디자인 토큰 적용까지 완료했으나, Android 앱 화면이 demo와 여전히 달랐다:

- 선생님 진입 시 바로 "작성 화면"이 열림 → demo Screen 1(우리반 홈)이 없었음
- 학부모 홈에 hero 카드·통계·다가오는 일정 없음
- 선생님 발송완료 화면이 인디고 hero 카드 없이 칩 행만 나열

---

## 작업 내용

### 1. 선생님 Screen 1 — `showTeacherDashboard()` 신규 (L602)

demo teacher.html Screen 1 전체를 Android로 구현. `buildScreen`이 FAB 오버레이를 지원하지 않아 `FrameLayout` 직접 구성.

**구성 요소:**

| 요소 | 설명 |
|---|---|
| 인디고 hero 카드 `teacherHeroCard()` | `COLOR_PEACH_DEEP → COLOR_PEACH_INK` 그라디언트, "학생 24명", KO12/VN5/CN4/EN2/TH1 언어 칩 |
| 긴급 할 일 카드 `urgentTaskCard()` | 흰 카드 + COLOR_PEACH 테두리, 💬 아이콘 박스, 회신 현황·D-2 칩 |
| 최근 통신문 행 `noticeHistoryRow()` | 색상 아바타 + 제목/메타 + 배지 칩 |
| FAB ✏️ | 54dp, `COLOR_PEACH_DEEP`, BOTTOM|END → `showTeacherHome()` |
| 탭바 | `makeBottomTabBar(0, false)` — 우리반 active |

### 2. 선생님 Screen 2 — `showTeacherHome()` 개편 (L837)

기존 단순 입력 폼 → demo Screen 2 스펙으로 전면 교체. 기존 업로드·발송 로직(`uploadSelectedFile`, `sendNotice`)과의 호환성 유지.

**주요 변경:**

| 항목 | 이전 | 변경 후 |
|---|---|---|
| 화면 상단 | 없음 | `buildStepBar(1)` — 작성(●)/발송(○) 2단계 바 |
| 받는 학부모 | 별도 카드 | 인라인 수신인 행 `recipientRow` |
| 업로드 영역 | 단순 버튼 | `buildUploadZone()` — 대시 테두리, 파일 타입 칩, ⬆ 아이콘 |
| AI 안내 | 없음 | `buildAIAssistBanner()` — 바이올렛 배너, "9개 언어 번역·TTS" |
| 액션 바 | 단일 "발송" 버튼 | "임시저장" outline + "24명에게 발송" primary |

신규 헬퍼 메서드: `buildStepBar`, `stepNode`, `buildUploadZone`, `buildAIAssistBanner`

### 3. 선생님 Screen 3 — `showTeacherSendComplete()` hero 카드 추가 (L3432)

demo teacher.html Screen 3의 인디고 hero 그라디언트 카드가 미반영된 상태였음.

**변경:**
- `buildScreen` subtitle 제거 → `sendCompleteHeroCard()` 첫 content 항목으로 추가
- 기존 두 줄 칩 행(FCM·9개 언어·TTS·용어사전·Claude Haiku) 제거 → hero 카드 내 흰색 칩으로 통합
- hero 카드 구성: `COLOR_PEACH_DEEP → COLOR_AI` 그라디언트, "24명 발송"/"FCM 푸시 전송" 상단 칩, "학부모 앱으로 전달됐습니다" 22sp bold, #C7D2FE 부제, 하단 "9개 언어"/"자동 번역"/"TTS 음성"/"일정 추출" 칩

### 4. 학부모 Screen 1 — `showParentHome()` 강화 (L1253)

demo parent.html Screen 1의 누락된 3개 구성요소 추가.

| 신규 요소 | 메서드 | 내용 |
|---|---|---|
| Hero 카드 | `parentHeroCard()` | `COLOR_PEACH_DEEP → COLOR_AI`, "회신 필요·D-2" + "✨ AI 번역됨" 칩, "지금 회신하기 →" CTA |
| 다가오는 일정 | `upcomingEventCard()` | 44dp 날짜 박스(5월/16), 행사명·시간, D-2 칩 |
| 통계 스트립 | `parentStatsStrip()` | 3열: 47건 받은통신문 / 9개 지원언어 / 340개 학교용어사전 |

### 5. 내비게이션 수정

| 위치 | 이전 | 변경 후 |
|---|---|---|
| 로그인 (L398) | `showTeacherHome()` | `showTeacherDashboard()` |
| 자동로그인 (L~5273) | `showTeacherHome()` | `showTeacherDashboard()` |
| 탭바 index 0 선생님 (L4592) | 없음 | `showTeacherDashboard()` |
| 탭바 index 1 선생님 (L4595) | 없음 | `showTeacherHome()` |
| 발송완료 "← 홈으로" (L3455) | `showTeacherHome()` | `showTeacherDashboard()` |

---

## 최종 화면 매핑

```
[선생님] demo ↔ Android
  Screen 1  우리반 홈        ← showTeacherDashboard()   ✅ 신규 구현
  Screen 2  통신문 작성       ← showTeacherHome()         ✅ 전면 개편
  Screen 3  발송 완료        ← showTeacherSendComplete()  ✅ hero 카드 추가
  Screen 4  회신 현황        ← (출시 예정 notImplementedToast)  ⚠️

[학부모] demo ↔ Android
  Screen 1  홈              ← showParentHome()           ✅ hero·통계·일정 추가
  Screen 2  원문 + AI CTA   ← showNoticeDetail()         ✅ (2026-05-23 완료)
  Screen 3  AI 번역 결과    ← showAIOverlay()            ✅
  Screen 4  회신 작성       ← showAIOverlay() bottomActionsBar  ✅
  Screen 5  일정+준비물     ← ChecklistActivity          ✅
```

---

## 신규/변경 헬퍼 메서드 목록

| 메서드 | 위치 | 용도 |
|---|---|---|
| `showTeacherDashboard()` | L602 | 선생님 Screen 1 진입점 |
| `teacherHeroCard()` | L683 | 선생님 홈 인디고 히어로 카드 |
| `heroChipWhite(label)` | L719 | 그라디언트 카드 위 흰 배지 칩 |
| `urgentTaskCard()` | L734 | 오늘 할 일 긴급 카드 |
| `noticeHistoryRow(...)` | L782 | 최근 통신문 목록 행 |
| `buildStepBar(step)` | L998 | 작성/발송 2단계 진행 바 |
| `stepNode(...)` | L1020 | 스텝바 단일 노드 |
| `buildUploadZone()` | L1051 | HWP·PDF 업로드 대시 영역 |
| `buildAIAssistBanner()` | L1100 | 바이올렛 AI 자동 번역 안내 배너 |
| `parentHeroCard()` | L1289 | 학부모 홈 히어로 카드 |
| `upcomingEventCard()` | L1345 | 다가오는 일정 날짜 카드 |
| `parentStatsStrip()` | L1393 | 통계 3열 스트립 |
| `sendCompleteHeroCard()` | L3478 | 발송완료 인디고 히어로 카드 |

---

## 변경 파일

| 파일 | 변경 내용 |
|---|---|
| `android/app/src/main/java/com/multicultural/demo/MainActivity.java` | showTeacherDashboard 신규, showTeacherHome 개편, showParentHome 강화, showTeacherSendComplete hero 카드, 내비게이션 수정 |

---

## 빌드 및 검증

Android Studio **Ctrl+F9** (Make Project). `gradlew`는 Studio가 `app/build/`를 점유하는 동안 AccessDeniedException 발생.

### 검증 체크리스트

**선생님 플로우:**
- [ ] 로그인 → 우리반 홈(Screen 1) 진입 확인
- [ ] 탭바 "우리반(0)" → showTeacherDashboard, "작성(1)" → showTeacherHome
- [ ] 우리반 홈 FAB ✏️ → 작성 화면 전환
- [ ] 작성 화면 스텝바 표시 확인
- [ ] 업로드존 탭 → 파일 선택기 열림
- [ ] "24명에게 발송" → 발송완료(Screen 3) 전환
- [ ] 발송완료 화면에 인디고 hero 카드 표시
- [ ] "← 홈으로" → 우리반 홈 복귀

**학부모 플로우:**
- [ ] 학부모 홈에 hero 카드·다가오는 일정·통계 스트립 표시
- [ ] "지금 회신하기 →" → 첫 번째 수신함 항목 또는 toast
- [ ] 통신문 선택 → AI CTA 카드 → AI 번역 결과 화면

---

## 다음 작업 후보

- [ ] 빌드 후 실기기에서 전 화면 시연 검증
- [ ] 선생님 회신 현황 화면 구현 (현재 출시 예정 toast)
- [ ] `noticeHistoryRow` 실제 API 데이터 연동 (현재 하드코딩 샘플)
- [ ] `parentHeroCard` + `upcomingEventCard` 수신함 첫 번째 항목 데이터 연동
