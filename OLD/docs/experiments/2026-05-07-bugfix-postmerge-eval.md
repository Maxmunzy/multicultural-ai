# bbox 머지 후 버그 수정 평가 (2026-05-07)

- date: 2026-05-07
- target: `slot_extractor.py` / `translator.py` / `card_builder.py`
- 계기: bbox PR 머지 후 NCP 실 문서 테스트에서 관찰된 잔여 문제 수정

## 수정 항목

### 1. `스쿨뱅킹 → "School Banking (School Banking)"` 중복번역

**원인**  
`translate_short_sentence()`의 glossary injection이 `스쿨뱅킹` → `스쿨뱅킹(School Banking)` 형태로 NLLB에 전달.  
NLLB가 한국어 음역(`스쿨뱅킹` → `School Banking`)과 괄호 힌트(`(School Banking)`)를 둘 다 번역 → 중복 출력.

**수정** (`translator.py`)  
glossary 용어를 `__SLOT__` placeholder로 stash (restore 값 = 번역어), NLLB 통과 후 복원.  
URL/전화 보호와 동일한 메커니즘.

```python
# Before:
injected = injected.replace(korean, f"{korean}({preferred})")

# After:
while korean in injected:
    idx = len(placeholders)
    placeholders.append(preferred)
    injected = injected.replace(korean, f"__SLOT{idx}__", 1)
```

**검증**
| 입력 | Before | After |
|---|---|---|
| `스쿨뱅킹으로 납부해 주세요.` | `School Banking (School Banking)` | `Vui lòng thanh toán School Banking.` |

---

### 2. 명시 헤더 카드 value 과도한 흡수

**원인**  
`_trim_long_fallback_card()`가 `기타` 헤더 카드만 trim.  
`신청방법`, `납부 방법` 등 정상 헤더 카드가 전체 안내 단락을 value로 흡수.

**수정** (`card_builder.py`)  
`_NAMED_MAX_KO_LEN = 150` 추가, `_build_card_from_todo`에서 명시 헤더 카드도 `_smart_trim` 적용.

```python
_NAMED_MAX_KO_LEN = 150
# ...
elif len(value) > _NAMED_MAX_KO_LEN:
    value = _smart_trim(value, max_len=_NAMED_MAX_KO_LEN)
```

**검증**  
168자 value → 107자로 trim (첫 완전 문장 단위 절단). 짧은 value는 그대로.

---

### 3. 발송일(통지 날짜)이 이벤트 dates 슬롯에 오추출

**원인**  
가정통신문 하단 서명 영역의 날짜(예: `2026. 4. 28.(화)`)가 이벤트 날짜로 추출.  
`까지`/`마감` 없이 단독 등장하므로 기존 마감일 분기에서 걸리지 않음.

**수정** (`slot_extractor.py`)  
날짜 앞뒤 60자 안에 서명 문구(`드림`, `올림`, `담임교사`, `교장직인`, `작성일`, `발송일`)가 있으면 발송일로 판단 → `dates`/`deadlines` 둘 다 제외.

```python
_NOTICE_SIGN_OFF = re.compile(
    r"드림(?!니다)|올림(?!니다)|담임\s*교사|교\s*장\s*직인|작성\s*일|발송\s*일"
)
# ...
elif _NOTICE_SIGN_OFF.search(before) or _NOTICE_SIGN_OFF.search(after):
    is_notice_date = True
if is_notice_date:
    continue
```

**검증**
| 시나리오 | 결과 |
|---|---|
| `위와 같이 안내드립니다.\n2026. 4. 28.(화)\n담임교사 드림` | dates=[] (발송일 제외) |
| `5월 6일(목) 출발, 오전 8시 50분 집합` | dates=[5월 6일(목)] (정상 추출) |
| `참가 동의서는 4월 28일(화) 까지 담임선생님께 제출` | deadlines=[4월 28일(화)] (마감일 분류) |

---

### 4. `1박 2일간` glossary 추가

**수정** (`term_glossary.csv`)  
수학여행/현장체험학습 숙박 일정 표현 8개 언어 추가.

| 언어 | 번역어 |
|---|---|
| vi | 1 đêm 2 ngày |
| en | 1 night 2 days |
| zh | 1晚2天 |
| th | 1 คืน 2 วัน |
| ms | 1 malam 2 hari |
| mn | 1 шөнө 2 өдөр |
| ru | 1 ночь 2 дня |
| ja | 1泊2日 |

## 자체 테스트 결과

| 케이스 | 결과 |
|---|---|
| `24:00` 시간 오인식 필터 | OK |
| URL 한국어 조사 strip | OK |
| 마감일 deadlines 분류 | OK |
| 발송일 dates 제외 | OK |
| 이벤트 날짜 정상 추출 | OK |
| 스쿨뱅킹 중복 없음 | OK |
| 같은 단어 2회 등장 __SLOT__ | OK |
| named 카드 150자 trim | OK |

- 전체 통과: 8/8 (100%)

## 남은 한계

- **ML Kit OCR 오인식** (`jje→jie`, `1·2→12`, `①→1)`) — 디바이스 OCR 한계, 백엔드 수정 불가
- **발송일 탐지** — `드림`/`담임교사` 없는 서명 양식은 여전히 이벤트 날짜로 추출 가능
- **Android `mergeAndFinalize()`** — 표 crop OCR 결과가 bbox 없이 선형 추가되어 layout 재구성 효과 감소 (Android 수정 필요)
