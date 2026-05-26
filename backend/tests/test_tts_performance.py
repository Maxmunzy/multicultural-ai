import asyncio

from app.models.schemas import SlotCard
from app.routers import notice
from app.services import tts


def test_build_tts_text_from_cards_limits_text_length():
    cards = [
        SlotCard(
            header_ko=f"헤더{i}",
            value_ko=("긴 문장입니다. " * 20),
            value_easy_ko=("쉬운 문장입니다. " * 20),
        )
        for i in range(16)
    ]

    text = notice._build_tts_text_from_cards(cards, "easy_ko", max_chars=300)

    assert len(text) <= 300
    assert text


def test_generate_tts_pair_runs_both_sides_concurrently(monkeypatch):
    calls = []

    async def fake_generate(text: str, target_lang: str = "vi", tts_engine: str = "edge") -> str:
        calls.append((text, target_lang, tts_engine))
        await asyncio.sleep(0.01)
        return f"/static/tts/{target_lang}.mp3"

    monkeypatch.setattr(notice, "generate_tts_file", fake_generate)

    result = asyncio.run(notice._generate_tts_pair("translated", "easy", "vi"))

    assert result == ("/static/tts/vi.mp3", "/static/tts/ko_easy.mp3")
    assert ("translated", "vi", "edge") in calls
    assert ("easy", "ko_easy", "edge") in calls


def test_generate_tts_pair_one_side_failure(monkeypatch):
    async def fake_generate(text: str, target_lang: str = "vi", tts_engine: str = "edge") -> str:
        if target_lang == "vi":
            raise RuntimeError("edge timeout")
        return "/static/tts/easy.mp3"

    monkeypatch.setattr(notice, "generate_tts_file", fake_generate)

    result = asyncio.run(notice._generate_tts_pair("translated", "easy", "vi"))

    assert result == ("", "/static/tts/easy.mp3")


def test_tts_cache_filename_is_stable(monkeypatch, tmp_path):
    saves = []
    monkeypatch.setattr(tts, "STATIC_DIR", tmp_path)

    class FakeCommunicate:
        def __init__(self, text: str, voice: str):
            self.text = text
            self.voice = voice

        async def save(self, path: str):
            saves.append(path)
            with open(path, "wb") as f:
                f.write(b"mp3")

    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeCommunicate)

    first = asyncio.run(tts.generate_tts_file("same text", "vi"))
    second = asyncio.run(tts.generate_tts_file("same text", "vi"))

    assert first == second
    assert len(saves) == 1
