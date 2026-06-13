from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

import fitz

from app.ingestion.parsers.html_parser import normalize_text
from app.ingestion.parsers.ocr_engine import OcrEngine, OcrTextBlock


@dataclass(frozen=True)
class ParsedOcrElement:
    element_type: str
    content: str
    order_index: int
    page_no: int
    bbox: dict[str, float] | None
    heading_level: int | None = None
    parent_index: int | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ParsedOcrDocument:
    title: str
    raw_text: str
    clean_text: str
    markdown_text: str
    elements: list[ParsedOcrElement]
    page_count: int
    ocr_engine: str
    render_dpi: int
    agent_refine_enabled: bool


@dataclass(frozen=True)
class OcrCandidate:
    content: str
    page_no: int
    bbox: tuple[float, float, float, float] | None
    confidence: float | None
    metadata: dict


def parse_pdf_ocr_document(
    pdf_path: str | Path,
    *,
    fallback_title: str,
    ocr_engine: OcrEngine,
    lang: str = "ch",
    render_dpi: int = 180,
    agent_refine_enabled: bool = False,
) -> ParsedOcrDocument:
    pdf_path = Path(pdf_path)
    engine_name = getattr(ocr_engine, "name", "custom")
    document = fitz.open(pdf_path)
    try:
        candidates: list[OcrCandidate] = []
        with tempfile.TemporaryDirectory(prefix="public-data-agent-ocr-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            scale = render_dpi / 72
            matrix = fitz.Matrix(scale, scale)
            for page_index, page in enumerate(document):
                page_no = page_index + 1
                image_path = tmp_path / f"page-{page_no}.png"
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                pixmap.save(image_path)
                for block in ocr_engine.recognize(image_path, lang=lang):
                    candidate = block_to_candidate(
                        block,
                        page_no=page_no,
                        scale=scale,
                        engine_name=engine_name,
                        render_dpi=render_dpi,
                    )
                    if candidate is not None:
                        candidates.append(candidate)
    finally:
        page_count = document.page_count
        document.close()

    candidates = merge_ocr_candidates(candidates)
    candidates.sort(key=sort_key)
    elements = classify_candidates(candidates, fallback_title=fallback_title)
    raw_text = "\n".join(candidate.content for candidate in candidates)
    clean_text = "\n".join(element.content for element in elements)
    title = next((element.content for element in elements if element.element_type == "title"), fallback_title)
    markdown_text = build_markdown(elements)

    return ParsedOcrDocument(
        title=title,
        raw_text=raw_text,
        clean_text=clean_text,
        markdown_text=markdown_text,
        elements=elements,
        page_count=page_count,
        ocr_engine=engine_name,
        render_dpi=render_dpi,
        agent_refine_enabled=agent_refine_enabled,
    )


def block_to_candidate(
    block: OcrTextBlock,
    *,
    page_no: int,
    scale: float,
    engine_name: str,
    render_dpi: int,
) -> OcrCandidate | None:
    content = normalize_text(block.text)
    if not content:
        return None
    bbox = image_bbox_to_pdf_bbox(block.bbox, scale=scale)
    return OcrCandidate(
        content=content,
        page_no=page_no,
        bbox=bbox,
        confidence=block.confidence,
        metadata={
            "extractor": "ocr",
            "ocr_engine": engine_name,
            "confidence": round(block.confidence, 2) if block.confidence is not None else None,
            "render_dpi": render_dpi,
            "source_metadata": block.metadata or {},
        },
    )


def merge_ocr_candidates(candidates: list[OcrCandidate]) -> list[OcrCandidate]:
    if not candidates:
        return []

    sorted_candidates = sorted(candidates, key=sort_key)
    merged: list[OcrCandidate] = []
    current: OcrCandidate | None = None
    title_seen = False

    for candidate in sorted_candidates:
        if infer_heading_level(candidate.content, is_first_text=not title_seen) is not None:
            if current is not None:
                merged.append(current)
                current = None
            merged.append(candidate)
            title_seen = True
            continue

        if current is not None and should_merge_ocr_lines(current, candidate):
            current = combine_ocr_candidates(current, candidate)
        else:
            if current is not None:
                merged.append(current)
            current = candidate

    if current is not None:
        merged.append(current)
    return merged


def should_merge_ocr_lines(previous: OcrCandidate, current: OcrCandidate) -> bool:
    if previous.page_no != current.page_no:
        return False
    if previous.bbox is None or current.bbox is None:
        return False
    if starts_new_policy_paragraph(current.content):
        return False

    _, previous_y0, _, previous_y1 = previous.bbox
    _, current_y0, _, current_y1 = current.bbox
    previous_height = max(previous_y1 - previous_y0, 1.0)
    current_height = max(current_y1 - current_y0, 1.0)
    vertical_gap = current_y0 - previous_y1
    return 0 <= vertical_gap <= max(previous_height, current_height) * 1.6


def combine_ocr_candidates(previous: OcrCandidate, current: OcrCandidate) -> OcrCandidate:
    confidence_values = [
        value for value in (previous.confidence, current.confidence) if value is not None
    ]
    confidence = sum(confidence_values) / len(confidence_values) if confidence_values else None
    return OcrCandidate(
        content=join_ocr_text(previous.content, current.content),
        page_no=previous.page_no,
        bbox=union_bbox(previous.bbox, current.bbox),
        confidence=confidence,
        metadata={
            **previous.metadata,
            "confidence": round(confidence, 2) if confidence is not None else None,
            "merged_lines": previous.metadata.get("merged_lines", 1)
            + current.metadata.get("merged_lines", 1),
        },
    )


def classify_candidates(
    candidates: list[OcrCandidate],
    *,
    fallback_title: str,
) -> list[ParsedOcrElement]:
    if not candidates:
        return []

    heading_stack: dict[int, int] = {}
    elements: list[ParsedOcrElement] = []

    for candidate in candidates:
        heading_level = infer_heading_level(candidate.content, is_first_text=not elements)
        element_type = "title" if heading_level is not None else "paragraph"
        parent_index = nearest_parent_heading(heading_stack, heading_level) if heading_level else None
        order_index = len(elements)
        elements.append(
            ParsedOcrElement(
                element_type=element_type,
                content=candidate.content,
                order_index=order_index,
                page_no=candidate.page_no,
                bbox=bbox_to_json(candidate.bbox),
                heading_level=heading_level,
                parent_index=parent_index,
                metadata=candidate.metadata,
            )
        )
        if heading_level is not None:
            heading_stack[heading_level] = order_index
            for stale_level in list(heading_stack):
                if stale_level > heading_level:
                    heading_stack.pop(stale_level, None)

    if not any(element.element_type == "title" for element in elements):
        elements.insert(
            0,
            ParsedOcrElement(
                element_type="title",
                content=normalize_text(fallback_title),
                order_index=0,
                page_no=1,
                bbox=None,
                heading_level=1,
                metadata={"generated": True},
            ),
        )
        elements = reindex_elements(elements)

    return elements


def infer_heading_level(text: str, *, is_first_text: bool) -> int | None:
    stripped = normalize_text(text)
    if not stripped:
        return None
    if is_first_text and len(stripped) <= 80:
        return 1
    if re.match(r"^第[一二三四五六七八九十百千万0-9]+章", stripped):
        return 2
    if re.match(r"^第[一二三四五六七八九十百千万0-9]+节", stripped):
        return 3
    if re.match(r"^[一二三四五六七八九十]+、", stripped):
        return 3
    return None


def starts_new_policy_paragraph(text: str) -> bool:
    stripped = normalize_text(text)
    patterns = [
        r"^第[一二三四五六七八九十百千万0-9]+条",
        r"^第[一二三四五六七八九十百千万0-9]+章",
        r"^第[一二三四五六七八九十百千万0-9]+节",
        r"^[（(][一二三四五六七八九十0-9]+[）)]",
        r"^[一二三四五六七八九十]+、",
        r"^\d+[.、]",
    ]
    return any(re.match(pattern, stripped) for pattern in patterns)


def nearest_parent_heading(heading_stack: dict[int, int], level: int) -> int | None:
    parent_levels = [heading_level for heading_level in heading_stack if heading_level < level]
    if not parent_levels:
        return None
    return heading_stack[max(parent_levels)]


def reindex_elements(elements: list[ParsedOcrElement]) -> list[ParsedOcrElement]:
    return [
        ParsedOcrElement(
            element_type=element.element_type,
            content=element.content,
            order_index=index,
            page_no=element.page_no,
            bbox=element.bbox,
            heading_level=element.heading_level,
            parent_index=element.parent_index + 1 if element.parent_index is not None else None,
            metadata=element.metadata,
        )
        for index, element in enumerate(elements)
    ]


def image_bbox_to_pdf_bbox(
    bbox: tuple[float, float, float, float] | None,
    *,
    scale: float,
) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return x0 / scale, y0 / scale, x1 / scale, y1 / scale


def bbox_to_json(bbox: tuple[float, float, float, float] | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return {
        "x0": round(x0, 2),
        "y0": round(y0, 2),
        "x1": round(x1, 2),
        "y1": round(y1, 2),
    }


def union_bbox(
    a: tuple[float, float, float, float] | None,
    b: tuple[float, float, float, float] | None,
) -> tuple[float, float, float, float] | None:
    if a is None:
        return b
    if b is None:
        return a
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1)


def sort_key(candidate: OcrCandidate) -> tuple[int, float, float]:
    x0, y0, _, _ = candidate.bbox or (0.0, 0.0, 0.0, 0.0)
    return candidate.page_no, y0, x0


def join_ocr_text(previous: str, current: str) -> str:
    if previous and current and previous[-1].isascii() and current[0].isascii():
        return f"{previous} {current}"
    return f"{previous}{current}"


def build_markdown(elements: list[ParsedOcrElement]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.element_type == "title":
            level = element.heading_level or 1
            lines.append(f"{'#' * min(level, 6)} {element.content}")
        else:
            lines.append(element.content)
    return "\n\n".join(lines)
