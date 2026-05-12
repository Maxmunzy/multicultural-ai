# 팀 진행 브리프

## 현재 프로젝트 한 줄 설명

SchoolBridge — 선생님이 보낸 가정통신문에서 학부모가 해야 할 일을 뽑고, 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 언어별 음성 안내까지 이어 주는 탑재형 AI 도우미 MVP.

```text
선생님 Android 화면  (X-User-Id: teacher_xxx)
  -> POST /notice/send / upload (teacher 권한 검증)
FastAPI 서버 (NCP Seoul VM 101.79.17.196:8000)
  -> FCM 푸시 알림 → 학부모 수신함
학부모 Android 화면  (X-User-Id: parent_xxx)
  -> GET /notice/inbox/{parent_id}
  -> POST /notice/analyze/{notice_id} (target_language 지정)
분석 결과
  -> 체크리스트 카드 + info_cards(준비물·비용·제출) + calendar_events
  -> 선택 언어 번역 + TTS 재생 + STT 음성 질문
```

---

## 탑재형 AI 도우미 모듈

이 프로젝트의 핵심은 기존 학교 알림장/가정통신문 서비스(학교종이·하이클래스·e알리미 등)가 가져다 쓸 수 있는 AI 도우미 모듈을 만드는 것입니다. Android 앱은 이 모듈의 동작을 보여 주기 위한 실기기 데모 클라이언트입니다.

---

## 역할 분담

| 이름 | 담당 | 주요 위치 |
| --- | --- | --- |
| 태수 | FastAPI 서버, API 설계, Android 통신, NCP 배포 | `backend/` |
| 윤정 | 주요 내용 추출 모델 (KoELECTRA, 47,148행) | `model/extraction/` |
| 경이 | 카테고리 분류 모델 (KcELECTRA v3, 15,948행) | `model/classification/` |
| 세종 | NLLB 번역·글로사리·TTS/STT·OCR·info_cards·캘린더 다국어 | `model/translation_tts/`, `backend/app/services/`, `android/` |
| 찬영 | 가정통신문 3,300장 수집, 발표 자료 | `docs/` |

---

## 현재 구현 상태 (2026-05-12 갱신)

| 영역 | 상태 | 메모 |
| --- | --- | --- |
| Backend | ✅ 완료 | FastAPI, Docker, NCP Seoul VM(101.79.17.196:8000). `/notice/{send,upload,upload-self,inbox,analyze}`, `/tts`, `/user`, `/health`, `/notice/glossary/unknown`. X-User-Id 헤더 역할 인증 |
| Android | ✅ 완료 + 실기기 안정화 | Java 단일 Activity. 선생님 화면(PDF/HWP/이미지 업로드), 학부모 홈(카메라 OCR, 수신함, AI 분석, 달력, 미니달력, 체크리스트). FCM 푸시 알림. 9개 언어 UI 전면 현지화 |
| 데이터 | ✅ 완료 | 원본 3,300장+(찬영), KoELECTRA 학습 47,148행(윤정), KcELECTRA 학습 15,948행(경이), 글로사리 340+항목(세종) |
| 파일 입력 | ✅ 완료 | HWP/PDF/text/이미지 → clean_text. LibreOffice + H2Orestart + 한글폰트. 원본 raw bytes 보존 → 학부모 풀화면 조회 |
| sentence_list 정제 | ✅ 완료 | Claude Haiku 4.5 — 가정통신문을 문장 단위로 분해하고 role_hint(13종) 태깅. 단일 호출로 cleaned_text + sentence_list 동시 반환 |
| 추출 모델 | ✅ 완료 | 윤정 KoELECTRA (`yunjeong116/koelectra-extractor`). 테스트 Recall 0.868 (+11.2%p). HF Hub 자동 로드 |
| 분류 모델 | ✅ 완료 | 경이 KcELECTRA v3 (`kysophia/kcelectra-category`). Macro F1 0.8374 (Simple 베이스라인 0.7590 대비 +10.3%). HF Hub 자동 로드 |
| 번역·글로사리 | ✅ 완료 | NLLB-600M + 글로사리 340+항목. Slot Protection(날짜·금액·URL 마스킹) + Glossary Injection. 용어 보존율 1/17→17/17 |
| info_cards | ✅ 완료 | 준비물·비용·제출 전용 카드. 준비물 checklist 항목별 체크박스. 괄호 내 세부 품목 자동 분리 |
| calendar_events | ✅ 완료 | 일정·신청기간·기한 달력 자동 표시. 달력/미니달력 9개 언어 현지화. 팝업 내용 번역 |
| TTS / STT | ✅ 완료 | Edge-TTS 9보이스, 속도 조절(단어별/천천히/오리지날). STT 음성 질문 9언어×6카테고리(주제/준비물/일정/비용/제출/건강). info_cards 탐색 포함 |
| 미등록 용어 감지 | ✅ 완료 | 번역 중 글로사리 미스 자동 수집 → `GET /notice/glossary/unknown` API |
| self_test | ✅ 125+ ALL PASS | 번역 slot 복원, 글로사리 주입, 날짜 파싱, 달력 이벤트 등 |
| OCR | ✅ 완료 | ML Kit Korean OCR + OpenCV 4종 전처리 + 2-pass 표 재인식 + Quality Gate(0.80) |
| 앱 아이콘 | ✅ 완료 | SchoolBridge 로고 mipmap 5밀도(mdpi~xxxhdpi) |

---

## 모델 파이프라인 v3 (2026-05-12 기준)

```text
POST /notice/analyze/{notice_id}  (target_language)
        ↓
[1] Claude Haiku 4.5
    통신문 전체 텍스트 → sentence_list (role_hint 13종 태깅) + cleaned_text
    role_hint: supplies / fee / submit / event_datetime / application_period
               application_url / contact / target / location / result_announcement
               content / program_title / etc
        ↓
[2] 윤정 KoELECTRA binary
    is_action_candidate 문장 → list[YunjeongTodo]  (할일 문장 + due_date/amount)
        ↓
[3] 경이 KcELECTRA v3
    각 todo의 카테고리 6분류 (일정/준비물/제출/비용/건강·안전/기타)
        ↓
[4] 세종 NLLB-200 + 글로사리
    Slot Protection → Glossary Injection → NLLB → Placeholder 복원
        ↓
[5a] card_builder → 체크리스트 카드 (행동 문장 기반)
[5b] info_card_builder → info_cards (role_hint supplies/fee/submit/event_datetime 등)
[5c] calendar_event_builder → calendar_events (날짜 파싱 + target_lang 번역)
        ↓
[6] Edge-TTS → 선택 언어 mp3
        ↓
Android: 카드 UI + 달력 + 체크리스트 + TTS/STT
```

**LLM 1단계 비교 (Claude Haiku 채택 배경)**

| 방식 | 처리 시간 | 안정성 | 비용 |
|---|---|---|---|
| 정규식 only | 0초 | 레이아웃 변형에 취약 | 0원 |
| Ollama qwen2.5:3b (로컬) | 2분 31초+ | 비결정성·CPU 한계 | 0원 |
| **Claude Haiku 4.5** | **8~16초** | **JSON 출력 안정** | 호출당 ~$0.1 |

---

## 정량 결과 요약

| 항목 | 결과 |
| --- | --- |
| KoELECTRA 추출 Recall | **0.868** (v1 0.756 대비 +11.2%p) |
| KcELECTRA 분류 Macro F1 | **0.8374** (Simple 베이스라인 0.7590 대비 +10.3%) |
| 글로사리 용어 보존율 | **37/37** (적용 전 1/37) |
| NLLB 번역 품질 (Gemini 평가) | **89.6점** (용어사전 적용 전 39점) |
| Slot 복원 | **21/21 PASS** |
| self_test | **125+ ALL PASS** |

---

## 개선 방향 (발표 후)

1. Claude Haiku 1단계 → 자체 경량 모델로 대체 (비용·독립성)
2. 학습 데이터 확보로 KoELECTRA·KcELECTRA 성능 추가 향상
3. STT 질의 → 체크리스트·달력·슬롯 카드 직접 연결 강화
4. 학부모·교사 쌍방향 소통 채널

---

## 발표용 핵심 문장

선생님이 가정통신문을 보내면 학부모 앱에서 핵심 체크리스트·준비물·일정·비용 카드와 쉬운 한국어·모국어 번역(8개국어)·음성 안내를 확인할 수 있습니다. KoELECTRA 추출 모델·KcELECTRA 분류 모델·NLLB+글로사리 번역 파이프라인이 모두 메인 백엔드에 연결되어 실기기 E2E 동작이 검증된 상태이며, self_test 125건 ALL PASS입니다.
