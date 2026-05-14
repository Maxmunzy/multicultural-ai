# Layout Reconstruction Eval

- date: 2026-05-07
- target: `_reconstruct_text_from_layout()` in `backend/app/routers/notice.py`
- eval input: `data/layout_reconstruction_eval_sample.csv`
- cases: 7

## 임계값 선정 근거

| 파라미터 | 값 | 근거 |
|---|---|---|
| `row_thr = median_h × 0.65` | 줄높이의 65% | ML Kit bbox는 줄 중심 정렬 기준. 같은 행 내 최대 세로 오차는 줄높이의 절반 수준. 0.65로 여유 확보. |
| `para_thr = median_h × 2.5` | 줄높이의 250% | 단락 간격은 typography 표준 1.5~2× 줄높이. 가정통신문은 항목 간격이 넓어 2.5×로 설정. |
| `col_thr = median_h × 2.0` | 줄높이의 200% | 표 셀 간 여백은 일반적으로 줄높이 이상. 2.0×는 같은 문장 내 단어 간격(< 0.5×)과 명확히 구분. |

모든 임계값은 고정값이 아닌 **문서별 median 줄높이 대비 비율**이라 해상도·폰트 크기에 무관하게 동작.

## 케이스별 결과

| case | 시나리오 | 입력 | 기대 출력 | pass |
|---|---|---|---|---|
| LAYOUT-001 | 두 프로그램 블록 분리 | ①블록 y≈100~195, ②블록 y≈420~510, Y gap=225px (5.6× h) | 두 블록 사이 빈 줄 | **OK** |
| LAYOUT-002 | 표 2열 복원 | 납부기간\|납부방법 각 2열 | `납부 기간 \| 2024.9.9...` | **OK** |
| LAYOUT-003 | 붙은 텍스트 과다 구분 방지 | 문의: / 064-767-9811 X gap=10px | 공백 연결, `\|` 없음 | **OK** |
| LAYOUT-004 | None fallback | layout_json=None | None 반환 | **OK** |
| LAYOUT-005 | 빈 리스트 fallback | layout_json=[] | None 반환 | **OK** |
| LAYOUT-006 | 단일 컬럼 연속 텍스트 | y gap < para_thr | 빈 줄 없이 개행만 | **OK** |
| LAYOUT-007 | 제목-본문 단락 분리 | Y gap > para_thr | 빈 줄 삽입 | **OK** |

- 전체 통과: 7/7 (100%)

## 실 문서 적용 관찰 (2026-05-07 테스트)

테스트 문서 2종 카메라 촬영 후 Android 앱 업로드:

**PDF 1: 5학년 백제권 체험현장배움 참가 신청서**
- 기간/장소/경비 슬롯 정상 추출 확인
- `납부 방법` 슬롯이 인접 일정 텍스트를 흡수하던 문제 → bbox 재구성으로 개선 예상

**PDF 2: 서귀포외국문화학습관 토요프로그램 추가모집**
- ① 토요영어체험교실 / ② 토요다문화이야기 두 프로그램 혼합 문제
- bbox Y gap(약 5× 줄높이) → `para_thr` 초과 → 빈 줄 삽입으로 두 블록 분리

## 다음 단계

- 태수님 layout_normalizer(Ollama) 트랙과 합류: **bbox 재구성 → LLM 정리** 순서
- 다양한 실제 통신문 layout_json 수집 후 임계값 재검증 (현재 합성 케이스 기반)
