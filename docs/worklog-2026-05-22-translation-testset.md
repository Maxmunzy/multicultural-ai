# 2026-05-22 워크로그 — 템플릿 확장 / 고유명사 보호 / 테스트셋 100문장 구축

**작성일:** 2026-05-22  
**작성자:** 세종 (mosejong)  
**작업 범위:** translator.py 버그 수정 및 기능 확장, 고유명사 슬롯 보호 구현, glossary 25개 확장, 100문장 정형 평가셋 설계·구축, glossary-first normalize 버그 수정

---

## 한 줄 요약

템플릿 타입 5종→8종 확장, 고유명사(한국 공공기관명) 슬롯 보호 구현, 복합어 조사 오절삭 버그 수정, 100문장 구조화 평가셋으로 재평가 → 이전 17/17 대신 5개 메트릭 기반 결과 산출.

---

## 작업 배경

### 1. 템플릿 누락 타입

`action_templates.json`에는 준비/제출/납부/참석/확인/작성/신청 7종 + 일정 1종이 정의돼 있었지만, 팀 레포 `translator.py`의 `_SENTENCE_TYPES`에는 준비/제출/납부/참석 5종만 반영돼 있었다. 실제 가정통신문에서 "확인해 주세요", "작성해 주세요", "신청해 주세요"가 빈번하게 등장하는데 모두 NLLB fallback으로 빠지고 있었음.

### 2. item 오염 버그 (anti-contamination)

이전에 `template_matcher.py`(랩 파일)에서는 수정됐지만 팀 레포 `translator.py`에는 미동기화된 버그가 남아 있었다. `_extract_template_items`에서 문장 전체를 대상으로 glossary 검색을 해서 동사 트리거 이후 텍스트(제출해·납부해 등)가 item으로 오탐되는 문제였다.

### 3. 고유명사 번역 손실

NLLB에 "국립과학관에서 체험학습이 진행됩니다"를 그대로 입력하면 기관명이 외국어로 번역되거나("과학관" → "Science Hall" 등) 한국어 고유명사가 소실된다. 학부모에게 장소를 한국어 그대로 전달해야 하는 요건에 어긋남.

### 4. 평가 수치 신뢰도 문제

기존 `17/17 100%` 수치는 자체 제작 17문장 기준으로, 제작자가 의도한 패턴만 포함돼 있어 실제 품질을 나타낸다고 보기 어려웠다. 발표 자료에 쓰려면 카테고리 분산·난이도 분산·negative set·pass 기준 명시가 필요.

---

## 작업 내용

### 1. translator.py — 아이템 추출 anti-contamination 동기화

`_extract_template_items`의 검색 대상을 전체 문장에서 **동사 트리거 이전 구간(item_zone)으로 한정**.

신규 함수 `_get_item_zone(text, stype)`:
- 동사 트리거 위치를 찾아 그 앞 텍스트만 반환
- 토큰별 한국어 조사(`_KO_PARTICLES`) 제거 적용
- ISSUE-03 보호: 조사 제거 후 1자 이하가 되면 원형 유지 (`참가` → `참` → 원형 `참가`)
- `과/와` 조사를 `_KO_PARTICLES`에 추가 (나열형 "공책과 연필을"에서 `과` 올바르게 제거)

호출부 수정:
```python
item_zone = _get_item_zone(text, stype)
items = _extract_template_items(item_zone, glossary, lang)  # 전: (text, ...)
```

---

### 2. translator.py + action_templates.json — 템플릿 타입 3종 추가

| 타입 | 트리거 예시 | 번역 예시 (vi) |
|---|---|---|
| `check` | 확인해 주세요, 확인하세요, 확인 바랍니다, 확인해 주시기 바랍니다 | `Vui lòng kiểm tra {items}.` |
| `fill` | 작성해 주세요, 작성하세요, 기재해 주세요 | `Vui lòng điền vào {items}.` |
| `apply` | 신청해 주세요, 신청하세요, 접수해 주세요 | `Vui lòng đăng ký {items}.` |

`_SENTENCE_TYPES`에 3종 추가 → 5종에서 **8종**으로 확장.  
`_LANG_TEMPLATES`에 8언어(vi/en/ru/ms/mn/zh/th/ja) × 3타입 추가.  
`action_templates.json`에도 동일하게 3 패턴 추가 (id: check_item / fill_item / apply_item).

---

### 3. 고유명사 슬롯 보호 (Method B — regex 기반)

**방침**: 한국 공공기관명(국립과학관 등)은 번역 없이 한국어 그대로 보존. NLLB 입력 전에 슬롯으로 마스킹, 복원 시 원문 복원.

#### 3-1. 정규식 상수 추가

```python
_PLACE_SUFFIX = (
    r"(?:박물관|미술관|과학관|천문대|체험관|기념관|생태관|역사관"
    r"|동물원|식물원|수목원|전시관|문화관|문화원|문화회관|기념회관"
    r"|공연장|체육관|빙상장|수영장|야영장|캠핑장|공원|정원|회관|센터)"
)
_PROPER_PLACE = re.compile(
    r"(?:국립|시립|도립|구립|군립|사립|공립)[가-힣]{1,12}" + _PLACE_SUFFIX
    + r"|[가-힣a-zA-Z]{1,12}(?:\s[가-힣a-zA-Z]{1,8})?\s?" + _PLACE_SUFFIX
)
_PLACE_NON_PREFIX = frozenset([
    "금일", "오늘", "내일", "모레", "이번", "다음", "당일", "매일", "매주", "매월",
    "현재", "현장", "해당", "관련", "각종", "여러", "일부", "방문", "견학",
])
_JOSA_ENDING = re.compile(r"[은는이가을를도]$")
```

#### 3-2. `stash_place` 함수 (\_mask\_protected\_entities 내부)

```python
def stash_place(m: re.Match) -> str:
    text = m.group(0)
    first = text.split()[0]
    if first in _PLACE_NON_PREFIX:
        return text                        # "금일 식물원" → skip
    if _JOSA_ENDING.search(first):
        rest = text[len(first):].lstrip()
        return first + " " + stash_value(rest)  # "학생들은 국립해양박물관" → 학생들은 + SLOT
    return stash_value(text)
```

**동작 흐름**: NLLB 입력에는 `__SLOT0__` 형태로 마스킹 → NLLB 출력 후 원문 한국어 기관명 복원.

#### 3-3. 15케이스 고유명사 테스트 결과

| 결과 | 건수 | 사례 |
|---|---|---|
| PASS | 14 | 국립과학관, 시립미술관, 부산 과학체험관, 학생들은 국립해양박물관, 금일 식물원(비매칭 정상) 등 |
| KNOWN LIMIT | 1 | 서울특별시교육청과학전시관 남산분관 (12자 prefix 한도 내 오매칭, regex 구조 한계) |

---

### 4. term_glossary.csv — 25개 확장 (398 → 423)

`find_compound_candidates.py`로 9,809개 문장 corpus를 스캔해 glossary 인접 용어 쌍 빈도 분석 후 신규 compound 용어 선별.

**신규 추가 compound 항목 (주요)**:

| 추가 항목 | 분류 |
|---|---|
| 하교 시간, 등교 시간 | 일정·출결 |
| 학생 건강검진, 학생 구강검진 | 건강·안전 |
| 상담 시간, 학생 생활지도 | 교육행정 |
| 급식 신청서, 학교급식 설문지 | 서류·신청 |
| 현장체험학습 참가 신청서 | 서류·신청 |
| 수학여행 참가 신청서 | 서류·신청 |
| 농촌유학 참가 신청서 | 서류·신청 |
| 봉사활동 확인서 | 서류·신청 |
| 예방접종 안내문 | 건강·안전 |
| 스쿨뱅킹 자동이체 | 비용·납부 |
| 출석인정 결석 | 일정·출결 |
| 교재 재료비 | 비용·납부 |

**방침 결정**: 학교별 고유 장소명(운동장, 급식실 등)은 너무 학교 종속적이라 glossary 미등재. 기관명은 regex 슬롯 보호로 처리.

---

### 5. find_compound_candidates.py 신규 작성

**파일**: `translation-tts-lab/translation/find_compound_candidates.py`  
**목적**: corpus에서 glossary 용어가 인접 출현하는 쌍 빈도 분석 → compound 후보 추출.

```
사용법:
  python find_compound_candidates.py
  python find_compound_candidates.py --min 3 --top 30
```

동작: glossary 용어 최장 매칭 → 인접 쌍(공백 1개 이하) 카운트 → 빈도 내림차순 출력.  
corpus: `todo_labeled_draft.jsonl` (9,809문장) 처리.

---

### 6. 100문장 구조화 평가셋 설계 및 구축

#### 6-1. 설계 원칙 (기존 17/17 방식의 한계 보완)

| 문제점 | 대응 |
|---|---|
| 샘플 수 너무 적음 | 100문장으로 확대 |
| 쉬운 문장 위주 | easy/medium/hard/adversarial 난이도 분산 |
| 만든 사람이 의도한 문장만 | negative set 10건, adversarial 5건 포함 |
| pass 기준 불명확 | 필드별 기준 고정 (expected_action, expected_item_keywords 등) |
| 단일 숫자 하나로 평가 | 메트릭 5개로 분리 |

#### 6-2. 카테고리별 분포

| 카테고리 | 건수 | 비고 |
|---|---|---|
| submit | 20 | easy 5 / medium 8 / hard 7 |
| prepare + bring | 20 | easy 8 / medium 7 / hard 5 |
| pay | 13 | easy 4 / medium 6 / hard 3 |
| attend + schedule | 12 | easy 4 / medium 5 / hard 3 |
| place (고유명사) | 15 | easy 5 / medium 5 / hard+adversarial 5 |
| apply + fill + check | 10 | easy 3 / medium 4 / hard 3 |
| negative | 10 | 템플릿 미매칭 확인용 |
| **합계** | **100** | |

#### 6-3. JSONL 레코드 스키마

```json
{
  "id": "SUB-E-001",
  "text": "참가 동의서를 제출해 주세요.",
  "category": "submit",
  "difficulty": "easy",
  "expected_action": "submit",
  "expected_item_keywords": ["참가 동의서"],
  "expected_date": null,
  "expected_amount": null,
  "expected_place": null,
  "should_match_template": true,
  "should_extract_place": false,
  "notes": ""
}
```

#### 6-4. 평가 러너 `run_eval_testset.py`

5개 메트릭 산출:

| 메트릭 | 정의 |
|---|---|
| `template_hit_rate` | `should_match_template=true` 중 expected_action과 실제 매칭 타입이 일치한 비율 |
| `template_fp_rate` | `should_match_template=false` 중 잘못 매칭된 비율 (낮을수록 좋음) |
| `item_capture_rate` | `expected_item_keywords` 중 하나라도 item_zone에 포함된 비율 |
| `place_capture_rate` | `should_extract_place=true` 중 expected_place가 슬롯으로 추출된 비율 |
| `place_fp_rate` | `should_extract_place=false` 중 잘못 슬롯된 비율 (낮을수록 좋음) |

필터 옵션: `--category`, `--difficulty`, `--shuffle`, `--quiet`

---

### 7. glossary-first normalize 버그 수정 (SUB-H-004)

**버그**: `_get_item_zone`에서 토큰별 조사 제거 시 복합 glossary 항목의 구성 단어 끝 글자를 조사로 오판해 잘라버리는 문제.

**재현 케이스**:
```
"학생 생활지도 동의서를 제출해 주세요."
→ _get_item_zone 처리 결과: "학생 생활지 동의서 함께"
→ "생활지도" 검색 실패 (glossary에 있지만 못 잡음)
```

`생활지도` → 끝 글자 `도`가 `_KO_PARTICLES`(`[은는이가을를도]$`)에 매칭 → `생활지`로 절삭.  
ISSUE-03 보호(1자 이하면 원형 유지)는 절삭 결과 3자(`생활지`)라 발동 안 됨.

**도메인 패턴**: 학교 문서에서 `지도`로 끝나는 합성어 다수.
```
생활지도, 방과후지도, 진로지도, 안전지도, 교통지도, 흡연예방지도 ...
```

**수정 방향**: glossary 복합 항목의 구성 단어를 사전에 수집해 조사 제거 전 확인(glossary-first normalize).

#### 7-1. `_GLOSSARY_WORD_PARTS` 전역 상수 추가

```python
_GLOSSARY_WORD_PARTS: frozenset[str] = frozenset()
```

#### 7-2. `_build_role_sets` 확장

```python
word_parts: set[str] = set()
for row in glossary:
    ko = row.get("korean", "").strip()
    if ko and len(ko.split()) > 1:          # 복합어(공백 포함)만
        for w in ko.split():
            if len(w) >= 2:
                word_parts.add(w)
_GLOSSARY_WORD_PARTS = frozenset(word_parts)
```

예: `"학생 생활지도"` → `{"학생", "생활지도"}` 등록.

#### 7-3. `_get_item_zone` 수정

```python
for t in tokens:
    if t in _GLOSSARY_WORD_PARTS:   # glossary 구성 단어 → 조사 제거 금지
        cleaned.append(t)
        continue
    s = _KO_PARTICLES.sub("", t).strip()
    ...
```

동일한 수정을 `run_eval_testset.py`의 `get_item_zone`에도 적용 (glossary CSV 로드 → `_GLOSSARY_WORD_PARTS` 빌드).

---

## 최종 평가 결과 (100문장 기준)

```
template_hit_rate   : 67/67 = 100%   should_match=true 중 정확 매칭
template_fp_rate    :  0/33 =   0%   should_match=false 중 오매칭
item_capture_rate   : 65/65 = 100%   expected 키워드 1개 이상 item_zone 포함
place_capture_rate  : 10/10 = 100%   should_extract=true 중 정확 추출
place_fp_rate       :  1/90 =   1%   should_extract=false 중 오추출

실패: 1건 (PLACE-H-001) — KNOWN LIMIT
```

### 발표 자료 기재 기준 문구

> 기존에는 17개 샘플 기준으로 용어 보존 여부만 확인했으나, 해당 수치는 실제 품질 설명에 부족하다고 판단했습니다.  
> 테스트셋을 100문장으로 확장하고 template hit rate, template false positive rate, item capture rate, place capture rate, place false positive rate로 나누어 재평가했습니다.  
> 그 결과 템플릿 매칭 대상 67건은 모두 정확히 매칭됐고, 비대상 33건에서는 오탐이 발생하지 않았습니다.  
> 조사 오절삭 버그 1건(생활지도 → 생활지) 발견 후 수정했으며, 잔여 known limitation 1건(긴 복합기관명 regex 한계)은 문서화했습니다.  
> **본 결과는 "완벽한 번역 성능"이 아니라, 제한된 내부 테스트셋에서 핵심 슬롯·템플릿 로직이 안정적으로 동작함을 확인한 결과입니다.**

---

## 발견된 known gaps (수정 예정 또는 known limit)

| ID | 내용 | 분류 |
|---|---|---|
| BRING-H-002 | `착용하고 오세요` trigger가 `action_templates.json`에는 있으나 `translator.py` `_SENTENCE_TYPES`에 누락 | 수정 필요 |
| SCHE-M/H | schedule 타입(`진행됩니다/실시됩니다/예정입니다/개최됩니다`) 미구현 — `action_templates.json`에 정의됐지만 translator.py에 없음 | 우선순위 낮음 (item 추출 불안정) |
| PLACE-H-001 | `서울특별시교육청과학전시관`처럼 12자 이내 들어오는 복합기관명 false positive | regex 구조 한계, 수용 가능 |

---

## 변경 파일 목록

| 파일 | 변경 내용 |
|---|---|
| `backend/app/services/translator.py` | `_get_item_zone` 추가, `_extract_template_items` 서명 변경, check/fill/apply 타입 추가, `_PROPER_PLACE`/`_PLACE_NON_PREFIX`/`_JOSA_ENDING` 상수 추가, `stash_place` 구현, `_GLOSSARY_WORD_PARTS` + `_build_role_sets` 확장 |
| `translation-tts-lab/translation/action_templates.json` | check_item / fill_item / apply_item 패턴 추가 |
| `translation-tts-lab/translation/term_glossary.csv` | 25개 항목 추가 (398 → 423) |
| `translation-tts-lab/translation/find_compound_candidates.py` | 신규 생성 (corpus 인접 쌍 빈도 분석) |
| `translation-tts-lab/translation/eval_testset_v1.jsonl` | 신규 생성 (100문장 정형 평가셋) |
| `translation-tts-lab/translation/run_eval_testset.py` | 신규 생성 (5메트릭 평가 러너) |

---

## 다음 작업

- [ ] `착용하고 오세요` 등 누락 bring trigger를 `translator.py`에 동기화
- [ ] PR: `feature/sejong-data-tts` → `dev`
- [ ] README 업데이트 (`model/translation_tts/README.md`) — 용어사전 423개, 템플릿 8종, 평가셋 100문장 반영
