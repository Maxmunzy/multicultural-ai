# Template-Based Translation Experiment

- 실험일: 2026-05-06
- 모델: facebook/nllb-200-distilled-600M
- 디바이스: cpu
- 샘플 수: 8

## 최종 비교

| 방식 | 용어 보존율 | 평균 추론시간 |
|------|------------|---------------|
| Baseline NLLB | 1/17 (6%) | 1.02s |
| Strategy A (직접치환) | 9/17 (53%) | 0.87s |
| Template-based | 17/17 (100%) | 0.00s |

## 방법론

| 분류 | 키워드 | 베트남어 템플릿 |
|------|--------|----------------|
| prepare | 준비해 주세요, 준비해주세요, 준비하세요... | `Vui lòng chuẩn bị {items}.` |
| bring | 가져오세요, 챙겨 주세요, 챙겨주세요... | `Vui lòng mang theo {items}.` |
| submit | 제출해 주세요, 제출해주세요, 제출하세요... | `Vui lòng nộp {items}.` |
| attend | 참석해 주세요, 참석해주세요, 참석하세요... | `Vui lòng tham gia {items}.` |
| pay | 납부해 주세요, 납부해주세요, 납부하세요... | `Vui lòng thanh toán {items}.` |
| info | (기타) | NLLB fallback |

## 사용 글로서리

| 한국어 | 베트남어 |
|--------|----------|
| 수채화 물감 | màu nước |
| 색칠 도구 | đồ dùng tô màu |
| 유성매직 | bút dạ dầu |
| 사인펜 | bút lông |
| 받아쓰기 공책 | vở chính tả |
| 클리어 화일 | túi đựng tài liệu |
| 체육복 | quần áo thể dục |
| 도화지 | giấy vẽ |
| 찰흙 | đất sét |
| 풍선 | bóng bay |
| 실내화 | giày trong nhà |
| 물통 | bình nước |
| 물감 | màu vẽ |
| 붓 | cọ vẽ |

## 샘플별 결과

### [1] 대회에 나가면 도화지와 색칠 도구를 준비해 주세요

- **문장 유형**: `prepare`
- **감지된 용어**: 도화지 | 색칠 도구
- **기대 베트남어**: giấy vẽ | đồ dùng tô màu

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Nếu bạn đi dự, hãy chuẩn bị đồ sơn và công cụ vẽ. | 0/2 | 2.33s |
| Strategy A | Nếu bạn đi dự, hãy chuẩn bị giấy vẽ và đồ dùng tô màu. | 2/2 | 0.90s |
| Template (`template`) | Vui lòng chuẩn bị giấy vẽ và đồ dùng tô màu. | 2/2 | 0.00s |

### [2] 유성매직과 사인펜을 준비해 주세요

- **문장 유형**: `prepare`
- **감지된 용어**: 유성매직 | 사인펜
- **기대 베트남어**: bút dạ dầu | bút lông

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Hãy chuẩn bị cho tôi một cái bút và ký hiệu. | 0/2 | 0.76s |
| Strategy A | Hãy chuẩn bị bút dạ dầu và bút lông. | 2/2 | 0.96s |
| Template (`template`) | Vui lòng chuẩn bị bút dạ dầu và bút lông. | 2/2 | 0.00s |

### [3] 풍선과 찰흙을 가져오세요

- **문장 유형**: `bring`
- **감지된 용어**: 풍선 | 찰흙
- **기대 베트남어**: bóng bay | đất sét

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Mang bóng và lùn đi. | 0/2 | 0.55s |
| Strategy A | Hãy mang bóng bay và sét. | 1/2 | 0.55s |
| Template (`template`) | Vui lòng mang theo bóng bay và đất sét. | 2/2 | 0.00s |

### [4] 실내화와 물통을 챙겨 주세요

- **문장 유형**: `bring`
- **감지된 용어**: 실내화 | 물통
- **기대 베트남어**: giày trong nhà | bình nước

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Hãy lấy đồ nội thất và bình nước. | 1/2 | 0.65s |
| Strategy A | Giày trong nhà và nước bình. | 0/2 | 0.64s |
| Template (`template`) | Vui lòng mang theo giày trong nhà và bình nước. | 2/2 | 0.00s |

### [5] 수채화 물감과 붓을 준비해 주세요

- **문장 유형**: `prepare`
- **감지된 용어**: 수채화 물감 | 붓
- **기대 베트남어**: màu nước | cọ vẽ

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Hãy chuẩn bị một cái bơm và nước lọc. | 0/2 | 0.84s |
| Strategy A | Hãy chuẩn bị cho chúng tôi nước và màu sắc. | 0/2 | 0.86s |
| Template (`template`) | Vui lòng chuẩn bị màu nước và cọ vẽ. | 2/2 | 0.00s |

### [6] 전교생은 체육복과 실내화를 지참해 주세요

- **문장 유형**: `bring`
- **감지된 용어**: 체육복 | 실내화
- **기대 베트남어**: quần áo thể dục | giày trong nhà

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Các bạn, hãy tham gia vào buổi tập thể dục và nội thất. | 0/2 | 1.20s |
| Strategy A | Các bạn, hãy tham gia phòng tập thể dục và giày trong. | 0/2 | 1.24s |
| Template (`template`) | Dành cho toàn thể học sinh: Vui lòng mang theo quần áo thể dục và giày trong nhà. | 2/2 | 0.00s |

### [7] 받아쓰기 공책과 클리어 화일을 제출해 주세요

- **문장 유형**: `submit`
- **감지된 용어**: 받아쓰기 공책 | 클리어 화일
- **기대 베트남어**: vở chính tả | túi đựng tài liệu

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Xin gửi giấy tờ nhận và thư xóa. | 0/2 | 0.73s |
| Strategy A | Xin hãy gửi vở chính tả và tài liệu trong túi. | 1/2 | 0.96s |
| Template (`template`) | Vui lòng nộp vở chính tả và túi đựng tài liệu. | 2/2 | 0.00s |

### [8] 물감과 붓, 도화지를 담임선생님께 제출해 주세요

- **문장 유형**: `submit`
- **감지된 용어**: 물감 | 붓 | 도화지
- **기대 베트남어**: màu vẽ | cọ vẽ | giấy vẽ

| 방식 | 출력 | 점수 | 시간 |
|------|------|------|------|
| Baseline | Hãy đưa cho ngài làm việc với bơm, bút và vải. | 0/3 | 1.10s |
| Strategy A | Hãy gửi màu vẽ và cọ vẽ, giấy vẽ cho giáo sư. | 3/3 | 0.84s |
| Template (`template`) | Vui lòng nộp màu vẽ, cọ vẽ và giấy vẽ cho giáo viên chủ nhiệm. | 3/3 | 0.00s |

## 분석

- 전체 샘플 8개 중 8개가 템플릿 번역 적용됨
- Template 방식: 17/17 (100%) vs Baseline 1/17 (6%)
- Template 방식은 Strategy A (9/17, 53%)와 비교해도 **47%p 더 높은** 용어 보존율 달성
- 템플릿 적용 샘플의 평균 추론시간: 0.00s (NLLB 불필요)
- **결론**: 준비물/제출물 문장(prepare/bring/submit)은 템플릿으로 안정적 처리 가능
