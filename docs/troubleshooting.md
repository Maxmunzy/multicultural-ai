# 트러블슈팅 및 제한사항

## 문서 목적

MVP 시연 중 자주 막히는 지점과 현재 구현상 제한사항을 정리합니다. 기준일은 2026-05-06이며, **NCP Seoul VM 실서버** (2vCPU 8GB, 실 IP 는 팀 디스코) 배포 후 상태 기준으로 작성했습니다. 이전 HF Spaces 무료 플랜은 POST 콜드스타트로 부적합 → NCP로 이전.

---

## 빠른 점검 순서

**기본 (HF Spaces 실서버)**

1. PC/휴대폰 브라우저에서 `https://maxmunzy-schoolbridge.hf.space/health` 확인 → `{"status":"ok"}`
1. Android `MainActivity.java`의 `BASE_URL`이 `https://maxmunzy-schoolbridge.hf.space`인지 확인 (기본값)
1. 앱 로그인 화면에서 시드 계정으로 입장 (teacher_001 / parent_001 등)
1. 선생님 ID로 발송 (또는 PDF/사진 업로드) 후 같은 `parent_id`의 학부모 ID로 수신함 조회
1. **카드 클릭 → 원본 PDF/이미지 풀화면** → 우상단 ✨ AI → 분석 결과 표시
1. 분석 결과가 안 나오면 앱의 고정 데모 fallback 확인

**로컬 백엔드 사용 시 (옵션)**

1. `docker compose up --build`
1. PC 브라우저에서 `http://localhost:8000/docs` 확인
1. 같은 네트워크의 휴대폰 브라우저에서 `http://PC_IP:8000/docs` 확인
1. `MainActivity.java`의 `BASE_URL`을 PC IP로 임시 변경 (커밋 금지)

---

## 서버 실행 문제

### `docker-compose up --build` 후 `/docs`가 열리지 않음

확인할 것:

- Docker Desktop이 실행 중인지 확인
- 8000 포트를 다른 프로세스가 쓰고 있지 않은지 확인
- repo 루트에서 실행했는지 확인

```powershell
docker-compose up --build
```

정상 접속 주소:

```text
http://localhost:8000/docs
```

## Android 연결 문제

### 휴대폰에서 서버 연결 실패

Android 실기기에서 `localhost`는 PC가 아니라 휴대폰 자기 자신입니다. `BASE_URL`에는 PC의 같은 네트워크 IP를 넣어야 합니다.

PC IP 확인:

```powershell
ipconfig
```

수정 위치:

```text
android/app/src/main/java/com/multicultural/demo/MainActivity.java
```

예시:

```java
private static final String BASE_URL = "http://192.168.0.23:8000";
```

휴대폰 브라우저에서 먼저 확인:

```text
http://192.168.0.23:8000/docs
```

### PC에서는 되는데 휴대폰에서는 안 됨

확인할 것:

- PC와 휴대폰이 같은 Wi-Fi인지 확인
- VPN, 핫스팟, 게스트 Wi-Fi가 분리망을 만들고 있지 않은지 확인
- Windows 방화벽에서 8000 포트 접근이 막히지 않았는지 확인
- Docker 컨테이너가 `0.0.0.0:8000`으로 노출되는지 확인

---

## 인증/권한 문제

### 401 Unauthorized — `X-User-Id 헤더가 필요합니다`

원인: 클라이언트가 `X-User-Id` 헤더 없이 `/notice/*`를 호출함. Android 앱은 로그인 화면에서 ID를 입력해야 헤더가 채워집니다. Swagger에서 직접 호출 시에는 `Authorize` 또는 cURL `-H "X-User-Id: parent_001"`을 추가해야 합니다.

### 401 Unauthorized — `등록되지 않은 사용자`

`X-User-Id` 헤더 값이 시드 계정 목록에 없는 경우. 시연용 시드는 서버 시작 시 자동 등록되며 다음 ID만 유효합니다.

| user_id | 역할 |
| --- | --- |
| `teacher_001`, `teacher_002` | teacher |
| `parent_001`, `parent_002`, `parent_003` | parent |

신규 ID가 필요하면 `POST /user/`로 등록 후 사용하세요.

### 403 Forbidden — `선생님 권한이 필요합니다` / `학부모 권한이 필요합니다`

각 엔드포인트의 역할 제약:

- `POST /notice/send` → teacher 본인 (헤더와 body의 `teacher_id` 일치 필요)
- `GET/DELETE /notice/inbox/{parent_id}` → 본인 parent_id만
- `POST /notice/analyze/{notice_id}` → 해당 통신문의 parent 본인만

## 데이터/분석 문제

### 학부모 수신함이 비어 있음

가능한 원인:

- 선생님 화면에서 발송을 먼저 하지 않음
- 발송 시 `parent_id`와 학부모 수신함 조회 `parent_id`가 다름
- 서버가 재시작되어 임시 메모리 저장소가 비워짐

현재 backend는 DB가 아니라 프로세스 메모리에 가정통신문을 저장합니다. 서버를 재시작하면 이전 발송 데이터는 사라집니다 (시드 계정은 lifespan에서 다시 등록됨).

### 분석 결과가 실제 모델 결과가 아님 (해결됨)

`POST /notice/analyze/{notice_id}`는 실제 모델 파이프라인과 연결되어 있습니다.

- 모델 A (추출): `backend/app/services/extractor.py` → `extract_todos()`
- 모델 B (분류 교차검증): `backend/app/services/classifier.py` → `review_todos()`
- 번역/TTS: `backend/app/services/translator.py` + `tts.py`

결과가 고정 샘플처럼 보이는 경우: 추출 모델이 해당 텍스트에서 항목을 뽑지 못하면 `MOCK_TODOS`로 fallback됩니다. 실제 가정통신문 형식의 텍스트로 테스트하세요.

### 첫 실행이 너무 오래 걸림 (콜드스타트)

첫 호출 시 HuggingFace Hub에서 모델 가중치를 다운로드합니다:

- KcELECTRA v3 분류 (`kysophia/kcelectra-category` subfolder `kcelectra-category-v3`) ~452MB
- KoELECTRA 추출 (`yunjeong116/koelectra-extractor`) ~440MB
- NLLB-200-distilled-600M ~2.4GB

총 ~3.3GB. HF Spaces 환경에선 보통 3-5분, 로컬 첫 docker compose는 10-15분 가능. 이후 컨테이너 캐시(`/root/.cache/huggingface`)에 저장되어 재호출 시 즉시 로드.

**시연 30분 전 warmup 필수**:

배포(HF Spaces):

```bash
# send
curl -s -X POST https://maxmunzy-schoolbridge.hf.space/notice/send \
  -H "Content-Type: application/json" \
  -H "X-User-Id: teacher_001" \
  -d '{"teacher_id":"teacher_001","parent_id":"parent_001","text":"6월 12일 수요일에 학부모 공개수업이 진행됩니다."}' | python -m json.tool

# 반환된 notice_id로 analyze
curl -s -X POST https://maxmunzy-schoolbridge.hf.space/notice/analyze/<NOTICE_ID> \
  -H "Content-Type: application/json" \
  -H "X-User-Id: parent_001" \
  -d '{"target_language":"vi"}' | python -m json.tool
```

로컬:

```bash
curl -s -X POST http://localhost:8000/notice/send \
  -H "Content-Type: application/json" \
  -H "X-User-Id: teacher_001" \
  -d '{"teacher_id":"teacher_001","parent_id":"parent_001","text":"테스트"}' | python -m json.tool

curl -s -X POST http://localhost:8000/notice/analyze/<NOTICE_ID> \
  -H "Content-Type: application/json" \
  -H "X-User-Id: parent_001" \
  -d '{"target_language":"vi"}' | python -m json.tool
```

### HF Spaces 첫 요청 타임아웃 (connectTimeout)

HF Spaces 무료 플랜은 일정 시간 요청이 없으면 슬립 상태에 진입합니다. 슬립 후 첫 요청 시 컨테이너가 깨어나는 데 10~30초가 소요되는데, Android `connectTimeout`이 5초이면 연결 단계에서 끊겨버립니다.

**증상**: 텍스트 발송·파일 업로드·분석 모두 바로 실패 (에러 토스트)

**해결**: `MainActivity.java`의 `connectTimeout`을 30초로 증가, 또는 시연 30분 전 warmup curl로 미리 깨워두기 (위 콜드스타트 섹션 참조).

---

## 번역/TTS 문제

### 언어를 바꿔도 결과가 그대로

언어 드롭다운은 `selectedLanguage`만 바꾸고 자동으로 `/notice/analyze`를 다시 호출합니다. 만약 갱신이 안 되면 서버 응답이 새 언어 키(`{lang}_text` 또는 `translation`)를 포함하는지 Swagger에서 확인하세요. 9개 지원 언어: `vi`, `en`, `ru`, `ms`, `mn`, `zh`, `th`, `ja`, `ko_easy`.

### 특정 언어 TTS만 작동 안 함

언어별 Edge-TTS 보이스 매핑(`backend/app/services/tts.py` 참조):

| 언어 코드 | Edge-TTS 보이스 |
| --- | --- |
| vi | vi-VN-HoaiMyNeural |
| en | en-US-JennyNeural |
| ru | ru-RU-SvetlanaNeural |
| ms | ms-MY-YasminNeural |
| mn | mn-MN-YesuiNeural |
| zh | zh-CN-XiaoxiaoNeural |
| th | th-TH-PremwadeeNeural |
| ja | ja-JP-NanamiNeural |
| ko_easy | ko-KR-SunHiNeural |

### TTS URL이 없는데도 앱에서 소리가 남

정상입니다. 서버가 TTS URL을 주지 않으면 Android 앱은 `android/app/src/main/res/raw/tts_output.mp3`에 포함된 고정 mp3를 재생합니다.

### 번역이 어색하거나 학교 용어가 빠짐

MVP의 중요한 관찰 지점입니다. NLLB 원번역은 자연스럽지 않거나 `도시락` 같은 핵심 용어를 놓칠 수 있습니다. 그래서 현재 번역/TTS 파트는 단순 번역만 보여 주지 않고 아래 산출물을 함께 둡니다.

- `02_vi_raw_translation.txt`: 원번역
- `03_glossary_check.csv`: 용어사전 검수 결과
- `04_review_needed.md`: 사람이 확인해야 할 항목
- `05_vi_corrected_translation.txt`: 보정 번역
- `06_tts_output.mp3`: 음성 출력

위 파일들은 `demo/translation_tts/demo_case_01/`에 있습니다.

---

## 현재 제한사항

| 제한사항 | 설명 |
| --- | --- |
| DB 없음 (메모리 + ephemeral) | 가정통신문은 서버 프로세스 메모리에 저장. HF Spaces 컨테이너 재시작 시 업로드된 가통문·원본 파일(`/app/static/notices/`) 모두 초기화. 시연 직전 1회 업로드 권장 |
| **원본 가정통신문 표시** | 학부모 카드 클릭 → 풀화면 PDF (PdfRenderer 페이지 네비) 또는 이미지 (BitmapFactory) 직접 렌더. 텍스트 직송 케이스는 텍스트 카드 fallback. 우상단 ✨ AI 버튼으로 분석 화면 진입 |
| OCR | 학부모 홈 카메라 촬영 → ML Kit Korean 온디바이스 인식 (OcrActivity). HWP/PDF/이미지는 서버사이드 파서 직접 처리 |
| 실제 학교 시스템 연동 없음 | MVP에서는 앱 내부 발송/수신 흐름만 시연 |
| Android `BASE_URL` | 기본 HF Spaces 실서버(`maxmunzy-schoolbridge.hf.space`). 로컬 백엔드 모드는 PC IP 수동 설정 |
| 학습 데이터 | `v3_dual_labeled.jsonl` 28,890행 확보 (이중 라벨). 분류 모델 학습용 `notice_sample_v5_clean_full.csv` 4,992행 (수동 라벨 142 + Haiku 자동 라벨링 4,850) |

---

## E2E 테스트 후 발견된 이슈 (2026-04-27)

### 이슈 1 — 인사말이 체크리스트에 포함됨

**담당**: 윤정 (추출 모델)

"학부모님 안녕하세요." 문장이 TODO로 추출됨. `NON_TODO_PATTERNS`에 `"안녕하십니까"`는 있으나 `"안녕하세요"` 변형이 누락된 것이 원인.

수정 위치: `model/extraction/predict.py` — `NON_TODO_PATTERNS`에 아래 추가

```python
r"^학부모님\s*안녕하세요",
r"^안녕하세요",
```

### 이슈 2 — 베트남어 첫 문장 어색

**담당**: 세종 (번역 파이프라인)

가정통신문 제목과 인사말이 구분 없이 하나의 텍스트 블록으로 NLLB에 입력되어 첫 문장이 혼합 번역됨. 번역 전처리에서 제목 헤더를 줄바꿈으로 분리하거나 제외하는 방식으로 개선 가능.

### 이슈 3 — "원→won" 통화 치환 오탐

**담당**: 세종 (번역 후처리)

"원하시는", "원인" 등 통화와 무관한 단어의 "원"이 substring으로 잡혀 용어 검수 상세에 `원→won`이 표시됨.

수정 위치: `backend/app/services/translator.py` — `_post_process()` 조건 변경

```python
# 기존
if "원" in easy_ko:
# 수정
if re.search(r"\d+\s*원", easy_ko):
```

---

## 학습 데이터 확보 방향 변경 (2026-04-28)

### 문제

학습 데이터가 절대적으로 부족.

- 현재 보유: 147행 (notices_labeled_v2)
- 클래스 불균형 17.5:1, '기타' 카테고리 1건
- BERT급 모델 안전 학습은 200~300행+ 필요

### 시도와 막힌 지점

기존 흐름은 **사진(가정통신문 이미지) → AI(Claude/GPT-4V)로 CSV 변환 → 학습 데이터** 였음. 이 경로에서 발견된 본질 문제:

- AI가 이미지의 글자를 그대로 옮기지 못함 (의역·재구성 본성)
- "도시락" → "급식", "체험학습비" → "체험비" 같이 단어 자체가 바뀜
- 학습 데이터 오염되면 모델이 **존재하지 않는 토큰**을 학습 → 운영 시 실 가정통신문 매칭 실패

→ **이미지 입력으로는 정확한 학습 데이터 만들 수 없음.** 양도 적고 질도 오염된 상태.

### 결정 — 학교 홈페이지 가정통신문 디지털 원본 사용

학교 사이트 게시판에는 가정통신문이 **`.hwp` 첨부파일** 형태로 올라옴 (서울교육청 산하 학교 표준 CMS 기준).

이미지가 아니라 **디지털 원본**이라:

- 한글 파서(`pyhwp`/LibreOffice headless 등)로 100% 정확한 텍스트 추출
- 의역·재구성 단계 자체가 사라짐
- 학습 데이터 오염 위험 0

### 후보 학교

| 학교 | 입력 형태 | 매칭 가치 |
| --- | --- | --- |
| 갈산초 (서울 양천구) | `.hwp` 첨부 | 시연 자료 보유 + 팀 네트워크 가능 |
| 서대구초 (대구) | PDF 첨부 + 학교알리미 | **다문화 가정 1학년 절반** — 우리 타겟 직격 |

→ 두 학교 모두 활용. 입력 형태 분산으로 한 학교 과적합 방지 + 호스트 케이스 다양성 확보.

### 데이터 확보 경로

**시도된 경로와 막힌 지점**:

- 학부모 → 담임 라인 (경이님 언니 통한 갈산초 학부모 컨택): **막힘**. 학교 보안 강화 + 민원 많아 동의 받기 어려움. 학부모-담임 일정 잡는 것조차 앱으로 가능하지만 까다로움.

**현재 메인 경로 — 학교 홈페이지 공개 게시물 수동 다운로드**:

학교 사이트 게시판에 이미 공개된 가정통신문은 일반 사용자가 게시판에서 다운로드하는 행위 자체는 합법. 별도 동의 불필요.
조건:

- 다운로드한 자료는 외부 공개·상업 이용 X
- 학생 이름·번호 등 개인정보 자동 마스킹 처리
- 학생 프로젝트 내부 학습용으로만

대량 자동 크롤링과는 다름. 1장씩 수동 다운로드는 학부모가 게시판 보는 것과 동일한 행위.

**보조 경로**:

- 태수님 지인 교사 라인: 선생님 직접 컨택. 다른 학교 archive 가능성. 별도 진행.
- 공모전 입상 후 정식 학교 / 교육청 협력: 중장기 카드.

**비추**: 자동 크롤링 (robots.txt + 개인정보 + 학교 서버 부하 + 자동 차단 + 법적 리스크).

공개 가정통신문 데이터셋은 부재 (AI Hub / HuggingFace / Kaggle 다 없음). 직접 수집이 답이며, 강사님 처방 ② "데이터 이해 + 커스텀이 근본 핵심"의 본질적 길.

### 양적 목표

300장 × 평균 5~8 라벨/장 = **1500~2400행** (현재 147행의 10~16배).

라벨링 효율화: LLM 1차 라벨 + 사람 검수 흐름 (한 장당 1~2분). 4명 분담 시 발표 일정 안에 가능.

---

## 런타임 파이프라인 v2 (2026-04-29)

윤정·경이 v2 역할 재분담 + 호스트 입력 다양성(HWP/PDF/text) 지원으로 백엔드 갈아엎음.

초기 소통 오류로 윤정·경이 모델이 같은 6-class 카테고리 분류를 *중복* 학습 중이었음. 정리:

- **윤정 v2** = 할일 추출 (binary 분류, BINARY_THRESHOLD=0.5)
- **경이 v2** = 6-class 카테고리 분류 (일정/준비물/제출/비용/건강·안전/기타)

분리 후 직렬 흐름 깨끗해짐 ([3] 윤정 → [4] 경이).

### 응답 구조 변경

기존 단일 blob 응답 (`translation`, `easy_ko_text`, `vi_text`)이 슬롯 구조로 바뀜.

```json
{
  "summary": {
    "dates": [], "times": [], "places": [],
    "supplies": [], "amounts": [], "deadlines": [],
    "urls": [], "phones": []
  },
  "items": [
    {
      "category": "준비물",
      "action_hint": "준비",
      "title_ko": "...",
      "title_translated": "...",
      "amount": "15,000원",
      "deadline": "...",
      "importance": 0.9
    }
  ],
  "tts_url": "...",
  "raw_text": "..."
}
```

→ 안드 화면이 옛 필드(`translation`, `easy_ko_text`)를 찾으면 비어있음. PR #54로 안드는 새 구조 대응 완료.

### 새 엔드포인트 — `POST /notice/upload`

선생님이 HWP/PDF/text 파일 직접 업로드. multipart form-data.

```
form fields:
  teacher_id: str    (X-User-Id 헤더와 일치해야 함)
  parent_id:  str
  file:       File   (.pdf/.hwp/.hwpx/.txt — 화이트리스트 외엔 거부)

응답:
  200 → {"data": {"notice_id": "...", "char_count": 1234}}
  400 → 파일 변환 실패 / 빈 텍스트 / 미지원 확장자
  403 → teacher_id 불일치
  404 → parent_id 없음
```

내부 흐름: HWP는 LibreOffice + H2Orestart로 PDF 변환 → pdfplumber. PDF는 직접 pdfplumber. `services/parser.py`가 통합 진입점.

### URL/전화 보호

NLLB가 `031-627-7916` 같은 전화나 `https://apply.kr` 같은 URL을 토큰화하면서 깨먹는 문제. 두 단계로 방어:

- **슬롯 단위**: `summary.urls`, `summary.phones`에 한국어 그대로 노출 (번역 안 거침)
- **본문 단위**: NLLB 호출 *전에* `⟦P0⟧` 같은 unicode bracket 토큰으로 치환 → 번역 통과 → 토큰 복원

### Dockerfile 영구화

PR #52로 LibreOffice + 한글 폰트 + H2Orestart가 `backend/Dockerfile`에 박힘. **머지 후 백엔드 띄우는 사람은 1회 재빌드 필요**:

```bash
docker compose build backend     # ~6분 (LibreOffice 설치 150초 + pip 210초)
```

이후엔 코드 수정만으로는 layer cache 덕분에 수초.

### 윤정 v2 모델 첫 로드 ~30초

PR #53으로 `_BASE_MODEL_ID = "yunjeong116/koelectra-extractor"`. 컨테이너 첫 호출 시 HF Hub에서 fine-tuned 가중치 자동 다운로드. 이후 `hf_cache` 볼륨에 캐시되어 재기동해도 유지.

### LibreOffice 변환 타임아웃

기본 300초. 큰 HWP에서 부족하면 환경변수로 늘림:

```bash
docker compose run -e PARSER_LIBREOFFICE_TIMEOUT=600 backend
```

### HWP→ODT 글자 3배 중복 (draw:frame, 2026-05-03 fix)

**증상:** 일부 통신문이 글자 3배 반복으로 추출됨 (`어어어린린린이이이`).

**원인:** HWP→ODT 변환 시 텍스트 상자(`draw:frame`)에 본문과 같은 텍스트가 별도로 저장됨. `_odt_to_text`가 `tree.iter()`로 전체 트리를 순회하면서 본문 + frame 텍스트를 둘 다 추출 → 같은 문장 2~3회 반복.

이전 PDF 경로 doubled-char 문제와 별개의 ODT 측 이슈.

**해결 (PR #79):** 표 inner element 제외 로직과 동일하게 `draw:frame` inner도 제외 처리.

```python
# parser.py
_ODT_DRAW_NS = "{urn:oasis:names:tc:opendocument:xmlns:drawing:1.0}"

# _odt_to_text 내부:
for frame in tree.iter(_ODT_DRAW_NS + "frame"):
    for elem in frame.iter():
        table_inner_ids.add(id(elem))  # 본문 처리에서 제외
```

머지 이후 신규 변환은 정상. 머지 이전에 변환된 학습 데이터는 `scripts/fix_triple_chars.py`로 후처리 정제.

### 학구 안내 통신문 (28만자 단일 행)

**증상:** "통반 명칭 및 관할구역" 같은 행정 문서는 한 행에 수만~수십만 자 (아파트 동/호수 나열). 이런 행이 들어가면 모델 추론에서 token limit 초과.

**대응 방향 (라벨링 후 확정):**
- `is_title` 분류기로 제목만 추출 → 학부모에게 "어떤 통신문" 알림
- 본문 분석은 best-effort (실패해도 제목+raw_text는 표시)
- 통신문 자체는 인박스에 정상 표시되어 학부모가 답답함 없음

---

## 설계 결정

### 왜 알림장 앱 전체가 아니라 AI 도우미 모듈인가

이번 MVP의 목표는 새 알림장 서비스를 완성하는 것이 아니라, 기존 학교 알림장이나 가정통신문 서비스가 가져다 쓸 수 있는 AI 기능을 검증하는 것입니다.

따라서 Android 앱은 최종 제품이라기보다 실기기에서 흐름을 보여 주는 데모 클라이언트입니다. 핵심 기능은 서버 API와 모델 파이프라인입니다.

```text
기존 학교 앱/알림장 서비스
  -> 우리 FastAPI 서버 호출
  -> 체크리스트, 쉬운 한국어, 베트남어 번역, TTS 결과 수신
  -> 기존 앱 화면에 표시
```

### OCR 입력 경로 (현재 구현 상태)

카메라 입력 경로와 디지털 파일 경로 두 가지가 구현되어 있습니다.

**카메라 (학부모 홈 — OcrActivity)**
- ML Kit Korean 온디바이스 인식
- 전처리 4종 병렬: raw / grayscale+CLAHE / warped(원근 보정) / warped+CLAHE
- 2-pass 표 OCR: 전체 인식 → OpenCV 표 감지 → 표 영역 crop 재인식
- Quality Gate (overall ≥ 0.80) 미통과 시 재촬영 / 강제 전송 선택 UI
- 업로드: `POST /notice/upload-self`

**디지털 파일 (선생님 홈 — 서버사이드 parser.py)**
- HWP/HWPX: LibreOffice headless → pdfplumber
- PDF: pdfplumber 직접 처리
- 이미지(.jpg/.png 등): Tesseract fallback
- 업로드: `POST /notice/upload`

---

## 시연 전 최종 확인

**기본 (HF Spaces 실서버)**

- [ ] `https://maxmunzy-schoolbridge.hf.space/health` → `{"status":"ok"}` 응답 확인
- [ ] 시연 30분 전 warmup curl 1회 (위 "콜드스타트" 섹션 명령) → analyze 응답 정상
- [ ] `MainActivity.java`의 `BASE_URL`이 `https://maxmunzy-schoolbridge.hf.space`인지 확인
- [ ] 선생님 화면에서 PDF/사진 업로드 또는 발송 성공
- [ ] 학부모 화면 수신함 조회 — 카드 리스트 표시
- [ ] **카드 클릭 → 원본 PDF/이미지 풀화면**
- [ ] **우상단 ✨ AI → 분석 결과 표시**
- [ ] TTS 재생
- [ ] 서버 실패 상황에서도 고정 데모 결과 보기 동작

**로컬 백엔드 사용 시 (옵션)**

- [ ] `docker compose up --build`
- [ ] PC에서 `http://localhost:8000/docs` 접속
- [ ] 휴대폰에서 `http://PC_IP:8000/docs` 접속
- [ ] `MainActivity.java`의 `BASE_URL`을 PC IP로 임시 변경 (커밋 금지)
