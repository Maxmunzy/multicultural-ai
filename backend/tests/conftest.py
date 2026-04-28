"""백엔드 테스트 공통 픽스처.

모델(KoELECTRA / NLLB / Edge-TTS) 호출은 무거우므로
auth/route 흐름 테스트에서는 monkey-patch로 가짜 응답을 사용한다.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """lifespan(seed_demo_users) 트리거를 위해 with 블록 안에서 사용."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def teacher_headers():
    return {"X-User-Id": "teacher_001"}


@pytest.fixture
def teacher2_headers():
    return {"X-User-Id": "teacher_002"}


@pytest.fixture
def parent_headers():
    return {"X-User-Id": "parent_001"}


@pytest.fixture
def parent2_headers():
    return {"X-User-Id": "parent_002"}
