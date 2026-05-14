# NLLB Placeholder Survival Experiment

**날짜**: 2026-05-06  
**모델**: facebook/nllb-200-distilled-600M  
**설정**: num_beams=1, repetition_penalty=1.3, no_repeat_ngram_size=3  
**샘플 수**: 8개 문장 / 8개 형식

## 결과 요약

| Format | Placeholder 생존율 | 용어 보존율 | 평균속도 |
|---|---|---|---|
| `AAAA/BBBB/CCCC` | 100% | 100% | 1.81s | **<-- 최적**
| `XITEMX/YITEMY/Z` | 100% | 100% | 1.86s |
| `ITEMA/B/C` | 96% | 96% | 1.12s |
| `SUPPLYA/B/C` | 90% | 90% | 1.05s |
| `MATERIALA/B/C` | 85% | 85% | 1.01s |
| `ITEM_A_TOKEN/...` | 48% | 48% | 1.54s |
| `[ITEM_A]/[ITEM_B]` | 42% | 42% | 2.17s |
| `<ITEM_A>/<ITEM_B>` | 6% | 6% | 0.76s |

## Tokenizer Sub-token 분석

| Format | Token | Sub-tokens | 개수 |
|---|---|---|---|
| `ITEMA/B/C` | `ITEMA` | `▁IT EMA` | 2 |
| `ITEMA/B/C` | `ITEMB` | `▁IT EM B` | 3 |
| `ITEMA/B/C` | `ITEMC` | `▁IT EM C` | 3 |
| `AAAA/BBBB/CCCC` | `AAAA` | `▁AA AA` | 2 |
| `AAAA/BBBB/CCCC` | `BBBB` | `▁B BB B` | 3 |
| `AAAA/BBBB/CCCC` | `CCCC` | `▁C CC C` | 3 |
| `XITEMX/YITEMY/Z` | `XITEMX` | `▁X IT EM X` | 4 |
| `XITEMX/YITEMY/Z` | `YITEMY` | `▁Y IT EM Y` | 4 |
| `XITEMX/YITEMY/Z` | `ZITEMZ` | `▁Z IT EM Z` | 4 |
| `SUPPLYA/B/C` | `SUPPLYA` | `▁SU PP L YA` | 4 |
| `SUPPLYA/B/C` | `SUPPLYB` | `▁SU PP LY B` | 4 |
| `SUPPLYA/B/C` | `SUPPLYC` | `▁SU PP LY C` | 4 |
| `MATERIALA/B/C` | `MATERIALA` | `▁MAT ERI ALA` | 3 |
| `MATERIALA/B/C` | `MATERIALB` | `▁MAT ERI AL B` | 4 |
| `MATERIALA/B/C` | `MATERIALC` | `▁MAT ERI AL C` | 4 |
| `[ITEM_A]/[ITEM_B]` | `[ITEM_A]` | `▁[ IT EM _ A ]` | 6 |
| `[ITEM_A]/[ITEM_B]` | `[ITEM_B]` | `▁[ IT EM _ B ]` | 6 |
| `[ITEM_A]/[ITEM_B]` | `[ITEM_C]` | `▁[ IT EM _ C ]` | 6 |
| `<ITEM_A>/<ITEM_B>` | `<ITEM_A>` | `▁< IT EM _ A >` | 6 |
| `<ITEM_A>/<ITEM_B>` | `<ITEM_B>` | `▁< IT EM _ B >` | 6 |
| `<ITEM_A>/<ITEM_B>` | `<ITEM_C>` | `▁< IT EM _ C >` | 6 |
| `ITEM_A_TOKEN/...` | `ITEM_A_TOKEN` | `▁IT EM _ A _ TO K EN` | 8 |
| `ITEM_A_TOKEN/...` | `ITEM_B_TOKEN` | `▁IT EM _ B _ TO K EN` | 8 |
| `ITEM_A_TOKEN/...` | `ITEM_C_TOKEN` | `▁IT EM _ C _ TO K EN` | 8 |

## 샘플별 상세 결과 (Best format)

**Sample 1**: `대회에 나가면 도화지와 색칠 도구를 준비해 주세요`  
- 마스킹: `대회에 나가면 BBBB와 AAAA를 준비해 주세요`  
- NLLB: `Nếu bạn đi dự, hãy chuẩn bị cho BBBB và AAAA.`  
- 복원: `Nếu bạn đi dự, hãy chuẩn bị cho giấy vẽ và đồ dùng tô màu.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 2**: `유성매직과 사인펜을 준비해 주세요`  
- 마스킹: `AAAA과 BBBB을 준비해 주세요`  
- NLLB: `Hãy chuẩn bị cho AAAA và BBBB.`  
- 복원: `Hãy chuẩn bị cho bút dạ dầu và bút lông.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 3**: `풍선과 찰흙을 가져오세요`  
- 마스킹: `AAAA과 BBBB을 가져오세요`  
- NLLB: `Hãy mang AAAA và BBBB.`  
- 복원: `Hãy mang bóng bay và đất sét.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 4**: `실내화와 물통을 챙겨 주세요`  
- 마스킹: `AAAA와 BBBB을 챙겨 주세요`  
- NLLB: `Hãy lấy AAAA và BBBB.`  
- 복원: `Hãy lấy giày trong nhà và bình nước.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 5**: `수채화 물감과 붓을 준비해 주세요`  
- 마스킹: `AAAA과 BBBB을 준비해 주세요`  
- NLLB: `Hãy chuẩn bị cho AAAA và BBBB.`  
- 복원: `Hãy chuẩn bị cho màu nước và cọ vẽ.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 6**: `전교생은 체육복과 실내화를 지참해 주세요`  
- 마스킹: `AAAA은 체육복과 BBBB를 지참해 주세요`  
- NLLB: `AAAA, hãy tham gia vào các hoạt động thể dục và BBBB.`  
- 복원: `toàn thể học sinh, hãy tham gia vào các hoạt động thể dục và giày trong nhà.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 7**: `받아쓰기 공책과 클리어 화일을 제출해 주세요`  
- 마스킹: `AAAA과 BBBB을 제출해 주세요`  
- NLLB: `Xin xin AAAA và BBBB.`  
- 복원: `Xin xin vở chính tả và túi đựng tài liệu.`  
- 생존: 2/2 / 용어: 2/2  

**Sample 8**: `물감과 붓, 도화지를 담임선생님께 제출해 주세요`  
- 마스킹: `BBBB과 CCCC, AAAA를 담임선생님께 제출해 주세요`  
- NLLB: `Hãy gửi cho ngài người đứng đầu BBBB và CCCC, AAAA.`  
- 복원: `Hãy gửi cho ngài người đứng đầu màu vẽ và cọ vẽ, giấy vẽ.`  
- 생존: 3/3 / 용어: 3/3  

## 결론 및 권고

**최적 placeholder**: `AAAA/BBBB/CCCC`  

- Placeholder 생존율 100%, 용어 보존율 100%
- 실패 패턴은 위 상세 결과 참조

### 다음 단계
- 최적 형식을 `run_mvp_pipeline.py` glossary injection에 적용
- 서비스 적용 전 `backend/tests/test_translator_protection.py`에 회귀 테스트 추가