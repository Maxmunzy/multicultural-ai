# 백엔드 단위테스트

> 강사 피드백(2026-04-28) 대응: *"단위테스트 끝나고 통합테스트 할 때 합의된 기준/절차에 의해 merge"*  
> → PR이 권한 검증·다국어 사전 로딩을 깨지 않는다는 자동 증빙 레이어.

## 구성

| 파일 | 검증 대상 |
| --- | --- |
| `test_auth_routes.py` | X-User-Id 헤더 인증, 역할(teacher/parent) 권한, 발송→수신 통합 흐름 |
| `test_glossary.py` | 다국어 용어사전(8개) 컬럼 동적 로딩, find_glossary_hits 언어별 동작 |

## 실행

### 도커 컨테이너에서

```bash
docker compose exec backend pip install -r /app/../backend/requirements-dev.txt
# 또는: docker compose exec backend pip install pytest httpx
docker compose exec backend pytest /app/../backend/tests -v
```

### CI (GitHub Actions)에서

PR 시 자동 실행 — `.github/workflows/backend-tests.yml` 참조.

## 추가 테스트 가이드

- 모델 호출(KoELECTRA / NLLB / Edge-TTS)은 무거우므로 직접 호출 X. 필요 시 monkey-patch로 가짜 응답 사용.
- 새 라우트 추가 시 권한 검증 케이스(teacher/parent/anonymous) 3종 모두 작성.
- 테스트는 빠르게 (총 실행시간 30초 이내 목표).
