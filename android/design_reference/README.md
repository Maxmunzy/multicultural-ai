# Handoff: 다온 (Daon) — 다문화가정 가정통신문 번역 앱

## Overview
다온은 다문화가정 학부모와 학교 교사를 잇는 양방향 번역 앱입니다.
- **학부모**: 한국어 통신문을 모국어로 번역해서 받고, 회신은 모국어로 작성하면 한국어로 자동 변환되어 전송됩니다.
- **교사**: 한 번 한국어로 작성하면 학부모 각자의 모국어로 자동 번역되어 발송됩니다.

지원 언어 (9): 한국어, 베트남어, 중국어, 영어, 러시아어, 태국어, 몽골어, 일본어, 말레이시아어.

## About the Design Files
이 패키지의 파일들은 **HTML로 만든 디자인 레퍼런스**입니다 — 의도한 외관과 동작을 보여주는 프로토타입이지, 그대로 복사해서 쓸 프로덕션 코드가 아닙니다.

작업의 본질은 이 HTML 디자인을 **타겟 코드베이스의 기존 환경(React Native, Flutter, SwiftUI, native Android 등)에 맞게 재구현**하는 것입니다. 환경이 아직 없다면 프로젝트에 가장 적합한 프레임워크를 선택해서 구현하세요. 모바일 앱(iOS/Android) 타겟이므로 React Native + Expo 또는 Flutter가 자연스러운 선택입니다.

번역 엔진은 **온디바이스 AI 모델**을 탑재해 사용할 예정이므로, UI는 빠른 응답을 가정하고 설계되었습니다.

## Fidelity
**High-fidelity (hifi)** — 파스텔 일러스트 톤의 픽셀 단위 시안. 최종 색상, 타이포그래피, 간격, 카드 스타일이 모두 의도된 값입니다. 코드베이스의 기존 라이브러리/패턴으로 픽셀 퍼펙트하게 재구현하세요.

## Design Tokens

### Colors (CSS variables in `daon-shared.css`)
```
--peach:       #ffd9c2   /* 메인 강조 (회신 필요, primary CTA bg) */
--peach-deep:  #ff9d6e
--peach-ink:   #b35a2b   /* peach 카드 안의 텍스트 */
--mint:        #c8ecd9   /* 동의/완료/긍정 */
--mint-deep:   #6fcfa1
--mint-ink:    #2f7a55
--lemon:       #ffeaa3   /* 사전/하이라이트/팁 */
--lemon-deep:  #ffd45e
--lemon-ink:   #8a6a14
--lavender:    #e3dcfb   /* 일정/날짜 카드 */
--sky:         #d4ebff   /* 음성 입력 등 보조 */
--paper:       #fffaf3   /* 화면 배경 */
--paper2:      #fff3e6   /* 입력란/세컨더리 배경 */
--ink:         #2b2018   /* 본문 텍스트 / 다크 CTA */
--ink2:        #5a4a3d   /* 보조 본문 */
--ink3:        #8a7c70   /* 캡션/라벨 */
--ink4:        #c4b6a8   /* placeholder */
--line:        #ead9c4
```

전역 배경: `linear-gradient(135deg, #ffe8d4 0%, #d8f0e4 50%, #fff5cc 100%)`

### Typography
- Font: **Pretendard Variable** (한국어 + 베트남어 다국어 지원)
- 크기 스케일:
  - title-xl: 26px / 800 / -0.02em / line-height 1.15
  - title-lg: 20px / 700 / -0.02em
  - title-md: 16px / 700 / -0.01em
  - title-sm: 14px / 600 / -0.01em
  - body: 13px / 400 / line-height 1.5
  - caption: 11px / 500
  - section-label: 11px / 600 / uppercase / letter-spacing 0.06em

### Spacing & Radius
- Card radius: **18px** (메인), 14px (작은), 12px (날짜 박스)
- Button radius: 14px (사각), 999px (pill)
- Phone radius: 48px outer / 42px screen
- Card padding: 14px (default), 16-18px (hero)
- Card gap: 8px (리스트 항목 사이)

### Shadows
- Card: `0 2px 6px rgba(70, 40, 20, 0.04)`
- Floating button: `0 8px 20px rgba(70, 40, 20, 0.3)`
- Phone: `0 30px 60px -15px rgba(70, 40, 20, 0.25)`
- Pill (lang): `0 2px 8px rgba(60, 40, 20, 0.06)`

## Screens / Views

### 학부모용 (parent.html) — 5 screens

**1. 홈 — 받은 통신문**
- 인사말 + 사용자 이름 (큰 타이틀, 우측에 언어 드롭다운 공간 130px 비워둠)
- Hero card (peach): 가장 시급한 회신 필요 통신문 (D-2 칩, 모국어 제목, 한국어 부제, 본문 요약, "지금 회신하기" 버튼)
- "새 통신문 N" 섹션: 카드 리스트 (avatar 이모지 + 모국어 제목 + 한국어 부제 + 미읽음 점)
- "곧 다가오는 일정" 섹션: mint 카드 (날짜 박스 + 일정명)
- 하단 탭바 5개: 홈 / 번역 / 일정 / 회신 / 나

**2. 번역 결과**
- 뒤로 + "통신문 #142" 캡션
- 모국어 제목 + 한국어 부제
- 세그먼티드 컨트롤: 한국어 / ↔ 나란히 / 모국어 (현재 활성)
- White card: 번역된 본문, 학교 용어는 lemon highlight inline
- Lemon card: 학교 용어 사전 ("…란?" + 한국어 풀이)
- 하단 액션 3개: 🔊 듣기 / 📅 일정 추가 / ↩ 회신 (peach)

**3. 회신 작성**
- "답장 작성 → 김선생님께" 헤더
- "빠른 답변" 섹션: mint(동의)/white(불참)/white(질문) 3장 — 선택된 카드는 mint 배경 + 우측에 mint-ink ✓
- "전송될 한국어" 미리보기: lemon card에 학생 이름과 일정명을 굵게
- 하단 풀폭 peach 버튼: "김선생님께 전송 →"

**4. 일정 + 준비물**
- 월 표시 + "Lịch lớp học" 큰 제목
- 가로 스크롤 7일 스트립 (오늘은 ink 배경 + white)
- Peach hero card: 시간/일정명/장소/D-2 칩 + 내부 white-overlay 박스에 4개 준비물 체크리스트 (✓는 mint-deep + 취소선)
- 다음 주 일정: lavender 날짜 박스 + 일정 카드

**5. 통신문 추가**
- "어떻게 받으셨나요?" 큰 제목
- 2x3 그리드 (aspect-ratio: 1): 사진찍기(peach) / 갤러리(mint) / PDF(lemon) / 붙여넣기(lavender) / 음성(sky) / 학교 연동(dashed border, 곧 출시)
- 각 카드: 큰 이모지 + 제목 + 캡션
- 하단 paper2 카드: 💡 안내 메시지

### 교사용 (teacher.html) — 5 screens

**1. 우리반 홈**
- 인사 + 김선생님 ✏️
- Mint hero card: "우리 반" + 학교/반 + 학생 수 + 5개 언어 분포 chip (KR 12, VN 5, CN 4, US 2, TH 1)
- "오늘 할 일": peach card에 ⚡ 아이콘 + 진행중인 회신 수 + D-2
- "최근 발송한 통신문" 리스트: avatar 이모지 + 제목 + "5개 언어 · 24명 발송 · 날짜" + 회신 수 chip
- Floating ✏️ FAB: 60px ink 배경, 우하단 (탭바 위 100px)
- 탭바: 우리반 / 작성 / 현황 / 답장 / 나

**2. 통신문 작성**
- 가로 스크롤 템플릿 chip 5개 (현장학습 활성 = peach)
- White card: 제목 입력
- White card: 내용 입력 (한국어로 작성, 학교/날짜 굵게)
- Lemon card: ✨ "AI가 도와드릴까요?" 제안
- "자동 추출됨" 칩 그리드: 날짜(mint) / 장소(mint) / 마감(peach) / 준비물(lemon)
- 하단: 미리보기(white) + 번역해서 발송(ink primary)

**3. 번역 미리보기**
- "5개 언어로 번역됨" 큰 제목
- 가로 스크롤 언어 탭 (활성 = ink): 🇰🇷 12명, 🇻🇳 5명 등 학생 수 표시
- White card: 선택된 언어로 번역된 전체 본문 (학부모가 보는 그대로)
- Mint card: ✓ "자연스러운 번역 확인됨" + 사전 적용 개수
- "사용된 학교 용어" lemon chip: "현장체험학습 → dã ngoại học tập"
- 하단: 수정 + 24명에게 발송(mint)

**4. 회신 현황**
- Peach hero: 22/24, 92%, 진행 바 (peach-ink)
- 3-grid 통계 카드: 동의(mint, 20) / 불참(#fde2e2 + #b34a4a, 2) / 대기(lemon, 2)
- "⏰ 아직 회신 없음" 리스트: lavender avatar + 학생명 + 국기 + "읽음 시간" + "알림" 버튼
- "최근 회신" 리스트: mint avatar + 학생명 + 국기 + 동의/시간 + ✓ chip

**5. 학부모 답장 받기**
- 헤더: 학생 정보 (peach avatar + 한국어 이름 + 국기 + 모국어)
- 채팅 스레드:
  - 받은 메시지(peach card, 좌측 정렬, border-radius 16/16/16/4): VI 원문 (italic) → 구분선 → KR 자동 번역 (굵게) + 🔊
  - 보낸 메시지(mint card, 우측 정렬, border-radius 16/16/4/16): 한국어 원문 → 구분선 → VI 학부모가 받은 번역 (italic)
- 하단 입력바: + 버튼 / paper2 input / ↑ ink 전송 버튼

## 공통 컴포넌트

### Phone frame
- 320 × 680, outer radius 48px, padding 8px, ink #1a1410 배경
- Dynamic island: 100×28, 상단 18px, ink black
- Home indicator: 134×5, ink 25% opacity
- Status bar: 54px, 9:41 + signal/battery SVG icons

### Lang Pill (모든 화면 우상단 고정)
- position: absolute, top: 64px, right: 16px
- 흰 반투명 배경 + backdrop blur
- 22×22 lemon flag circle + 언어명 + ▾ chevron
- white-space: nowrap

### Tab Bar
- 78px 높이, paper 92% + blur, 1px 상단 보더
- 5개 탭: 28×28 ic + 10px 라벨
- 활성 탭: peach 배경 사각 (10px radius) + peach-ink 텍스트

### Card variants
`.card` (기본 white) / `.peach` / `.mint` / `.lemon` / `.lavender` / `.sky`
모든 컬러 카드는 동일 색상의 deep 버전과의 135deg 그라데이션.

### Chips
`.chip` (white 기본), 컬러 변형은 카드와 동일. font-size 11, padding 4×10, radius 999.

## Interactions & Behavior
- 언어 드롭다운: 탭하면 9개 언어 리스트 모달, 선택 즉시 모든 텍스트 재번역 (온디바이스 AI 가정)
- 통신문 추가 → 처리 중 진행 표시 → 번역 결과로 자동 이동
- 회신 빠른 답변 선택 → 한국어 미리보기 자동 갱신 → 전송
- 교사 작성 → 5개 언어 미리보기 → 발송
- 채팅에서 메시지 입력 시: 입력은 받는 사람 모국어 / 표시는 양국어 동시
- TTS: 모국어/한국어 양쪽 모두 재생 가능

## State Management
- currentUserRole: 'parent' | 'teacher'
- currentLanguage: 'ko' | 'vi' | 'zh' | 'en' | 'ru' | 'th' | 'mn' | 'ja' | 'ms'
- notices: { id, title_ko, body_ko, translations, sentAt, replyDeadline, requiresReply, attachments[], extractedEvents[], extractedSupplies[] }
- replies: { noticeId, parentId, choice, customMessage, sentAt, readAt }
- classRoster (teacher): { studentId, name_ko, parentLanguage, parentName }
- 온디바이스 번역 모델 호출은 비동기지만 빠르므로 낙관적 업데이트 가정

## Assets
- **Pretendard Variable** font: `https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.css` — 한국어/베트남어/한자 모두 처리
- 이모지는 시스템 이모지 사용 (별도 아이콘 에셋 없음)
- 일러스트는 카드 색상 그라데이션 + blob blur로 표현 (별도 아트워크 없음)

## Files (in this bundle)
- `parent.html` — 학부모용 5개 화면 시연 캔버스 (좌우 스크롤)
- `teacher.html` — 교사용 5개 화면 시연 캔버스
- `daon-shared.css` — 공용 토큰, 컴포넌트 클래스
- 두 HTML 모두 우상단에 역할 전환 토글 포함 (학부모 ↔ 선생님)

## Notes
- 색상은 채도가 낮은 파스텔이라 인쇄/저DPI 화면에서도 잘 보입니다
- 다국어 텍스트(특히 베트남어 성조 표기)는 Pretendard가 처리하므로 별도 폰트 fallback 불필요
- 시연용 캔버스이므로 화면 간 전환은 정적 — 실제 구현 시 React Navigation 등으로 연결 필요
- 학교 용어 사전, 회신 템플릿은 데이터 시드가 필요함 (별도 시딩 작업)
