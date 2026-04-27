# Translation/TTS MVP

![세종 파트 현재 상태](../../docs/assets/translation_tts_status.png)

## 현재 상태

Translation/TTS 파트는 쉬운 한국어 입력에서 베트남어 번역, 학교 용어사전 검수, Edge-TTS 음성 출력까지 1차 MVP 실행을 완료했다.

핵심은 단순 번역이 아니라 `번역 + 용어사전 검수 + TTS + 실패 안전장치` 흐름이다. 일반 번역 결과가 자연스럽더라도 `도시락 -> cơm hộp`처럼 학교 안내문에서 중요한 준비물 용어가 누락될 수 있으므로, glossary check로 검수 지점을 명확히 남긴다.

## 주요 파일

- `run_mvp_pipeline.py`: MVP 파이프라인 실행 스크립트
- `term_glossary.csv`: 학교 특화 한국어-베트남어 용어사전
- `requirements-translation-tts.txt`: 번역/TTS 파트 실행 의존성
- `../../data/translation_tts/easy_ko_text_sample.csv`: 샘플 입력
- `../../demo/translation_tts/demo_case_01/`: 고정 데모 산출물

## 실행 예시

```bash
python model/translation_tts/run_mvp_pipeline.py --input data/translation_tts/easy_ko_text_sample.csv --output-dir outputs/mvp --save-demo-case demo_case_01
```

## 데모 케이스

`demo/translation_tts/demo_case_01/`에는 다음 산출물을 고정 보관한다.

- `01_easy_ko_input.txt`
- `02_vi_raw_translation.txt`
- `03_glossary_check.csv`
- `04_review_needed.md`
- `05_vi_corrected_translation.txt`
- `06_tts_output.mp3`
- `demo_summary.md`
