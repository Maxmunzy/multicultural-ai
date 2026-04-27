"""사용자 식별 + 역할 검증.

X-User-Id 헤더로 사용자를 식별하고, 역할(teacher/parent)에 따른 권한을 검증한다.
시연 단계라 별도 비밀번호/토큰 없이 헤더 한 줄로 처리. 실제 운영 시 JWT/세션 도입 예정.
"""
from fastapi import Depends, Header, HTTPException, status

from app.models.schemas import UserProfile

# 모듈 레벨 인메모리 사용자 저장소. user.py 라우터와 공유.
_user_store: dict[str, UserProfile] = {}


def get_user(user_id: str) -> UserProfile | None:
    return _user_store.get(user_id)


def upsert_user(profile: UserProfile) -> UserProfile:
    _user_store[profile.user_id] = profile
    return profile


def list_users() -> list[UserProfile]:
    return list(_user_store.values())


def seed_demo_users() -> None:
    """시연용 기본 계정 시드. 이미 존재하면 덮어쓰지 않음."""
    demos = [
        UserProfile(user_id="teacher_001", role="teacher"),
        UserProfile(user_id="teacher_002", role="teacher"),
        UserProfile(user_id="parent_001", role="parent"),
        UserProfile(user_id="parent_002", role="parent"),
        UserProfile(user_id="parent_003", role="parent"),
    ]
    for profile in demos:
        _user_store.setdefault(profile.user_id, profile)


def require_user(x_user_id: str = Header(..., description="요청자 사용자 ID")) -> UserProfile:
    """X-User-Id 헤더 필수. 등록되지 않은 ID면 401."""
    if not x_user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-User-Id 헤더가 필요합니다",
        )
    profile = _user_store.get(x_user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"등록되지 않은 사용자: {x_user_id}",
        )
    return profile


def require_teacher(user: UserProfile = Depends(require_user)) -> UserProfile:
    if user.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="선생님 권한이 필요합니다",
        )
    return user


def require_parent(user: UserProfile = Depends(require_user)) -> UserProfile:
    if user.role != "parent":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="학부모 권한이 필요합니다",
        )
    return user
