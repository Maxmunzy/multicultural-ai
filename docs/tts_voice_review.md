# TTS Voice Review

공모전 데모용 TTS는 “듣기 편안함”을 우선 기준으로 검수합니다. 현재 실험은 Edge-TTS 기본 보이스와 MMS-TTS 로컬 모델을 같은 짧은 학교 안내문으로 비교하는 방식입니다.

## 1. Edge-TTS Comfort Samples

Edge-TTS는 현재 MVP 기본 엔진입니다. 아래 샘플은 기본 보이스를 유지하고, 발표장에서 너무 빠르게 들리지 않도록 속도를 낮춘 버전입니다.

공통 설정:

| 항목 | 값 |
| --- | --- |
| rate | `-12%` |
| pitch | `-2Hz` |
| volume | `+0%` |

| 언어 | 기본 voice | 샘플 파일 |
| --- | --- | --- |
| 베트남어 | `vi-VN-HoaiMyNeural` | `outputs/tts_voice_probe/comfort_vi.mp3` |
| 영어 | `en-US-JennyNeural` | `outputs/tts_voice_probe/comfort_en.mp3` |
| 중국어 | `zh-CN-XiaoxiaoNeural` | `outputs/tts_voice_probe/comfort_zh.mp3` |
| 일본어 | `ja-JP-NanamiNeural` | `outputs/tts_voice_probe/comfort_ja.mp3` |
| 러시아어 | `ru-RU-SvetlanaNeural` | `outputs/tts_voice_probe/comfort_ru.mp3` |
| 말레이시아어 | `ms-MY-YasminNeural` | `outputs/tts_voice_probe/comfort_ms.mp3` |
| 몽골어 | `mn-MN-YesuiNeural` | `outputs/tts_voice_probe/comfort_mn.mp3` |
| 태국어 | `th-TH-PremwadeeNeural` | `outputs/tts_voice_probe/comfort_th.mp3` |

## 2. MMS-TTS Samples

MMS-TTS는 Edge-TTS 목소리 자체가 불편하다는 피드백에 대응하기 위한 비교 후보입니다. 실험레포에서 실행한 결과, 8개 지원 언어 중 6개 언어는 샘플 생성에 성공했고, 중국어 표준어와 일본어는 MMS-TTS의 해당 체크포인트를 찾지 못했습니다.

| 언어 | MMS model | 결과 | 샘플 파일 | 메모 |
| --- | --- | --- | --- | --- |
| 베트남어 | `facebook/mms-tts-vie` | 성공 | `outputs/tts_mms_probe/mms_vi.wav` | Edge 대체 후보 |
| 영어 | `facebook/mms-tts-eng` | 성공 | `outputs/tts_mms_probe/mms_en.wav` | Edge 대체 후보 |
| 러시아어 | `facebook/mms-tts-rus` | 성공 | `outputs/tts_mms_probe/mms_ru.wav` | 팀 피드백상 부자연스러움 확인 필요 |
| 말레이시아어 | `facebook/mms-tts-zlm` | 성공 | `outputs/tts_mms_probe/mms_ms.wav` | `zsm`이 아니라 `zlm` 모델 사용 |
| 몽골어 | `facebook/mms-tts-mon` | 성공 | `outputs/tts_mms_probe/mms_mn.wav` | 음질 깨짐 피드백 확인 필요 |
| 태국어 | `facebook/mms-tts-tha` | 성공 | `outputs/tts_mms_probe/mms_th.wav` | 발음/문장 길이 영향 확인 필요 |
| 중국어 | `facebook/mms-tts-cmn` | 실패 | - | Hugging Face API 확인 결과 `cmn`/`zho` 없음. Min Nan(`nan`), Hakka(`hak`)만 확인되어 현재 목표인 표준 중국어와 다름 |
| 일본어 | `facebook/mms-tts-jpn` | 실패 | - | Hugging Face API 확인 결과 `jpn`/`jap` 없음. `ja` 검색 결과는 `jac`/`jam`/`jav`로 일본어가 아님 |

## 3. 비교 판단표

팀원이 샘플을 듣고 아래 기준으로 1~5점 평가합니다.

| 언어 | Edge 샘플 | MMS 샘플 | 자연스러움 | 발음 명확도 | 듣기 편안함 | 최종 후보 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| vi | `comfort_vi.mp3` | `mms_vi.wav` |  |  |  |  |
| en | `comfort_en.mp3` | `mms_en.wav` |  |  |  |  |
| ru | `comfort_ru.mp3` | `mms_ru.wav` |  |  |  |  |
| ms | `comfort_ms.mp3` | `mms_ms.wav` |  |  |  |  |
| mn | `comfort_mn.mp3` | `mms_mn.wav` |  |  |  |  |
| th | `comfort_th.mp3` | `mms_th.wav` |  |  |  |  |
| zh | `comfort_zh.mp3` | MMS 없음 |  |  |  | Edge 유지 또는 별도 후보 필요 |
| ja | `comfort_ja.mp3` | MMS 없음 |  |  |  | Edge 유지 또는 별도 후보 필요 |

## 4. 현재 결론

- Edge-TTS는 8개 언어 모두 바로 지원하므로 MVP 안정성 측면에서 가장 안전합니다.
- MMS-TTS는 6개 언어에서 대체 후보 샘플을 만들 수 있었지만, 중국어와 일본어는 현재 실험 범위에서 샘플 생성에 실패했습니다.
- 따라서 “8개국어 전체를 동일 엔진으로 유지”하려면 Edge-TTS가 현실적입니다.
- “베트남어 등 특정 언어의 목소리 개선”이 목표라면 MMS-TTS를 언어별 선택 엔진으로 검토할 수 있습니다.
- MMS-TTS는 라이선스와 상업적 사용 조건을 별도로 확인해야 하므로, 사업화 문서에서는 운영 기본 엔진이 아니라 실험 후보로 표현하는 것이 안전합니다.

## 5. 재생성 명령

Edge-TTS comfort 샘플:

```cmd
python model\translation_tts\tts_voice_probe.py --lang vi --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_vi.mp3
python model\translation_tts\tts_voice_probe.py --lang en --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_en.mp3
python model\translation_tts\tts_voice_probe.py --lang zh --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_zh.mp3
python model\translation_tts\tts_voice_probe.py --lang ja --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_ja.mp3
python model\translation_tts\tts_voice_probe.py --lang ru --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_ru.mp3
python model\translation_tts\tts_voice_probe.py --lang ms --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_ms.mp3
python model\translation_tts\tts_voice_probe.py --lang mn --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_mn.mp3
python model\translation_tts\tts_voice_probe.py --lang th --rate=-12% --pitch=-2Hz --output outputs\tts_voice_probe\comfort_th.mp3
```

MMS-TTS 샘플:

```cmd
python model\translation_tts\mms_voice_probe.py --lang vi --output-dir outputs\tts_mms_probe --device cpu
python model\translation_tts\mms_voice_probe.py --lang en --output-dir outputs\tts_mms_probe --device cpu
python model\translation_tts\mms_voice_probe.py --lang ru --output-dir outputs\tts_mms_probe --device cpu
python model\translation_tts\mms_voice_probe.py --lang ms --output-dir outputs\tts_mms_probe --device cpu
python model\translation_tts\mms_voice_probe.py --lang mn --output-dir outputs\tts_mms_probe --device cpu
python model\translation_tts\mms_voice_probe.py --lang th --output-dir outputs\tts_mms_probe --device cpu
```

## 6. Hugging Face 모델 검색 확인

`huggingface_hub.list_models(author="facebook", search="mms-tts-")` 기준으로 다시 확인했습니다.

| 검색 코드 | 결과 | 판단 |
| --- | --- | --- |
| `cmn`, `zho`, `chi`, `yue` | 0건 | 표준 중국어/광둥어 MMS-TTS 확인 불가 |
| `nan` | `facebook/mms-tts-nan` | Chinese Min Nan 방언. 표준 중국어 아님 |
| `hak` | `facebook/mms-tts-hak` | Hakka Chinese. 표준 중국어 아님 |
| `jpn`, `jap` | 0건 | 일본어 MMS-TTS 확인 불가 |
| `ja` | `jac`, `jam`, `jav` | 각각 다른 ISO 639-3 언어 코드이며 일본어가 아님 |

따라서 현재 확인 가능한 facebook MMS-TTS 공식 체크포인트 기준으로는 중국어(표준어)와 일본어를 MMS로 대체하기 어렵습니다.