from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup, Tag


NOISE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "form",
    "aside",
    ".nav",
    ".navbar",
    ".footer",
    ".breadcrumb",
    ".share",
    ".toolbar",
]
CONTENT_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"]


@dataclass(frozen=True)
class ParsedElement:
    element_type: str
    content: str
    order_index: int
    heading_level: int | None = None
    parent_index: int | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class ParsedHtmlDocument:
    title: str
    raw_text: str
    clean_text: str
    markdown_text: str
    elements: list[ParsedElement]
    extraction_mode: str = "dom"


def parse_html_document(
    html: str,
    *,
    fallback_title: str,
) -> ParsedHtmlDocument:
    embedded_table = extract_embedded_statistical_table(html)
    if embedded_table is not None:
        return embedded_table

    soup = BeautifulSoup(html, "html.parser")
    for selector in NOISE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    raw_text = normalize_text(soup.get_text("\n", strip=True))
    title = extract_title(soup, fallback_title=fallback_title)
    elements = extract_elements(soup, title=title)
    clean_text = "\n".join(element.content for element in elements)
    markdown_text = build_markdown(elements)

    return ParsedHtmlDocument(
        title=title,
        raw_text=raw_text,
        clean_text=clean_text,
        markdown_text=markdown_text,
        elements=elements,
        extraction_mode="dom",
    )


def extract_embedded_statistical_table(html: str) -> ParsedHtmlDocument | None:
    soup = BeautifulSoup(html, "html.parser")
    decoder = json.JSONDecoder()
    for script in soup.find_all("script"):
        script_text = script.string or script.get_text("\n", strip=False)
        for match in re.finditer(r"\b(?:var|let|const)\s+data\s*=\s*", script_text):
            try:
                payload, _end = decoder.raw_decode(script_text[match.end() :])
            except json.JSONDecodeError:
                continue
            parsed = build_embedded_table_document(payload)
            if parsed is not None:
                return parsed
    return None


def build_embedded_table_document(payload: Any) -> ParsedHtmlDocument | None:
    if not isinstance(payload, dict):
        return None
    title = normalize_text(str(payload.get("templetname") or ""))
    raw_rows = payload.get("data")
    if not title or not isinstance(raw_rows, list) or not raw_rows:
        return None

    rows = [normalize_table_row(row) for row in raw_rows if isinstance(row, list)]
    if not rows:
        return None
    header_count = payload.get("fixedRowsTop", 1)
    if not isinstance(header_count, int):
        header_count = 1
    header_count = min(max(header_count, 1), len(rows))
    headers = merge_table_headers(rows[:header_count])

    elements = [
        ParsedElement(
            element_type="title",
            content=title,
            order_index=0,
            heading_level=1,
            metadata={"generated": True, "source": "script_json_table"},
        )
    ]
    for source_row_index, row in enumerate(rows[header_count:], start=header_count):
        content = format_table_data_row(row, headers)
        if not content:
            continue
        elements.append(
            ParsedElement(
                element_type="table",
                content=content,
                order_index=len(elements),
                parent_index=0,
                metadata={
                    "source": "script_json_table",
                    "table_name": title,
                    "source_row_index": source_row_index,
                },
            )
        )

    remark = normalize_text(str(payload.get("remark") or ""))
    if remark:
        elements.append(
            ParsedElement(
                element_type="paragraph",
                content=remark,
                order_index=len(elements),
                parent_index=0,
                metadata={"source": "script_json_table", "role": "remark"},
            )
        )

    if len(elements) == 1:
        return None
    clean_text = "\n".join(element.content for element in elements)
    return ParsedHtmlDocument(
        title=title,
        raw_text=clean_text,
        clean_text=clean_text,
        markdown_text=build_markdown(elements),
        elements=elements,
        extraction_mode="script_json_table",
    )


def normalize_table_row(row: list[Any]) -> list[str]:
    return [normalize_text("" if cell is None else str(cell)) for cell in row]


def merge_table_headers(header_rows: list[list[str]]) -> list[str]:
    width = max(len(row) for row in header_rows)
    expanded_rows: list[list[str]] = []
    for row_index, row in enumerate(header_rows):
        expanded: list[str] = []
        previous = ""
        for column_index in range(width):
            value = row[column_index] if column_index < len(row) else ""
            if value:
                previous = value
            elif row_index == 0 and previous:
                value = previous
            expanded.append(value)
        expanded_rows.append(expanded)

    headers: list[str] = []
    for column_index in range(width):
        levels: list[str] = []
        for row in expanded_rows:
            value = row[column_index]
            if value and value not in levels:
                levels.append(value)
        headers.append(" / ".join(levels) or f"第{column_index + 1}列")
    return headers


def format_table_data_row(row: list[str], headers: list[str]) -> str:
    fields: list[str] = []
    for column_index, value in enumerate(row):
        if not value:
            continue
        header = headers[column_index] if column_index < len(headers) else f"第{column_index + 1}列"
        fields.append(f"{header}={value}")
    return " | ".join(fields)


def extract_title(soup: BeautifulSoup, *, fallback_title: str) -> str:
    h1 = soup.find("h1")
    if isinstance(h1, Tag):
        text = normalize_text(h1.get_text(" ", strip=True))
        if text:
            return text

    html_title = soup.find("title")
    if isinstance(html_title, Tag):
        text = normalize_text(html_title.get_text(" ", strip=True))
        if text:
            return text

    return fallback_title


def extract_elements(soup: BeautifulSoup, *, title: str) -> list[ParsedElement]:
    body = soup.body or soup
    elements: list[ParsedElement] = []
    heading_stack: dict[int, int] = {}
    seen_title = False

    for node in body.find_all(CONTENT_TAGS):
        if not isinstance(node, Tag):
            continue
        text = element_text(node)
        if not text:
            continue

        if node.name and re.fullmatch(r"h[1-6]", node.name):
            level = int(node.name[1])
            parent_index = nearest_parent_heading(heading_stack, level)
            order_index = len(elements)
            elements.append(
                ParsedElement(
                    element_type="title",
                    content=text,
                    order_index=order_index,
                    heading_level=level,
                    parent_index=parent_index,
                    metadata={"tag": node.name},
                )
            )
            heading_stack[level] = order_index
            for stale_level in list(heading_stack):
                if stale_level > level:
                    heading_stack.pop(stale_level, None)
            if level == 1:
                seen_title = True
            continue

        parent_index = nearest_parent_heading(heading_stack, 7)
        element_type = "table" if node.name == "table" else "paragraph"
        elements.append(
            ParsedElement(
                element_type=element_type,
                content=text,
                order_index=len(elements),
                parent_index=parent_index,
                metadata={"tag": node.name},
            )
        )

    if not seen_title and title:
        elements.insert(
            0,
            ParsedElement(
                element_type="title",
                content=title,
                order_index=0,
                heading_level=1,
                metadata={"generated": True},
            ),
        )
        elements = [
            ParsedElement(
                element_type=element.element_type,
                content=element.content,
                order_index=index,
                heading_level=element.heading_level,
                parent_index=shift_parent_index(element.parent_index),
                metadata=element.metadata,
            )
            for index, element in enumerate(elements)
        ]

    return elements


def element_text(node: Tag) -> str:
    if node.name == "table":
        rows = []
        for row in node.find_all("tr"):
            cells = [normalize_text(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"])]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        return "\n".join(rows)

    return normalize_text(node.get_text(" ", strip=True))


def nearest_parent_heading(heading_stack: dict[int, int], level: int) -> int | None:
    parent_levels = [heading_level for heading_level in heading_stack if heading_level < level]
    if not parent_levels:
        return None
    return heading_stack[max(parent_levels)]


def shift_parent_index(parent_index: int | None) -> int | None:
    if parent_index is None:
        return None
    return parent_index + 1


def build_markdown(elements: list[ParsedElement]) -> str:
    lines: list[str] = []
    for element in elements:
        if element.element_type == "title":
            level = element.heading_level or 1
            lines.append(f"{'#' * min(level, 6)} {element.content}")
        elif element.element_type == "table":
            lines.append(element.content)
        else:
            lines.append(element.content)
    return "\n\n".join(lines)


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
