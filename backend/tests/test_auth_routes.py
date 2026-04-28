"""권한 분리 라우트 테스트.

강사 피드백(2026-04-28): "단위테스트 끝나고 통합테스트 할 때 합의된 기준/절차에 의해 merge"
→ 운영 PR이 권한 검증을 깨지 않는다는 자동 증빙.
"""


def test_health_ok(client):
    """기본 헬스체크 — 모델 로드 없이 즉시 응답."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_send_notice_requires_teacher_role(client, parent_headers):
    """학부모 ID로 발송 시도 → 403."""
    payload = {"teacher_id": "teacher_001", "parent_id": "parent_001", "text": "테스트"}
    r = client.post("/notice/send", json=payload, headers=parent_headers)
    assert r.status_code == 403
    assert "선생님 권한" in r.json()["detail"]


def test_send_notice_teacher_id_must_match_header(client, teacher_headers):
    """헤더(teacher_001) ≠ body.teacher_id(teacher_002) → 403."""
    payload = {"teacher_id": "teacher_002", "parent_id": "parent_001", "text": "테스트"}
    r = client.post("/notice/send", json=payload, headers=teacher_headers)
    assert r.status_code == 403
    assert "본인 선생님 ID" in r.json()["detail"]


def test_send_notice_unknown_parent(client, teacher_headers):
    """존재하지 않는 학부모로 발송 → 404."""
    payload = {"teacher_id": "teacher_001", "parent_id": "parent_999", "text": "테스트"}
    r = client.post("/notice/send", json=payload, headers=teacher_headers)
    assert r.status_code == 404
    assert "학부모 계정을 찾을 수 없습니다" in r.json()["detail"]


def test_inbox_self_only(client, parent_headers, parent2_headers):
    """parent_001은 본인 수신함 OK, parent_002의 수신함 조회는 403."""
    r1 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r1.status_code == 200

    r2 = client.get("/notice/inbox/parent_001", headers=parent2_headers)
    assert r2.status_code == 403


def test_inbox_requires_user_header(client):
    """X-User-Id 헤더 없으면 422 (FastAPI Header 필수 검증)."""
    r = client.get("/notice/inbox/parent_001")
    assert r.status_code == 422


def test_unknown_user_id_rejected(client):
    """등록 안 된 ID로 헤더 → 401."""
    r = client.get("/notice/inbox/parent_001", headers={"X-User-Id": "ghost_999"})
    assert r.status_code == 401
    assert "등록되지 않은 사용자" in r.json()["detail"]


def test_send_then_receive_flow(client, teacher_headers, parent_headers):
    """발송 후 학부모 수신함에 보임 (권한 흐름 통합 검증)."""
    payload = {"teacher_id": "teacher_001", "parent_id": "parent_001", "text": "단위테스트 통신문"}
    r1 = client.post("/notice/send", json=payload, headers=teacher_headers)
    assert r1.status_code == 200
    notice_id = r1.json()["data"]["notice_id"]
    assert notice_id

    r2 = client.get("/notice/inbox/parent_001", headers=parent_headers)
    assert r2.status_code == 200
    inbox = r2.json()["data"]
    assert any(n["notice_id"] == notice_id for n in inbox)
