from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import fitz
import pdfplumber

from app.ingestion.parsers.html_parser import normalize_text


@dataclass(frozen=True)
class ParsedPdfElement:
    element_type: str
    content: str
    order_index: int
    page_no: int
    bbox: dict[str, float] | None
    heading_level: int | None = None
    parent_index: int | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ParsedPdfDocument:
    title: str
    raw_text: str
    clean_text: str
    markdown_text: str
    elements: list[ParsedPdfElement]
    page_count: int
    agent_refine_enabled: bool
    table_extraction_errors: list[str]


@dataclass(frozen=True)
class CandidateElement:
    element_type: str
    content: str
    page_no: int
    bbox: tuple[float, float, float, float] | None
    font_size: float | None
    metadata: dict


def parse_pdf_text_document(
    pdf_path: str | Path,
    *,
    fallback_title: str,
    table_extraction_enabled: bool = True,
    agent_refine_enabled: bool = False,
) -> ParsedPdfDocument:
    pdf_path = Path(pdf_path)
    if table_extraction_enabled:
        table_candidates, table_extraction_errors = extract_table_candidates(pdf_path)
    else:
        table_candidates, table_extraction_errors = {}, []

    document = fitz.open(pdf_path)
    try:
        raw_text_parts: list[str] = []
        text_candidates: list[CandidateElement] = []
        font_sizes: list[float] = []

        for page_index, page in enumerate(document):
            page_no = page_index + 1
            raw_text_parts.append(normalize_text(page.get_text("text")))
            page_tables = table_candidates.get(page_no, [])
            for block in page.get_text("dict").get("blocks", []):
                if block.get("type") != 0:
                    continue
                bbox = tuple(float(value) for value in block.get("bbox", (0, 0, 0, 0)))
                if overlaps_any_table(bbox, page_tables):
                    continue

                lines, block_font_sizes = extract_block_lines(block)
                content = normalize_text("\n".join(lines))
                if not content or is_page_noise(content):
                    continue

                font_size = max(block_font_sizes) if block_font_sizes else None
                if font_size is not None:
                    font_sizes.append(font_size)
                text_candidates.append(
                    CandidateElement(
                        element_type="paragraph",
                        content=content,
                        page_no=page_no,
                        bbox=bbox,
                        font_size=font_size,
                        metadata={"extractor": "pymupdf", "font_size": font_size},
                    )
                )

        merged_text_candidates = merge_text_candidates(text_candidates, font_sizes=font_sizes)
        all_candidates = merged_text_candidates + [
            table for tables in table_candidates.values() for table in tables
        ]
        all_candidates.sort(key=sort_key)
        elements = classify_candidates(all_candidates, font_sizes=font_sizes, fallback_title=fallback_title)
    finally:
        page_count = document.page_count
        document.close()

    raw_text = "\n\n".join(part for part in raw_text_parts if part)
    clean_text = "\n".join(element.content for element in elements)
    title = next((element.content for element in elements if element.element_type == "title"), fallback_title)
    markdown_text = build_markdown(elements)

    return ParsedPdfDocument(
        title=title,
        raw_text=raw_text,
        clean_text=clean_text,
        markdown_text=markdown_text,
        elements=elements,
        page_count=page_count,
        agent_refine_enabled=agent_refine_enabled,
        table_extraction_errors=table_extraction_errors,
    )


def extract_block_lines(block: dict) -> tuple[list[str], list[float]]:
    lines: list[str] = []
    font_sizes: list[float] = []
    for line in block.get("lines", []):
        spans = line.get("spans", [])
        line_text = normalize_text("".join(span.get("text", "") for span in spans))
        if line_text:
            lines.append(line_text)
        for span in spans:
            size = span.get("size")
            if isinstance(size, int | float):
                font_sizes.append(float(size))
    return lines, font_sizes


def extract_table_candidates(pdf_path: Path) -> tuple[dict[int, list[CandidateElement]], list[str]]:
    tables_by_page: dict[int, list[CandidateElement]] = {}
    errors: list[str] = []
    try:
        with pdfplumber.open(pdf_path) as document:
            for page_index, page in enumerate(document.pages):
                page_no = page_index + 1
                candidates: list[CandidateElement] = []
                try:
                    tables = page.find_tables()
                except Exception as exc:  # noqa: BLE001 - table extraction is optional
                    errors.append(f"page {page_no}: {type(exc).__name__}: {exc}")
                    tables_by_page[page_no] = []
                    continue
                for table_index, table in enumerate(tables):
                    rows = table.extract()
                    text = table_to_text(rows)
                    if not text:
                        continue
                    bbox = tuple(float(value) for value in table.bbox)
                    candidates.append(
                        CandidateElement(
                            element_type="table",
                            content=text,
                            page_no=page_no,
                            bbox=bbox,
                            font_size=None,
                            metadata={"extractor": "pdfplumber", "table_index": table_index},
                        )
                    )
                tables_by_page[page_no] = candidates
    except Exception as exc:  # noqa: BLE001 - PyMuPDF text extraction can still continue
        errors.append(f"document: {type(exc).__name__}: {exc}")
    return tables_by_page, errors


def table_to_text(rows: list[list[str | None]]) -> str:
    text_rows: list[str] = []
    for row in rows:
        cells = [normalize_text(cell or "") for cell in row]
        cells = [cell for cell in cells if cell]
        if cells:
            text_rows.append(" | ".join(cells))
    return "\n".join(text_rows)


def classify_candidates(
    candidates: list[CandidateElement],
    *,
    font_sizes: list[float],
    fallback_title: str,
) -> list[ParsedPdfElement]:
    if not candidates:
        return []

    body_font_size = median(font_sizes) if font_sizes else 12.0
    title_inserted = False
    heading_stack: dict[int, int] = {}
    elements: list[ParsedPdfElement] = []

    for candidate in candidates:
        heading_level = infer_heading_level(
            candidate.content,
            font_size=candidate.font_size,
            body_font_size=body_font_size,
            is_first_text=not title_inserted and candidate.element_type == "paragraph",
        )
        element_type = candidate.element_type
        parent_index = None
        if heading_level is not None:
            element_type = "title"
            parent_index = nearest_parent_heading(heading_stack, heading_level)

        order_index = len(elements)
        parsed = ParsedPdfElement(
            element_type=element_type,
            content=candidate.content,
            order_index=order_index,
            page_no=candidate.page_no,
            bbox=bbox_to_json(candidate.bbox),
            heading_level=heading_level,
            parent_index=parent_index,
            metadata=candidate.metadata,
        )
        elements.append(parsed)

        if heading_level is not None:
            heading_stack[heading_level] = order_index
            for stale_level in list(heading_stack):
                if stale_level > heading_level:
                    heading_stack.pop(stale_level, None)
            title_inserted = True

    if not any(element.element_type == "title" for element in elements):
        title = normalize_text(fallback_title)
        elements.insert(
            0,
            ParsedPdfElement(
                element_type="title",
                content=title,
                order_index=0,
                page_no=1,
                bbox=None,
                heading_level=1,
                metadata={"generated": True},
            ),
        )
        elements = reindex_elements(elements)

    return elements


def merge_text_candidates(
    candidates: list[CandidateElement],
    *,
    font_sizes: list[float],
) -> list[CandidateElement]:
    if not candidates:
        return []

    body_font_size = median(font_sizes) if font_sizes else 12.0
    sorted_candidates = sorted(candidates, key=sort_key)
    merged: list[CandidateElement] = []
    current: CandidateElement | None = None
    title_seen = False

    for candidate in sorted_candidates:
        heading_level = infer_heading_level(
            candidate.content,
            font_size=candidate.font_size,
            body_font_size=body_font_size,
            is_first_text=not title_seen,
        )
        if heading_level is not None:
            if current is not None:
                merged.append(current)
                current = None
            merged.append(candidate)
            title_seen = True
            continue

        if current is not None and should_merge_text_blocks(current, candidate):
            current = combine_text_blocks(current, candidate)
        else:
            if current is not None:
                merged.append(current)
            current = candidate

    if current is not None:
        merged.append(current)
    return merged


def should_merge_text_blocks(previous: CandidateElement, current: CandidateElement) -> bool:
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
    return 0 <= vertical_gap <= max(previous_height, current_height) * 1.8


def combine_text_blocks(previous: CandidateElement, current: CandidateElement) -> CandidateElement:
    return CandidateElement(
        element_type="paragraph",
        content=join_wrapped_text(previous.content, current.content),
        page_no=previous.page_no,
        bbox=union_bbox(previous.bbox, current.bbox),
        font_size=previous.font_size or current.font_size,
        metadata={
            "extractor": "pymupdf",
            "merged_blocks": previous.metadata.get("merged_blocks", 1)
            + current.metadata.get("merged_blocks", 1),
        },
    )


def join_wrapped_text(previous: str, current: str) -> str:
    if previous and current and previous[-1].isascii() and current[0].isascii():
        return f"{previous} {current}"
    return f"{previous}{current}"


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


def infer_heading_level(
    text: str,
    *,
    font_size: float | None,
    body_font_size: float,
    is_first_text: bool,
) -> int | None:
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
    if font_size is not None and font_size >= body_font_size + 2 and len(stripped) <= 80:
        return 2
    return None


def nearest_parent_heading(heading_stack: dict[int, int], level: int) -> int | None:
    parent_levels = [heading_level for heading_level in heading_stack if heading_level < level]
    if not parent_levels:
        return None
    return heading_stack[max(parent_levels)]


def reindex_elements(elements: list[ParsedPdfElement]) -> list[ParsedPdfElement]:
    return [
        ParsedPdfElement(
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


def overlaps_any_table(
    bbox: tuple[float, float, float, float],
    table_candidates: list[CandidateElement],
) -> bool:
    return any(overlap_ratio(bbox, table.bbox) > 0.2 for table in table_candidates if table.bbox)


def overlap_ratio(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float] | None,
) -> float:
    if b is None:
        return 0.0
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    x_overlap = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    y_overlap = max(0.0, min(ay1, by1) - max(ay0, by0))
    intersection = x_overlap * y_overlap
    area = max((ax1 - ax0) * (ay1 - ay0), 1.0)
    return intersection / area


def sort_key(candidate: CandidateElement) -> tuple[int, float, float, int]:
    x0, y0, _, _ = candidate.bbox or (0.0, 0.0, 0.0, 0.0)
    type_rank = 1 if candidate.element_type == "table" else 0
    return candidate.page_no, y0, x0, type_rank


def build_markdown(elements: list[ParsedPdfElement]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.element_type == "title":
            level = element.heading_level or 1
            lines.append(f"{'#' * min(level, 6)} {element.content}")
        else:
            lines.append(element.content)
    return "\n\n".join(lines)


def is_page_noise(text: str) -> bool:
    return bool(re.fullmatch(r"[-—_ ]*\d+[-—_ ]*", text.strip()))
