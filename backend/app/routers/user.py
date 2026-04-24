from fastapi import APIRouter, HTTPException
from app.models.schemas import UserProfile

router = APIRouter()

_store: dict[str, UserProfile] = {}


@router.get("/{user_id}", response_model=UserProfile)
def get_user(user_id: str):
    """사용자 프로파일 조회 (한국어 수준, 학년, TTS 속도)."""
    if user_id not in _store:
        raise HTTPException(status_code=404, detail="사용자 없음")
    return _store[user_id]


@router.post("/", response_model=UserProfile)
def save_user(profile: UserProfile):
    """사용자 프로파일 저장/수정."""
    _store[profile.user_id] = profile
    return profile
