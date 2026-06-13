from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class OcrTextBlock:
    text: str
    bbox: tuple[float, float, float, float] | None
    confidence: float | None = None
    metadata: dict | None = None


class OcrEngine(Protocol):
    name: str

    def recognize(self, image_path: str | Path, *, lang: str) -> list[OcrTextBlock]:
        raise NotImplementedError


class OcrEngineError(RuntimeError):
    pass


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None

    def recognize(self, image_path: str | Path, *, lang: str) -> list[OcrTextBlock]:
        del lang  # RapidOCR V1 uses its bundled Chinese-English recognition model.
        if self._engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OcrEngineError(
                    "rapidocr is not installed; install backend dependencies before running OCR"
                ) from exc
            self._engine = RapidOCR()

        try:
            result = self._engine(str(image_path))
        except Exception as exc:  # pragma: no cover - depends on local inference runtime.
            raise OcrEngineError(f"RapidOCR failed: {exc}") from exc
        return rapidocr_result_to_blocks(result)


class TesseractOcrEngine:
    name = "tesseract"

    def recognize(self, image_path: str | Path, *, lang: str) -> list[OcrTextBlock]:
        try:
            import pytesseract
            from pytesseract import Output
        except ImportError as exc:
            raise OcrEngineError(
                "pytesseract is not installed; install backend dependencies before running OCR"
            ) from exc

        try:
            data = pytesseract.image_to_data(
                str(image_path),
                lang=normalize_tesseract_lang(lang),
                output_type=Output.DICT,
            )
        except Exception as exc:  # pragma: no cover - depends on local system OCR binary.
            raise OcrEngineError(f"Tesseract OCR failed: {exc}") from exc

        return tesseract_data_to_blocks(data)


def normalize_tesseract_lang(lang: str) -> str:
    normalized = lang.lower().replace("_", "-")
    if normalized in {"ch", "zh", "zh-cn", "cn", "chi-sim"}:
        return "chi_sim+eng"
    if normalized in {"zh-tw", "zh-hk", "chi-tra"}:
        return "chi_tra+eng"
    if normalized in {"en", "eng"}:
        return "eng"
    return lang


def rapidocr_result_to_blocks(result: object) -> list[OcrTextBlock]:
    if result is None:
        return []

    raw_texts = getattr(result, "txts", None)
    raw_boxes = getattr(result, "boxes", None)
    raw_scores = getattr(result, "scores", None)
    texts = list(raw_texts) if raw_texts is not None else []
    boxes = list(raw_boxes) if raw_boxes is not None else []
    scores = list(raw_scores) if raw_scores is not None else []
    if not texts and isinstance(result, tuple) and result:
        legacy_rows = result[0] or []
        texts = [row[1] for row in legacy_rows]
        boxes = [row[0] for row in legacy_rows]
        scores = [row[2] for row in legacy_rows]

    blocks: list[OcrTextBlock] = []
    for index, raw_text in enumerate(texts):
        text = str(raw_text).strip()
        if not text:
            continue
        box = boxes[index] if index < len(boxes) else None
        score = scores[index] if index < len(scores) else None
        blocks.append(
            OcrTextBlock(
                text=text,
                bbox=normalize_polygon_bbox(box),
                confidence=parse_confidence(score),
                metadata={"line_index": index},
            )
        )
    return blocks


def normalize_polygon_bbox(box: object) -> tuple[float, float, float, float] | None:
    if hasattr(box, "tolist"):
        box = box.tolist()
    if not isinstance(box, (list, tuple)) or not box:
        return None
    try:
        points = [(float(point[0]), float(point[1])) for point in box]
    except (TypeError, ValueError, IndexError):
        return None
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def tesseract_data_to_blocks(data: dict) -> list[OcrTextBlock]:
    groups: dict[tuple[int, int, int], list[dict]] = defaultdict(list)
    text_items = data.get("text", [])
    for index, raw_text in enumerate(text_items):
        text = str(raw_text).strip()
        if not text:
            continue
        key = (
            int(data.get("block_num", [0])[index]),
            int(data.get("par_num", [0])[index]),
            int(data.get("line_num", [0])[index]),
        )
        groups[key].append(
            {
                "text": text,
                "left": float(data.get("left", [0])[index]),
                "top": float(data.get("top", [0])[index]),
                "width": float(data.get("width", [0])[index]),
                "height": float(data.get("height", [0])[index]),
                "confidence": parse_confidence(data.get("conf", [-1])[index]),
            }
        )

    blocks: list[OcrTextBlock] = []
    for key in sorted(groups):
        words = groups[key]
        text = " ".join(word["text"] for word in words)
        x0 = min(word["left"] for word in words)
        y0 = min(word["top"] for word in words)
        x1 = max(word["left"] + word["width"] for word in words)
        y1 = max(word["top"] + word["height"] for word in words)
        confidences = [word["confidence"] for word in words if word["confidence"] is not None]
        confidence = sum(confidences) / len(confidences) if confidences else None
        blocks.append(
            OcrTextBlock(
                text=text,
                bbox=(x0, y0, x1, y1),
                confidence=confidence,
                metadata={"block_num": key[0], "par_num": key[1], "line_num": key[2]},
            )
        )
    return blocks


def parse_confidence(value: object) -> float | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return None
    return confidence
