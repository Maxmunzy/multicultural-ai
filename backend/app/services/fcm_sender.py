"""Firebase Cloud Messaging — 학부모 폰에 새 가정통신문 알림 push.

선생님이 /notice/send 또는 /notice/upload로 새 통신문을 보내면, 해당 학부모의
등록된 FCM 토큰으로 시스템 알림을 발사한다. 학부모가 앱을 닫고 폰을 잠가도
Google FCM 인프라를 통해 알림 도달.

토큰은 안드 앱이 부팅·로그인 시점에 /notice/register-fcm-token 으로 등록.
인메모리 dict 저장 (학부모 ID → 토큰 + 선호 언어). 학부모 로그아웃 또는
컨테이너 재시작 시 토큰 재등록 필요.

키 파일: 서비스 계정 JSON. 환경변수 `FIREBASE_ADMIN_KEY_PATH` 또는
backend 폴더의 `*firebase-adminsdk*.json` 자동 탐지.
키 없으면 모든 호출이 status="skip:no_key"로 우회 — 서버 부팅 안 막음.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Lazy import — firebase-admin 없으면 SDK 사용 안 함 (CI/로컬 개발용)
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    _FCM_SDK_AVAILABLE = True
except ImportError:
    firebase_admin = None  # type: ignore[assignment]
    credentials = None  # type: ignore[assignment]
    messaging = None  # type: ignore[assignment]
    _FCM_SDK_AVAILABLE = False


_app: object | None = None  # firebase_admin.App
_init_status: str = "uninitialized"
_resolved_key_path: str = ""


# (parent_id 또는 teacher_id) → {"token": str, "lang": str}
# lang 은 안드가 등록 시 자기 target_language 로 보냄. 알림 텍스트 다국어용.
_tokens: dict[str, dict[str, str]] = {}


# 9개 언어 알림 텍스트 — 안드 STT_TIPS 와 매칭
_NOTIF_TEXT: dict[str, tuple[str, str]] = {
    "ko":      ("새 가정통신문 도착",         "통신문이 도착했습니다."),
    "ko_easy": ("새 가정통신문 도착",         "통신문이 도착했어요."),
    "vi":      ("Có thông báo mới từ trường", "Vui lòng nhấn để xem chi tiết."),
    "vi_demo": ("새 가정통신문 도착",         "통신문이 도착했습니다."),  # 시연용 한국어
    "en":      ("New school notice",          "Tap to view details."),
    "ru":      ("Новое уведомление школы",    "Нажмите, чтобы просмотреть."),
    "ms":      ("Notis baru dari sekolah",    "Ketik untuk melihat butiran."),
    "mn":      ("Сургуулиас шинэ мэдэгдэл",   "Дэлгэрэнгүйг харахын тулд дарна уу."),
    "zh":      ("学校新通知",                 "点按以查看详情。"),
    "th":      ("มีประกาศใหม่จากโรงเรียน",   "แตะเพื่อดูรายละเอียด"),
    "ja":      ("学校から新しいお知らせ",       "タップして詳細を確認してください。"),
}


def _resolve_key_path() -> str:
    """ENV → backend/*firebase-adminsdk*.json → /app/firebase-admin-key.json 순으로 탐지."""
    env_path = os.environ.get("FIREBASE_ADMIN_KEY_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path

    # backend 폴더 내 자동 탐지 (Firebase 콘솔이 만든 기본 이름 패턴)
    candidates: list[Path] = []
    for base in (Path("backend"), Path("/app"), Path(".")):
        if base.exists():
            candidates.extend(base.glob("*firebase-adminsdk*.json"))
            candidates.extend(base.glob("firebase-admin-key.json"))

    for c in candidates:
        if c.is_file():
            return str(c.resolve())
    return ""


def initialize() -> str:
    """firebase_admin app 1회 초기화. 멱등(idempotent). 상태 문자열 반환."""
    global _app, _init_status, _resolved_key_path
    if _app is not None:
        return _init_status

    if not _FCM_SDK_AVAILABLE:
        _init_status = "skip:no_sdk"
        logger.warning("[fcm] firebase-admin SDK 미설치 — FCM 비활성")
        return _init_status

    _resolved_key_path = _resolve_key_path()
    if not _resolved_key_path:
        _init_status = "skip:no_key"
        logger.warning(
            "[fcm] 서비스 계정 키 파일 못 찾음 — FCM 비활성. "
            "FIREBASE_ADMIN_KEY_PATH 환경변수 또는 backend/*firebase-adminsdk*.json 필요"
        )
        return _init_status

    try:
        cred = credentials.Certificate(_resolved_key_path)
        _app = firebase_admin.initialize_app(cred)
        _init_status = "ok"
        logger.info("[fcm] 초기화 완료 (key=%s)", _resolved_key_path)
    except Exception as error:
        _init_status = f"error:{type(error).__name__}"
        logger.warning("[fcm] 초기화 실패: %s", error)
    return _init_status


def status() -> str:
    """현재 초기화 상태 + 등록된 토큰 수."""
    return f"{_init_status}, tokens={len(_tokens)}"


def register_token(user_id: str, token: str, lang: str = "ko") -> None:
    """안드 앱이 로그인 시점에 호출 — 학부모 ID(또는 선생님 ID)와 토큰 매핑."""
    _tokens[user_id] = {"token": token, "lang": lang or "ko"}
    logger.info(
        "[fcm] 토큰 등록 user_id=%s lang=%s token=…%s",
        user_id, lang, token[-10:] if token else "EMPTY",
    )


def unregister_token(user_id: str) -> None:
    """로그아웃 시점에 호출 — 알림 끊기."""
    if _tokens.pop(user_id, None) is not None:
        logger.info("[fcm] 토큰 제거 user_id=%s", user_id)


def get_lang(user_id: str) -> str:
    entry = _tokens.get(user_id)
    return (entry or {}).get("lang", "ko")


def send_to_user(
    user_id: str,
    notice_id: str,
    text_preview: str = "",
    title_override: str | None = None,
) -> str:
    """학부모(또는 선생님)에게 새 통신문 도착 알림 발사.

    Returns 상태 문자열:
      "ok" / "skip:not_initialized" / "skip:no_token" / "error:..."
    """
    if _app is None:
        return "skip:not_initialized"
    if not _FCM_SDK_AVAILABLE:
        return "skip:no_sdk"

    entry = _tokens.get(user_id)
    if not entry or not entry.get("token"):
        return "skip:no_token"

    lang = entry.get("lang") or "ko"
    title_default, body_default = _NOTIF_TEXT.get(lang, _NOTIF_TEXT["ko"])
    title = title_override or title_default
    # body 에 통신문 첫 줄 prefix 를 붙여 학부모가 알림만 봐도 어느 통신문인지 감 잡게.
    body = body_default
    if text_preview:
        snippet = (text_preview.strip().split("\n", 1)[0] or "")[:60]
        if snippet:
            body = f"{snippet}\n{body_default}"

    msg = messaging.Message(
        notification=messaging.Notification(title=title, body=body),
        data={
            "notice_id": notice_id,
            "lang": lang,
        },
        token=entry["token"],
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id="schoolbridge_inbox",
                sound="default",
            ),
        ),
    )
    try:
        msg_id = messaging.send(msg)
        logger.info(
            "[fcm] send ok user_id=%s notice_id=%s msg_id=%s",
            user_id, notice_id, msg_id,
        )
        return "ok"
    except Exception as error:
        # 토큰 만료(UNREGISTERED)면 정리해서 다음 호출에 헛수고 안 함
        err_name = type(error).__name__
        msg_str = str(error)
        if "UNREGISTERED" in msg_str or "not registered" in msg_str.lower():
            unregister_token(user_id)
            return "skip:token_unregistered"
        logger.warning(
            "[fcm] send fail user_id=%s notice_id=%s: %s",
            user_id, notice_id, error,
        )
        return f"error:{err_name}"
