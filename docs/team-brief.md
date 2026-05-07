# 팀 진행 브리프

## 현재 프로젝트 한 줄 설명

가정통신문 AI 도우미는 선생님이 보낸 안내문에서 학부모가 바로 확인해야 할 일을 뽑고, 쉬운 한국어 + 8개국어(베트남어/영어/러시아어/말레이시아어/몽골어/중국어/태국어/일본어) 번역과 언어별 음성 안내까지 이어 주는 MVP입니다.

현재 저장소 기준 핵심은 다음 흐름입니다.

```text
선생님 Android 화면  (X-User-Id: teacher_xxx)
  -> POST /notice/send (teacher 권한 검증)
FastAPI 서버
  -> 임시 메모리 저장
학부모 Android 화면  (X-User-Id: parent_xxx)
  -> GET /notice/inbox/{parent_id} (본인만)
  -> POST /notice/analyze/{notice_id} (target_language 지정)
분석 결과
  -> 체크리스트, 쉬운 한국어, 선택 언어 번역, 용어 검수, 언어별 TTS 재생
```

Android 앱은 모델을 직접 실행하지 않습니다. 서버 API를 호출하고, 서버 응답이 없거나 TTS URL이 없을 때는 앱에 포함된 고정 데모 산출물을 fallback으로 보여 줍니다.

`/notice/*` 엔드포인트는 모두 `X-User-Id` 헤더로 요청자를 식별하고 역할(teacher/parent) 권한을 검증합니다. MVP 단계라 토큰 없이 헤더 한 줄로 처리하며, 시드 계정은 `teacher_001/002`와 `parent_001/002/003`입니다.

---

## 탑재형 AI 도우미 모듈

이 프로젝트의 핵심은 새로운 알림장 앱 자체를 만드는 것이 아니라, 기존 학교 알림장/가정통신문 서비스가 가져다 쓸 수 있는 AI 도우미 모듈을 만드는 것입니다. Android 앱은 이 모듈의 동작을 보여 주기 위한 실기기 데모 클라이언트입니다.

서버와 모델 파이프라인은 가정통신문 텍스트와 학부모가 선택한 언어 코드(target_language)를 받아 체크리스트, 쉬운 한국어, 선택 언어 번역(8개국어 중 1), 용어 검수 결과, 해당 언어 TTS 음성을 만들어 반환합니다. 이후에는 기존 학교 앱이나 알림장 서비스가 같은 API를 호출하는 방식으로 확장할 수 있습니다.

---

## 역할 분담

| 이름 | 담당 | 주요 위치 |
| --- | --- | --- |
| 태수 | FastAPI 서버, API 설계, Android 통신 연결 | `backend/` |
| 윤정 | 중요 문장 추출 모델 | `model/extraction/` |
| 경이 | 카테고리 분류, 중요도 모델 | `model/classification/` |
| 세종 | NLLB 번역, 학교 용어사전 검수, Edge-TTS 출력, OCR bbox/slot 보정 실험 | `model/translation_tts/`, `backend/app/services/ocr_slot_corrector.py`, `docs/experiments/` |
| 찬영 | Android 실기기 데모, UI, 발표 자료 | `android/`, `docs/` |

---

## 현재 구현 상태 (2026-05-07 갱신)

| 영역 | 상태 | 메모 |
| --- | --- | --- |
| Backend | 완료 + **HF Spaces 배포** | FastAPI, Docker, `/notice/{send,upload,upload-self,inbox,analyze}`, `/tts`, `/user`, `/health`. X-User-Id 헤더 + 역할 권한. v2 슬롯 응답(`summary` + `items`). **Notice 스키마에 `original_file_url`/`original_filename`/`mime_type` 필드 추가**. 실서버: `https://maxmunzy-schoolbridge.hf.space` (CPU basic, 24/7) |
| Android | 완료 + 실기기 OCR 안정화 | Java 단일 Activity. 선생님 화면 PDF/HWP/이미지 업로드, 학부모 홈 카메라 OCR(ML Kit Korean), **알림 카드 클릭 → 원본 PDF/이미지 풀화면(PdfRenderer + ImageView)**, 우상단 ✨ AI → 분석 화면. 2026-05-07 실기기에서 `사진 촬영 → OCR 결과 확인 → 그래도 전송 → 업로드 → AI 번역 시연` 성공. OpenCV native 로딩 실패 시 원본 ML Kit OCR로 fallback |
| 데이터 | 완료 | `v3_dual_labeled.jsonl` 28,890행 (이중 라벨: is_todo + is_title). 분류 학습용 `notice_sample_v5_clean_full.csv` 4,992행 (수동 142 + Haiku 자동 4,850) |
| 파일 입력 | 완료 | `services/parser.py` — HWP/PDF/text/이미지 → clean_text. LibreOffice + H2Orestart + 한글폰트 Dockerfile 영구. `POST /notice/upload` multipart. **원본 raw bytes는 `static/notices/{id}{ext}`에 보존되어 학부모가 풀화면으로 조회 가능** |
| OCR slot 보정 | PoC 완료 | `ocr_slot_corrector.py` — OCR 결과 중 날짜/시간/금액/학년/반/전화번호 slot 내부 confusable 문자만 보정. 합성 샘플 7건 기준 raw exact 1/7 → corrected 7/7. 실제 ML Kit OCR 결과 20~30줄로 확장 검증 예정 |
| URL/전화/slot 보호 | 완료 + 보강 | NLLB가 깨먹는 패턴 방어. `__SLOTn__` 계열 placeholder 복원 시 대소문자 변형(`__Slot1__`, `__SLOt2__`)과 내부 공백을 허용하고, 미복원 token은 화면에 노출하지 않도록 제거 |
| 번역 화면 노이즈 감소 | 진행 중 | OCR 실기기 결과에서 fallback 카드가 반복되어 `Khac:`가 많이 보이는 문제 확인. `기타` 카드 번역 header 비움, 긴 fallback 카드 trim, fallback 카드 최대 3개 제한 적용. NCP 반영 후 재검증 필요 |
| 번역/TTS | 완료 | NLLB 다국어 번역(vi/en/ru/ms/mn/zh/th/ja), 용어사전 검수, Edge-TTS 9개 보이스 매핑, 통화 오번역 후처리 |
| 추출 모델 | v2 연결 완료 | 윤정 KoELECTRA binary 추출 (`yunjeong116/koelectra-extractor`). 첫 호출 시 HF Hub 자동 다운로드 |
| 분류 모델 | **v3 연결 완료** | 경이 KcELECTRA v3 파인튜닝 (`kysophia/kcelectra-category` subfolder `kcelectra-category-v3`). **Macro F1 0.8545** (Simple 베이스라인 0.8116 대비 +4.29%p, 건강·안전 클래스 0.29 → 0.91 대폭 회복). 첫 호출 시 HF Hub fallback |
| 통합 E2E | 완료 | 백엔드 `/notice/upload` → 분석 → 슬롯 응답 → 안드 카드 UI + 원본 뷰어 흐름 코드 검증. HF Spaces 배포 후 실기기 테스트는 별도 IP 셋업 불필요 |

---

## 모델 파이프라인 기준 (v2 — 2026-04-29)

```text
호스트 앱 → POST /notice/upload (HWP/PDF/text) 또는 /notice/send (text)
        ↓
[1] services/parser.py — HWP/PDF/text → clean_text
        ↓
[2] slot_extractor — 정규식 dates/times/amounts/urls/phones (summary 재료)
        ↓
[3] 윤정 KoELECTRA binary → list[YunjeongTodo] (할일 문장 + due_date/amount/action_hint)
        ↓
[4] 경이 6-class 분류 → 각 todo의 카테고리 (일정/준비물/제출/비용/건강·안전/기타)
        ↓
[5] 세종 NLLB + 용어사전 + URL/전화 placeholder 보호 → 슬롯별 번역
        ↓
[6] _build_summary + _build_item — AnalyzeItem 결합 (summary 8슬롯 + items 리스트)
        ↓
[7] Edge-TTS → 선택 언어 mp3 생성
        ↓
Android 출력 (슬롯 칩 + 할일 카드 + TTS 재생)
```

기본 NLLB 모델은 `facebook/nllb-200-distilled-600M`, TTS는 언어별 보이스 매핑(`vi-VN-HoaiMyNeural`, `en-US-JennyNeural`, `ru-RU-SvetlanaNeural`, `ms-MY-YasminNeural`, `mn-MN-YesuiNeural`, `zh-CN-XiaoxiaoNeural`, `th-TH-PremwadeeNeural`, `ja-JP-NanamiNeural`, `ko-KR-SunHiNeural`)을 사용합니다.

---

## 다음 우선 과제

1. NCP 반영 후 같은 촬영본으로 번역 화면 재검증: `__Slot` 누수, `Khac:` 반복, 긴 기타 카드 감소 여부
2. 실제 ML Kit OCR 결과 20~30줄 수집 후 OCR slot 보정 평가셋 확장
3. OCR bbox/highlight PoC: 원본 문서 위 중요 문장 표시
4. 모델 튜닝: 체크리스트 정밀도 향상, NLLB 번역 품질 개선
5. 발표에서 E2E 파이프라인 시연 및 검수 루프 설명

---

## 발표용 핵심 문장

선생님이 가정통신문을 보내면 학부모 앱에서 핵심 체크리스트와 쉬운 한국어, 모국어 번역(8개국어 중 선택), 음성 안내를 확인할 수 있습니다. 추출 모델(KoELECTRA), 분류 모델(SBERT 기반), 번역/TTS 파이프라인(NLLB + Edge-TTS 9개 보이스)이 모두 메인 백엔드에 연결되어 실기기에서 E2E 동작이 확인된 상태입니다. 백엔드는 X-User-Id 헤더 기반의 역할 권한 검증으로 선생님/학부모 흐름을 분리합니다.
