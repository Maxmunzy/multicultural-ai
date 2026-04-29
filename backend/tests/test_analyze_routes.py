"""`/notice/analyze` + `/notice/inbox` DELETE 권한 검증 + 슬롯 응답 shape 테스트.

핵심 라우트 권한 분리 + 강사 처방(2026-04-28) 슬롯 응답이 자동 게이트로 잡혀야 한다.
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


def _patch_models(monkeypatch, *, todos=None, category=None,
                  tts_url="/static/tts/fake.mp3"):
    """모델 호출 4종(추출/분류/번역2)을 한 번에 mock. 각 테스트가 인자만 바꿔쓰게."""
    from app.models.schemas import Category
    default_category = category or Category.other
    monkeypatch.setattr("app.routers.notice.extract_todos", lambda text: todos or [])
    monkeypatch.setattr("app.routers.notice.classify_category",
                        lambda text: default_category)
    monkeypatch.setattr("app.routers.notice.translate_short_sentence",
                        lambda text, target_lang: f"[VI]{text}")
    monkeypatch.setattr("app.routers.notice.translate_term",
                        lambda text, target_lang: f"[T]{text}")

    async def fake_tts(text, target_lang="vi"):
        return tts_url
    monkeypatch.setattr("app.routers.notice.generate_tts_file", fake_tts)


# ─────────────────────────────────────────
#  ANALYZE — 권한 게이트
# ─────────────────────────────────────────
_VI_BODY = {"target_language": "vi"}


def test_analyze_unknown_notice(client, parent_headers):
    r = client.post("/notice/analyze/ghost-id-xxx", json=_VI_BODY, headers=parent_headers)
    assert r.status_code == 404
    assert "찾을 수 없습니다" in r.json()["detail"]


def test_analyze_other_parent_blocked(client, teacher_headers, parent_headers, parent2_headers):
    notice_id = _seed_notice(client)
    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=parent2_headers)
    assert r.status_code == 403
    assert "본인의 가정통신문" in r.json()["detail"]


def test_analyze_teacher_role_blocked(client, teacher_headers):
    notice_id = _seed_notice(client)
    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=teacher_headers)
    assert r.status_code == 403


def test_analyze_missing_target_language_rejected(client, teacher_headers, parent_headers):
    """body에 target_language 없이 호출 → 422 (FastAPI body 검증)."""
    notice_id = _seed_notice(client)
    r = client.post(f"/notice/analyze/{notice_id}", json={}, headers=parent_headers)
    assert r.status_code == 422


# ─────────────────────────────────────────
#  ANALYZE — 슬롯 응답 shape (강사 처방)
# ─────────────────────────────────────────
def test_analyze_returns_slot_shape(client, parent_headers, monkeypatch):
    """응답이 summary + items 슬롯 구조 — translation 한 덩어리 필드 사라짐."""
    notice_id = _seed_notice(client, text="내일 도시락을 가져와 주세요.")
    _patch_models(monkeypatch)

    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=parent_headers)
    assert r.status_code == 200
    data = r.json()["data"]

    assert data["notice_id"] == notice_id
    assert data["target_language"] == "vi"

    # summary 6슬롯 모두 존재
    summary = data["summary"]
    for key in ("dates", "times", "places", "supplies", "amounts", "deadlines"):
        assert key in summary, f"summary 슬롯 누락: {key}"
        assert isinstance(summary[key], list)

    # items 리스트 + 각 item 필수 필드
    assert isinstance(data["items"], list)
    for item in data["items"]:
        for key in ("category", "action_hint", "title_ko", "title_translated",
                    "when", "where", "what", "amount", "deadline", "importance"):
            assert key in item, f"item 필드 누락: {key}"

    # 구버전 한 덩어리 필드는 빠져있어야 함 (안드 마이그레이션 확인용)
    assert "translation" not in data
    assert "vi_text" not in data
    assert "easy_ko_text" not in data
    assert "todos" not in data

    assert data["tts_url"] == "/static/tts/fake.mp3"


def test_analyze_regex_slots_filled_from_raw_text(client, parent_headers, monkeypatch):
    """원문에 날짜·시간·금액이 있으면 정규식 추출이 summary에 채워진다 (LLM 비의존 데이터)."""
    text = "5월 14일(수) 오전 9시 출발. 참가비 15,000원."
    notice_id = _seed_notice(client, text=text)
    _patch_models(monkeypatch)

    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=parent_headers)
    summary = r.json()["data"]["summary"]

    # 정규식 hit 3종 모두 잡혀야 함
    assert any(d["ko"] == "5월 14일(수)" for d in summary["dates"])
    assert any(t["ko"] == "오전 9시" for t in summary["times"])
    assert any(a["ko"] == "15,000원" for a in summary["amounts"])

    # source: "regex" 명시 — 강사 처방 "정규식 + 모델 하이브리드" 가시화
    assert all(d["source"] == "regex" for d in summary["dates"])
    assert all(t["source"] == "regex" for t in summary["times"])
    assert all(a["source"] == "regex" for a in summary["amounts"])


def test_analyze_supplies_aggregated_from_items(client, parent_headers, monkeypatch):
    """경이님 분류가 supplies로 잡힌 todo의 토큰이 summary.supplies로 집계 (강사 강조: 누락 금지)."""
    from app.models.schemas import Category, YunjeongTodo
    todos = [YunjeongTodo(
        text="도시락, 물통, 돗자리를 준비해 주세요",
        confidence=0.9,
        action_hint="준비",
    )]
    notice_id = _seed_notice(client, text="도시락, 물통, 돗자리를 준비해 주세요")
    _patch_models(monkeypatch, todos=todos, category=Category.supplies)

    r = client.post(f"/notice/analyze/{notice_id}", json=_VI_BODY, headers=parent_headers)
    supplies = r.json()["data"]["summary"]["supplies"]
    ko_tokens = [s["ko"] for s in supplies]
    assert "도시락" in ko_tokens
    assert "물통" in ko_tokens
    assert "돗자리" in ko_tokens


# ─────────────────────────────────────────
#  DELETE INBOX — 본인만 허용
# ─────────────────────────────────────────
def test_delete_inbox_self_only(client, teacher_headers, parent_headers, parent2_headers):
    notice_id = _seed_notice(client)
    r = client.delete("/notice/inbox/parent_001", headers=parent2_headers)
    assert r.status_code == 403

    r2 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r2.status_code == 200
    assert any(n["notice_id"] == notice_id for n in r2.json()["data"])


def test_delete_inbox_self_succeeds(client, teacher_headers, parent_headers):
    _seed_notice(client)
    _seed_notice(client, text="두 번째 통신문")

    r1 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert len(r1.json()["data"]) >= 2

    r2 = client.delete("/notice/inbox/parent_001", headers=parent_headers)
    assert r2.status_code == 200

    r3 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r3.json()["data"] == []
