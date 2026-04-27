from fastapi import APIRouter

from app.auth import get_user as _get_user, list_users, upsert_user
from app.models.schemas import ApiResponse, UserProfile

router = APIRouter()


@router.get("/", response_model=ApiResponse)
def list_all_users():
    """등록된 사용자 전체 목록 (시연용)."""
    return ApiResponse.success(data=list_users())


@router.get("/{user_id}", response_model=ApiResponse)
def get_user(user_id: str):
    """사용자 프로파일 조회 (한국어 수준, 학년, TTS 속도)."""
    profile = _get_user(user_id)
    if profile is None:
        return ApiResponse.error(message="사용자 없음")
    return ApiResponse.success(data=profile)


@router.post("/", response_model=ApiResponse)
def save_user(profile: UserProfile):
    """사용자 프로파일 저장/수정. 시연 시 학부모/선생님 계정 등록에도 사용."""
    saved = upsert_user(profile)
    return ApiResponse.success(data=saved)
