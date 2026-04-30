from __future__ import annotations

import re


EASY_KO_DICT = {
    "제출": "제출(내기)",
    "납부": "납부(지불)",
    "준비물": "준비할 것",
    "방역지침": "마스크 착용 등 방역 규칙",
    "신청": "신청",
    "개인": "각자",
    "해당": "관련",
}

_PROTECTED_PATTERN = re.compile(
    r"("
    r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|"
    r"\d{1,2}\s*월\s*\d{1,2}\s*일"
    r"|"
    r"\d{1,2}\s*/\s*\d{1,2}"
    r"|"
    r"\d{1,3}(?:,\d{3})+원"
    r"|"
    r"\d+원"
    r")"
)
_PLACEHOLDER_PATTERN = re.compile(r"__EASY_KO_PROTECTED_(\d+)__")
_WORD_CHARS = r"가-힣A-Za-z0-9_"
_POLITE_ENDING_PATTERN = re.compile(r"(합니다|세요|입니다)[.!?]?$")


def _protect_patterns(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__EASY_KO_PROTECTED_{len(protected) - 1}__"

    return _PROTECTED_PATTERN.sub(stash, text), protected


def _restore_patterns(text: str, protected: list[str]) -> str:
    def restore(match: re.Match[str]) -> str:
        index = int(match.group(1))
        return protected[index] if index < len(protected) else match.group(0)

    return _PLACEHOLDER_PATTERN.sub(restore, text)


def _replace_terms(text: str) -> str:
    for source, target in EASY_KO_DICT.items():
        pattern = re.compile(rf"(?<![{_WORD_CHARS}]){re.escape(source)}(?![{_WORD_CHARS}])")
        text = pattern.sub(target, text)
    return text


def _make_ending_natural(text: str) -> str:
    stripped = text.strip()
    if not stripped or _POLITE_ENDING_PATTERN.search(stripped):
        return text

    suffix_map = {
        "신청": "신청해야 합니다",
        "제출(내기)": "제출해야 합니다",
        "준비": "준비해야 합니다",
        "참가": "참가해야 합니다",
    }

    trailing_punctuation = ""
    if stripped[-1] in ".!?":
        trailing_punctuation = stripped[-1]
        stripped = stripped[:-1].rstrip()

    for suffix, replacement in suffix_map.items():
        if stripped.endswith(suffix):
            return stripped[: -len(suffix)] + replacement + trailing_punctuation
    return text


def to_easy_korean(value_ko: str) -> str:
    try:
        if not value_ko:
            return value_ko
        masked, protected = _protect_patterns(value_ko)
        converted = _replace_terms(masked)
        converted = _make_ending_natural(converted)
        return _restore_patterns(converted, protected)
    except Exception:
        return value_ko


if __name__ == "__main__":
    samples = [
        "3월 17일까지 신청",
        "5,000원 납부",
        "개인 준비물 지참",
        "온라인 사전예약 후 방문 바랍니다",
        "방역지침 준수",
    ]
    for sample in samples:
        print(f"{sample} -> {to_easy_korean(sample)}")
