"""Hybrid Sentence Extractor 추론 — PDF → sentence_list.

학습된 hybrid_best.pt로 PDF page를 처리해서 char별 BIO 예측 → B 위치마다 sentence 분리.

흐름 (학습과 동일):
  PDF page → word + bbox + image
  → LayoutXLMProcessor + KoCharELECTRA tokenizer
  → HybridSentenceExtractor.forward
  → char별 BIO logits
  → B 위치마다 sentence 시작 (변형 0: 원문 char substring)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import torch


class HybridInferer:
    """Hybrid 모델 추론 wrapper."""

    def __init__(self, checkpoint_path: str | Path, device: str | None = None):
        from transformers import LayoutXLMProcessor, AutoTokenizer
        from hybrid_model import HybridSentenceExtractor, HybridConfig

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        ckpt = torch.load(str(checkpoint_path), map_location=self.device, weights_only=False)
        # config 복원
        config_dict = ckpt.get("config", {})
        # tuple 복원 (json save 시 list로 됐을 수도)
        if "class_weights" in config_dict and isinstance(config_dict["class_weights"], list):
            config_dict["class_weights"] = tuple(config_dict["class_weights"])
        config = HybridConfig(**config_dict)

        self.model = HybridSentenceExtractor(config).to(self.device)
        self.model.load_state_dict(ckpt["state_dict"])
        self.model.eval()

        self.processor = LayoutXLMProcessor.from_pretrained(config.layoutxlm_id, apply_ocr=False)
        self.tokenizer = AutoTokenizer.from_pretrained(config.kochar_id)
        self.config = config
        print(f"Hybrid loaded: device={self.device}, trainable_only={sum(p.numel() for p in self.model.parameters() if p.requires_grad)/1e6:.1f}M", file=sys.stderr)

    def _extract_page(
        self, pdf_path: Path, page_idx: int, use_camelot: bool = True,
    ) -> tuple[list[str], list[list[int]], Any] | None:
        """Page → word + bbox + image.

        한글자 word 단편 합치기 (자간 큰 헤더 처리) — 학습 데이터와 동일 로직.

        use_camelot=True: 표 영역을 camelot으로 EAV(header: value)로 재구성
            - 본문은 pdfplumber 그대로
            - 표 영역 word 제거 → camelot으로 cell 추출 → "header: value" word 생성
            - reading order(y, x)로 merge
        """
        import pdfplumber
        import fitz
        from PIL import Image
        from parser_ensemble import dedup_overlapping_words, merge_singleton_words

        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return None
            raw_words = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            raw_words = dedup_overlapping_words(raw_words)
            raw_words = merge_singleton_words(raw_words)

            # v11 axis: 표 영역 word를 camelot EAV로 재구성
            table_bboxes_pp: list[tuple[float, float, float, float]] = []
            if use_camelot:
                try:
                    table_bboxes_pp = [tbl.bbox for tbl in page.find_tables()]
                except Exception:
                    table_bboxes_pp = []

            def _in_any_table(w: dict) -> bool:
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                return any(
                    bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3]
                    for bx in table_bboxes_pp
                )

            if table_bboxes_pp:
                # 본문 word만 (표 영역 제외)
                raw_words = [w for w in raw_words if not _in_any_table(w)]
                # camelot으로 표 cell → EAV word 추가
                eav_words = self._extract_table_eav_words(
                    pdf_path, page_idx, table_bboxes_pp, W, H,
                )
                raw_words = raw_words + eav_words
                # reading order (y, x) 정렬
                raw_words.sort(key=lambda w: (round(w["top"] / 5) * 5, w["x0"]))

            words: list[str] = []
            bboxes: list[list[int]] = []
            for w in raw_words:
                words.append(w["text"])
                x0, y0, x1, y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                bboxes.append([
                    max(0, min(1000, int(x0 / W * 1000))),
                    max(0, min(1000, int(y0 / H * 1000))),
                    max(0, min(1000, int(x1 / W * 1000))),
                    max(0, min(1000, int(y1 / H * 1000))),
                ])
        doc = fitz.open(pdf_path)
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return words, bboxes, image

    def _extract_table_eav_words(
        self,
        pdf_path: Path,
        page_idx: int,
        table_bboxes_pp: list[tuple[float, float, float, float]],
        W: float,
        H: float,
    ) -> list[dict]:
        """camelot으로 표 cell 추출 → EAV word list.

        Header-only 표(1 row) → cell text 그대로.
        Header+value 표 → "header: value" 형식.
        """
        try:
            import camelot
        except ImportError:
            return []

        # pdfplumber bbox(top-down) → camelot table_areas(pdf coord, y bottom-up)
        # camelot 형식: "x1,y1,x2,y2" — (x1,y1)=left-top, (x2,y2)=right-bottom in pdf coord
        table_areas = []
        for bbox in table_bboxes_pp:
            x1, top, x2, bottom = bbox
            y1 = H - top      # 큰 y (top in pdf coord)
            y2 = H - bottom   # 작은 y (bottom)
            table_areas.append(f"{x1},{y1},{x2},{y2}")

        try:
            tables = camelot.read_pdf(
                str(pdf_path), flavor="lattice",
                pages=str(page_idx + 1),
                table_areas=table_areas,
            )
        except Exception:
            return []

        out: list[dict] = []

        def _emit(text: str, cell) -> None:
            top = H - cell.y2
            bottom = H - cell.y1
            words_in = text.split()
            n = len(words_in)
            if n == 0:
                return
            x_step = (cell.x2 - cell.x1) / n
            for wi, wt in enumerate(words_in):
                out.append({
                    "text": wt,
                    "x0": cell.x1 + wi * x_step,
                    "x1": cell.x1 + (wi + 1) * x_step,
                    "top": top,
                    "bottom": bottom,
                })

        for tbl in tables:
            df = tbl.df
            n_rows = len(df)
            n_cols = len(df.columns)
            if n_rows < 2:
                # Header-only — cell text 그대로
                for cidx in range(n_cols):
                    cell_text = str(df.iloc[0][cidx]).strip()
                    if cell_text:
                        _emit(cell_text, tbl.cells[0][cidx])
            else:
                header_row = df.iloc[0]
                for ridx in range(1, n_rows):
                    for cidx in range(n_cols):
                        cell_text = str(df.iloc[ridx][cidx]).strip()
                        header_text = str(header_row[cidx]).strip()
                        if not cell_text or not header_text:
                            continue
                        _emit(f"{header_text}: {cell_text}", tbl.cells[ridx][cidx])
        return out

    def _extract_body_and_tables(
        self, pdf_path: Path, page_idx: int,
    ) -> tuple[list[str], list[list[int]], list[float], Any, list[tuple], float, float] | None:
        """분리 파서용 — 표 영역 word 제거한 본문 word + 표 bbox 반환.

        Returns: (body_words, body_bboxes, body_tops, image, table_bboxes_pp, W, H)
          - body_words/bboxes: 표 영역 제외 본문 word (모델 input)
          - body_tops: 각 본문 word의 top 좌표 (sentence y 추적용)
          - table_bboxes_pp: pdfplumber 검출 표 bbox (camelot input)
        """
        import pdfplumber
        import fitz
        from PIL import Image
        from parser_ensemble import dedup_overlapping_words, merge_singleton_words

        with pdfplumber.open(pdf_path) as pdf:
            if page_idx >= len(pdf.pages):
                return None
            page = pdf.pages[page_idx]
            W, H = page.width, page.height
            if W <= 0 or H <= 0:
                return None
            raw_words = page.extract_words(
                use_text_flow=True, keep_blank_chars=False,
                x_tolerance=3, y_tolerance=3,
            )
            raw_words = dedup_overlapping_words(raw_words)
            raw_words = merge_singleton_words(raw_words)

            try:
                table_bboxes_pp = [tbl.bbox for tbl in page.find_tables()]
            except Exception:
                table_bboxes_pp = []

            def _in_any_table(w: dict) -> bool:
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                return any(
                    bx[0] <= cx <= bx[2] and bx[1] <= cy <= bx[3]
                    for bx in table_bboxes_pp
                )

            body_raw = [w for w in raw_words if not _in_any_table(w)]
            body_words: list[str] = []
            body_bboxes: list[list[int]] = []
            body_tops: list[float] = []
            for w in body_raw:
                body_words.append(w["text"])
                x0, y0, x1, y1 = w["x0"], w["top"], w["x1"], w["bottom"]
                body_bboxes.append([
                    max(0, min(1000, int(x0 / W * 1000))),
                    max(0, min(1000, int(y0 / H * 1000))),
                    max(0, min(1000, int(x1 / W * 1000))),
                    max(0, min(1000, int(y1 / H * 1000))),
                ])
                body_tops.append(w["top"])

        doc = fitz.open(pdf_path)
        page_f = doc[page_idx]
        pix = page_f.get_pixmap(dpi=150)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        doc.close()
        return body_words, body_bboxes, body_tops, image, table_bboxes_pp, W, H

    def _forward_words_to_sentences(
        self, words: list[str], bboxes: list[list[int]], tops: list[float], image,
        max_lxlm: int = 512, max_char: int = 512, char_stride: int = 400,
    ) -> list[tuple[str, float]]:
        """word 리스트 → hybrid forward → (sentence, y_top) 리스트.

        본문/표 EAV word 모두 이 메서드로 hybrid를 거침 (다듬기).
        y_top: 각 sentence 첫 word의 top 좌표 (merge 정렬용).
        """
        if not words:
            return []
        char_text, char_to_word = self._build_char_text(words)
        if not char_text:
            return []

        chunk_size = max_char - 2
        all_b_positions: set[int] = set()
        start = 0
        while start < len(char_text):
            end = min(start + chunk_size, len(char_text))
            chunk_c2w_abs = char_to_word[start:end]
            valid_w = [w for w in chunk_c2w_abs if w >= 0]
            if not valid_w:
                start += char_stride
                continue
            min_w, max_w = min(valid_w), max(valid_w)
            chunk_words = words[min_w : max_w + 1]
            chunk_bboxes = bboxes[min_w : max_w + 1]
            chunk_c2w_local = [(w - min_w) if w >= 0 else -1 for w in chunk_c2w_abs]
            try:
                b_rel = self._forward_chunk(
                    char_text[start:end], chunk_c2w_local, chunk_words,
                    chunk_bboxes, image, max_lxlm, max_char,
                )
            except Exception as e:
                print(f"  chunk forward FAIL [{start}:{end}]: {e}", file=sys.stderr)
                start += char_stride
                continue
            for b in b_rel:
                all_b_positions.add(start + b)
            if end >= len(char_text):
                break
            start += char_stride

        sorted_b = sorted(all_b_positions)
        out: list[tuple[str, float]] = []
        for i, b_pos in enumerate(sorted_b):
            end_pos = sorted_b[i + 1] if i + 1 < len(sorted_b) else len(char_text)
            sent = char_text[b_pos:end_pos].strip()
            if not sent:
                continue
            wi = char_to_word[b_pos] if b_pos < len(char_to_word) else -1
            y_top = tops[wi] if 0 <= wi < len(tops) else 0.0
            out.append((sent, y_top))
        return out

    def extract_page_sentences_split(
        self, pdf_path: Path, page_idx: int,
        max_lxlm: int = 512, max_char: int = 512,
        char_stride: int = 400,
    ) -> list[str]:
        """분리 파서 — 본문 word와 표 EAV word를 각각 hybrid에 통과 후 좌표 merge.

        룰 없음. camelot은 표 영역 word를 cell 단위 EAV word로 재구성(좌표 파싱)만 하고,
        sentence boundary는 본문/표 둘 다 hybrid 모델이 잡음.
        input을 본문/표로 분리 → 본문 흡수 없음. 모델이 EAV 학습되면(재학습) 표 품질 향상.
        """
        data = self._extract_body_and_tables(pdf_path, page_idx)
        if data is None:
            return []
        body_words, body_bboxes, body_tops, image, table_bboxes_pp, W, H = data

        # 1. 본문 word → hybrid
        body_sents = self._forward_words_to_sentences(
            body_words, body_bboxes, body_tops, image, max_lxlm, max_char, char_stride,
        )

        # 2. 표 EAV word(camelot 재구성) → hybrid
        eav_dicts = self._extract_table_eav_words(
            pdf_path, page_idx, table_bboxes_pp, W, H,
        )
        table_words = [w["text"] for w in eav_dicts]
        table_bboxes = [[
            max(0, min(1000, int(w["x0"] / W * 1000))),
            max(0, min(1000, int(w["top"] / H * 1000))),
            max(0, min(1000, int(w["x1"] / W * 1000))),
            max(0, min(1000, int(w["bottom"] / H * 1000))),
        ] for w in eav_dicts]
        table_tops = [w["top"] for w in eav_dicts]
        table_sents = self._forward_words_to_sentences(
            table_words, table_bboxes, table_tops, image, max_lxlm, max_char, char_stride,
        )

        # 3. y좌표로 merge
        merged = body_sents + table_sents
        merged.sort(key=lambda x: x[1])
        return [s for s, _ in merged]

    def _build_char_text(self, words: list[str]) -> tuple[str, list[int]]:
        """words → char_text + char_to_word (학습 데이터와 동일 규칙)."""
        char_text_parts: list[str] = []
        char_to_word: list[int] = []
        for wi, word in enumerate(words):
            if not word:
                continue
            if char_text_parts:
                char_text_parts.append(" ")
                char_to_word.append(wi - 1 if wi > 0 else 0)
            for c in word:
                char_text_parts.append(c)
                char_to_word.append(wi)
        return "".join(char_text_parts), char_to_word

    def _forward_chunk(
        self, chunk_text: str, chunk_c2w: list[int],
        chunk_words: list[str], chunk_bboxes: list[list[int]], image,
        max_lxlm: int, max_char: int,
    ) -> list[tuple[int, int]]:
        """한 chunk 처리. Returns (B 위치 char index, next char index) 페어 list — 매 B마다 sentence span 만들기 위함."""
        # LayoutXLM
        lxlm_encoded = self.processor(
            image, chunk_words, boxes=chunk_bboxes,
            return_tensors="pt", truncation=True,
            padding="max_length", max_length=max_lxlm,
        )
        word_ids = lxlm_encoded.word_ids()
        layoutxlm_inputs = {k: v.to(self.device) for k, v in lxlm_encoded.items() if hasattr(v, "squeeze")}

        # KoCharELECTRA
        char_enc = self.tokenizer(
            chunk_text, return_offsets_mapping=True, add_special_tokens=False,
            truncation=True, max_length=max_char - 2,
        )
        char_tokens = char_enc["input_ids"]
        offsets = char_enc["offset_mapping"]
        token_to_word = [chunk_c2w[s] if s < len(chunk_c2w) else -1 for s, _ in offsets]

        cls_id = self.tokenizer.cls_token_id
        sep_id = self.tokenizer.sep_token_id
        pad_id = self.tokenizer.pad_token_id
        input_ids = [cls_id] + char_tokens + [sep_id]
        c2w = [-1] + token_to_word + [-1]
        attn = [1] * len(input_ids)
        pad_len = max_char - len(input_ids)
        input_ids += [pad_id] * pad_len
        attn += [0] * pad_len
        c2w += [-1] * pad_len
        n_real = max_char - pad_len

        char_input_ids = torch.tensor([input_ids], dtype=torch.long).to(self.device)
        char_attention_mask = torch.tensor([attn], dtype=torch.long).to(self.device)
        char_to_word_t = torch.tensor([c2w], dtype=torch.long).to(self.device)

        with torch.no_grad():
            outputs = self.model(
                layoutxlm_inputs=layoutxlm_inputs,
                word_ids_list=[word_ids],
                char_input_ids=char_input_ids,
                char_attention_mask=char_attention_mask,
                char_to_word=char_to_word_t,
                labels=None,
            )
        if self.model.crf is not None and "predictions" in outputs:
            # CRF Viterbi decode — list of int, length = mask sum (n_real)
            preds = outputs["predictions"][0]
        else:
            preds = outputs["logits"].argmax(-1)[0].cpu().tolist()

        # B 위치 char index 찾기 — chunk_text 기준
        b_positions: list[int] = []  # B-SENT 시작 char index
        for tok_i, (s, e) in enumerate(offsets):
            real_idx = tok_i + 1
            if real_idx >= n_real - 1:
                break
            if real_idx >= len(preds):
                break
            if preds[real_idx] == 1:  # B-SENT
                b_positions.append(s)
        return b_positions

    def extract_page_sentences(
        self, pdf_path: Path, page_idx: int,
        max_lxlm: int = 512, max_char: int = 512,
        char_stride: int = 400,
    ) -> list[str]:
        """단일 page에서 sentence_list 추출 — sliding window로 긴 page 처리."""
        page_data = self._extract_page(pdf_path, page_idx)
        if page_data is None:
            return []
        words, bboxes, image = page_data
        if not words:
            return []

        # 전체 char_text + char_to_word 만들기 (truncation 없이)
        char_text, char_to_word = self._build_char_text(words)
        if not char_text:
            return []

        chunk_size = max_char - 2  # CLS + SEP 제외
        all_b_positions: set[int] = set()  # 전체 char 기준 B-SENT 위치

        # Sliding window
        start = 0
        while start < len(char_text):
            end = min(start + chunk_size, len(char_text))
            chunk_text = char_text[start:end]
            chunk_c2w_abs = char_to_word[start:end]  # 절대 word index

            # 이 chunk에서 사용하는 word range
            valid_w = [w for w in chunk_c2w_abs if w >= 0]
            if not valid_w:
                start += char_stride
                continue
            min_w, max_w = min(valid_w), max(valid_w)
            chunk_words = words[min_w : max_w + 1]
            chunk_bboxes = bboxes[min_w : max_w + 1]
            chunk_c2w_local = [(w - min_w) if w >= 0 else -1 for w in chunk_c2w_abs]

            try:
                b_rel = self._forward_chunk(
                    chunk_text, chunk_c2w_local, chunk_words, chunk_bboxes, image,
                    max_lxlm, max_char,
                )
            except Exception as e:
                print(f"  chunk forward FAIL [{start}:{end}]: {e}", file=sys.stderr)
                start += char_stride
                continue

            # 절대 char 위치로 변환
            for b in b_rel:
                all_b_positions.add(start + b)

            if end >= len(char_text):
                break
            start += char_stride

        # B 위치 sort → sentence span 만들기
        sorted_b = sorted(all_b_positions)
        sentences: list[str] = []
        if sorted_b:
            # 첫 B 이전은 sentence 아님 (또는 O 영역)
            for i, b_pos in enumerate(sorted_b):
                end_pos = sorted_b[i + 1] if i + 1 < len(sorted_b) else len(char_text)
                sent = char_text[b_pos:end_pos].strip()
                if sent:
                    sentences.append(sent)
        return sentences

    def extract_sentences(self, pdf_path: Path, split_parser: bool = True) -> list[str]:
        """전체 PDF → sentence_list (page별 처리 후 합침).

        split_parser=True (default): 분리 파서 — 본문은 hybrid 모델, 표는 camelot EAV.
            본문 segmentation에 표 word 영향 0.
        split_parser=False: 기존 단일 경로 (_extract_page use_camelot 분기).
        """
        import fitz
        doc = fitz.open(pdf_path)
        n_pages = len(doc)
        doc.close()
        all_sents: list[str] = []
        for page_idx in range(n_pages):
            if split_parser:
                all_sents.extend(self.extract_page_sentences_split(pdf_path, page_idx))
            else:
                all_sents.extend(self.extract_page_sentences(pdf_path, page_idx))
        return all_sents


if __name__ == "__main__":
    import argparse
    import io

    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", required=True, type=Path)
    ap.add_argument("--file", required=True, type=Path)
    args = ap.parse_args()

    inf = HybridInferer(args.checkpoint)
    sents = inf.extract_sentences(args.file)
    print(f"=== {args.file.name} ===")
    print(f"Sentences: {len(sents)}\n")
    for i, s in enumerate(sents):
        print(f"  [{i:02d}] {s}")
