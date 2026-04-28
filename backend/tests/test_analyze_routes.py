"""`/notice/analyze` + `/notice/inbox` DELETE 권한 검증 테스트.

핵심 라우트인 분석 엔드포인트의 권한 분리가 자동 게이트로 잡혀야 한다.
모델 호출(KoELECTRA + NLLB + Edge-TTS)은 무거우므로 monkeypatch로 우회.
"""
import pytest


@pytest.fixture(autouse=True)
def reset_notices():
    """각 테스트 전 모듈 상태(_notices) 초기화로 순서 의존성 제거."""
    from app.routers import notice
    notice._notices.clear()
    yield
    notice._notices.clear()


# ─────────────────────────────────────────
#  공통 헬퍼: parent_001 앞으로 통신문 1건 발송
# ─────────────────────────────────────────
def _seed_notice(client, teacher_id="teacher_001", parent_id="parent_001",
                 text="테스트 통신문") -> str:
    payload = {"teacher_id": teacher_id, "parent_id": parent_id, "text": text}
    headers = {"X-User-Id": teacher_id}
    r = client.post("/notice/send", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["notice_id"]


# ─────────────────────────────────────────
#  ANALYZE — 권한 게이트 (모델 호출 도달 X, mock 불필요)
# ─────────────────────────────────────────
_VI_BODY = {"target_language": "vi"}


def test_analyze_unknown_notice(client, parent_headers):
    """존재하지 않는 notice_id → 404."""
    r = client.post("/notice/analyze/ghost-id-xxx", json=_VI_BODY, headers=parent_headers)
    assert r.status_code == 404
    assert "찾을 수 없습니다" in r.json()["detail"]


def test_analyze_other_parent_blocked(client, teacher_headers, parent_headers, parent2_headers):
    """parent_002가 parent_001 통신문 분석 시도 → 403."""
    notice_id = _seed_notice(client)  # parent_001에게 발송
    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=parent2_headers)
    assert r.status_code == 403
    assert "본인의 가정통신문" in r.json()["detail"]


def test_analyze_teacher_role_blocked(client, teacher_headers):
    """teacher 계정으로 분석 호출 → 403 (학부모 전용 엔드포인트)."""
    notice_id = _seed_notice(client)
    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=teacher_headers)
    assert r.status_code == 403
    assert "본인의 가정통신문" in r.json()["detail"]


def test_analyze_missing_target_language_rejected(client, teacher_headers, parent_headers):
    """body에 target_language 없이 호출 → 422 (FastAPI body 검증).
    default 자체를 없애 클라이언트가 항상 명시하도록 강제 — 서비스 정체성 변경
    시점에 default 논쟁을 피하기 위함.
    """
    notice_id = _seed_notice(client)
    r = client.post(f"/notice/analyze/{notice_id}", json={}, headers=parent_headers)
    assert r.status_code == 422


# ─────────────────────────────────────────
#  ANALYZE — 정상 흐름 (모델 mock)
# ─────────────────────────────────────────
def test_analyze_smoke_with_mock(client, parent_headers, monkeypatch):
    """정상 분석 흐름 — 모델 호출을 가짜로 두고 200/응답 형태 검증."""
    notice_id = _seed_notice(client, text="내일 도시락을 가져와 주세요.")

    # routers.notice 의 import된 이름을 패치 (from X import Y 패턴)
    fake_review = {
        "easy_ko_text": "내일 도시락을 가져오세요.",
        "translation": "Mang theo cơm hộp vào ngày mai.",
        "vi_text": "Mang theo cơm hộp vào ngày mai.",
        "target_language": "vi",
        "quality_note": "ok",
        "review_needed": "",
    }

    async def fake_tts(text, target_lang="vi"):
        return "/static/tts/fake.mp3"

    monkeypatch.setattr("app.routers.notice.extract_todos", lambda text: [])
    monkeypatch.setattr("app.routers.notice.review_todos", lambda todos: "")
    monkeypatch.setattr("app.routers.notice.translate_and_review",
                        lambda text, target_lang="vi": fake_review)
    monkeypatch.setattr("app.routers.notice.generate_tts_file", fake_tts)

    r = client.post(f"/notice/analyze/{notice_id}", json={"target_language": "vi"},
                    headers=parent_headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["notice_id"] == notice_id
    assert data["target_language"] == "vi"
    assert data["translation"] == "Mang theo cơm hộp vào ngày mai."
    assert data["tts_url"] == "/static/tts/fake.mp3"


# ─────────────────────────────────────────
#  DELETE INBOX — 본인만 허용
# ─────────────────────────────────────────
def test_delete_inbox_self_only(client, teacher_headers, parent_headers, parent2_headers):
    """parent_002가 parent_001 수신함 삭제 시도 → 403, 데이터 보존됨."""
    notice_id = _seed_notice(client)

    # parent_002가 parent_001 수신함 삭제 시도 → 403
    r = client.delete("/notice/inbox/parent_001", headers=parent2_headers)
    assert r.status_code == 403

    # parent_001 본인 수신함은 그대로 살아있음
    r2 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r2.status_code == 200
    assert any(n["notice_id"] == notice_id for n in r2.json()["data"])


def test_delete_inbox_self_succeeds(client, teacher_headers, parent_headers):
    """parent_001 본인이 본인 수신함 삭제 → 200, 통신문 사라짐."""
    _seed_notice(client)
    _seed_notice(client, text="두 번째 통신문")

    # 삭제 전 2건
    r1 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert len(r1.json()["data"]) >= 2

    # 본인 삭제
    r2 = client.delete("/notice/inbox/parent_001", headers=parent_headers)
    assert r2.status_code == 200

    # 삭제 후 0건
    r3 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r3.json()["data"] == []
