# 2026-05-06 워크로그 — 번역 안정화 (slot-protected translation)

**작성일:** 2026-05-06  
**작성자:** 세종 (mosejong)  
**작업 범위:** translator.py 오번역 방어 + 슬롯 보호 번역 1차 안정화 + 테스트 완비

---

## 한 줄 요약

NLLB가 날짜·시간·금액·URL·전화를 깨먹지 못하도록 placeholder 격리 파이프라인을 구축하고, 1글자 용어사전 오탐 방지 및 베트남어 오번역 후처리를 추가. 테스트 21종 전부 통과.

---

## 작업 배경

실시연 중 NLLB가 "5월 9일(금)"을 "9 tháng 5 (Thứ Sáu)" 대신 알아볼 수 없는 형태로 내놓거나, "15,000원"을 "15.000 đồng"·"15 USD"로 오번역하는 케이스가 반복됨. 용어사전의 1글자 항목("원", "반" 등)이 숫자 뒤에 붙은 단위에도 hit를 내서 의도치 않은 치환이 발생하는 버그도 함께 발견됨.

---

## 작업 내용

### 1. term_glossary.csv — 1글자 항목 제거

| 제거 항목 | 이유 |
|---|---|
| 풀 | "풀어쓰다" 등 동사 어근에 오탐 |
| 반 | "반드시", "반납" 등에 substring 충돌 |
| 컵 | 단어 경계 없는 오탐 |
| 원 | "15,000원" → "15,000won" 이중치환 버그 |

현재 용어사전: **319개** (4차 배치 후 기준, 2026-05-06).

---

### 2. backend/app/services/translator.py

#### 2-1. 1글자 term 가드 (`_find_glossary_hits_safe`)

```python
if not korean or not preferred or len(korean) <= 1:
    continue
```

glossary hit 탐색 시 한국어 키가 1글자이면 무조건 건너뜀.

#### 2-2. 공백 normalize 매칭

```python
def _normalize_glossary_key(text: str) -> str:
    return re.sub(r"\s+", "", text or "")
```

HWP 표 셀이 "담임 선생님" / "담임선생님"처럼 띄어쓰기 변형으로 들어와도 동일 키로 매칭.

#### 2-3. 베트남어 후처리 패턴 추가

| 오번역 패턴 | 수정값 |
|---|---|
| `sinh viên` / `học viên` | → `học sinh` (학생 맥락에서) |
| `giáo viên giám đốc` 등 | → `giáo viên chủ nhiệm` (담임 맥락에서) |
| `Học viện sinh viên mẫu giáo` 등 | → `trẻ mẫu giáo` (유치원생 맥락에서) |
| `học tập thực tập tại trường` 등 | → `buổi trải nghiệm thực tế` (체험학습 맥락에서) |

#### 2-4. Slot-protected translation 구축

`_mask_protected_entities(text, target_lang=None)` 확장:

```
URL/전화 → ⟦P0⟧ … (기존)
날짜     → ⟦P1⟧   format_date(d, target_lang) 값을 placeholders에 저장
시간     → ⟦P2⟧   format_time(t, target_lang)
금액     → ⟦P3⟧   format_amount(a, target_lang)
```

`translate_short_sentence` 파이프라인:

```
원문
 └→ _mask_protected_entities(text, target_lang)   # 날짜/시간/금액/URL/전화 격리
 └→ glossary injection (긴 용어 우선)
 └→ NLLB (_translate)
 └→ _post_process_vi (vi 한정)
 └→ _restore_protected_entities                    # ⟦Pn⟧ → 포맷된 값 복원
```

**before/after 예시:**

| 원문 | NLLB 입력 (이전) | NLLB 입력 (이후) | 최종 출력 |
|---|---|---|---|
| `5월 9일(금)까지 제출` | `5월 9일(금)까지 제출` | `⟦P0⟧까지 제출` | `Ngày 9/5 (Thứ Sáu)까지 제출` |
| `오전 9시부터 시작` | `오전 9시부터 시작` | `⟦P0⟧부터 시작` | `9 giờ sáng부터 시작` |
| `참가비 15,000원 납부` | `참가비 15,000원 납부` | `참가비 ⟦P0⟧ 납부` | `참가비 15,000 won 납부` |

---

### 3. backend/tests/test_translator_protection.py

기존 11종 + 신규 10종 = **21종 전부 통과**.

#### 신규 테스트 목록

| 테스트 | 검증 내용 |
|---|---|
| `test_mask_date_protected_with_target_lang` | "5월 9일(금)" → ⟦P0⟧, holder = `Ngày 9/5 (Thứ Sáu)` |
| `test_mask_time_protected_with_target_lang` | "오전 9시" → ⟦P0⟧, holder = `9 giờ sáng` |
| `test_mask_amount_protected_with_target_lang` | "15,000원" → ⟦P0⟧, holder = `15,000 won` |
| `test_mask_no_slot_protection_without_target_lang` | target_lang 없으면 날짜/시간/금액 보호 안 함 |
| `test_mask_date_time_no_overlap` | 날짜+시간 동시 존재 시 중복 없이 각각 격리 |
| `test_mask_already_placeholder_not_re_extracted` | URL placeholder를 날짜 추출기가 오탐하지 않음 |
| `test_translate_short_sentence_protects_date` | NLLB 입력에 원본 날짜 없음, vi 포맷 복원 |
| `test_translate_short_sentence_protects_time` | NLLB 입력에 원본 시간 없음, vi 포맷 복원 |
| `test_translate_short_sentence_protects_amount` | NLLB 입력에 원본 금액 없음, vi 포맷 복원 |
| `test_translate_short_sentence_en_date_format` | en 타깃에서 영어 날짜 포맷 확인 |

#### 기존 테스트 버그 수정

`test_translate_short_sentence_protects_url_through_nllb`에서 `_sejong.find_glossary_hits` monkeypatch 제거.  
CI 환경에서 `_sejong = None`이라 `AttributeError`가 발생하던 버그. 현재 코드는 `_find_glossary_hits_safe`를 직접 사용하므로 해당 monkeypatch 자체가 불필요.

---

## 테스트 결과

```
backend/tests/test_translator_protection.py  21/21 PASSED  (5.44s)
backend/tests/test_slot_extractor.py         32/32 PASSED  (0.13s)
```

---

## 커밋

| 커밋 | 브랜치 | 내용 |
|---|---|---|
| `cc169ef` | `feature/sejong-data-tts` | test(translator): slot-protected translation 1차 안정화 및 테스트 21종 추가 |
| `3530761` | `feature/sejong-data-tts` | fix(translator): NLLB placeholder 복원 버그 수정 + 준비물 용어 10개 추가 |

푸시 보류 (미팅 전 NCP 재배포 금지 방침).

---

## 시연 테스트 중 발견된 이슈 및 팀 결정 (2026-05-06 오후)

학습준비물 안내 PDF 및 해조류박람회 체험학습 공지로 실기기 시연 테스트 진행.

### 발견 이슈

| 항목 | 내용 | 처리 |
|---|---|---|
| `__SLOT0__` 복원 실패 (구버전 `⟦P0⟧`) | NLLB가 ⟦⟧ 소실 → "연락처: P0" 출력 | `3530761` 커밋으로 수정 완료 |
| `유성매직` → `hoạt động sinh dục` | 용어사전 미등록으로 오역 (성행위) | 용어사전 추가로 수정 완료 |
| `전교생` 오역 | 이미 사전에 등록됨, 서버 미배포 상태라 반영 안 됨 | 푸시 후 자동 해결 예정 |
| 쉬운 한국어 거의 변화 없음 | 윤정 모델 한계, 원문이 단문이라 변환 여지 적음 | 세종 영역 외 |
| 학년별 준비물 한 덩어리 출력 | 표 파싱은 이미 구현됨, 표 행 분리 미구현 | 학년 필터는 상용화 시 추가 예정 (패싱) |

### 팀 결정사항 (태수·세종 합의)

**쉬운 한국어 섹션 UI 숨김**
- 기능은 유지, 화면 표시만 제거
- 실제로 한두 단어만 바뀌어 자리만 차지하는 문제
- 태수 작업 예정

**"📖 사용된 학교 용어" 탭 숨김**
- 실제 glossary_hits 응답 필드 없음 (translate_and_review deprecated 이후 빠짐)
- 안드 `renderCardChips`가 glossary 아닌 카드 chip 재활용 중 (라벨/기능 불일치)
- A안(glossary_hits 복원) 대신 B안(숨김) 선택 — 공모전 이후 상용화 시 복원
- 태수·찬영 작업 예정

---

## 다음 작업

- [ ] 미팅 후 `feature/sejong-data-tts` → `dev` PR 및 푸시
- [ ] 실제 가통문 샘플로 slot-protected translation 수동 검증 (`run_mvp_pipeline.py`)
- [ ] 날짜 범위 "8:50 ~ 14:40" → `__SLOT0__` ~ `__SLOT1__` 복원 검증
