from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.document import DocumentElement
from app.db.models.rag_chunk import RagChunk
from app.db.repositories.document import DocumentRepository
from app.db.repositories.rag_chunk import RagChunkRepository
from app.ingestion.parsers.html_parser import normalize_text


CHUNK_STRATEGIES = {"section", "paragraph", "sliding_window"}
DEFAULT_CHUNK_STRATEGY = "section"
DEFAULT_MIN_CHARS = 300
DEFAULT_MAX_CHARS = 800
DEFAULT_OVERLAP_RATIO = 0.12


class ChunkBuildError(ValueError):
    pass


@dataclass(frozen=True)
class ChunkUnit:
    content: str
    element_ids: list[str]
    heading_path: str | None
    element_type: str


@dataclass(frozen=True)
class ChunkSpec:
    chunk_text: str
    heading_path: str | None
    element_ids: list[str]
    chunk_strategy: str
    char_count: int
    token_count: int
    embedding_text: str
    retrieval_text: str
    search_text: str


@dataclass(frozen=True)
class ChunkBuildResult:
    version_id: UUID
    document_id: UUID
    chunks: list[RagChunk]
    reused_count: int


class ChunkingService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.documents = DocumentRepository(db)
        self.chunks = RagChunkRepository(db)

    def build_chunks(
        self,
        *,
        version_id: UUID,
        chunk_strategy: str = DEFAULT_CHUNK_STRATEGY,
        min_chars: int = DEFAULT_MIN_CHARS,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
    ) -> ChunkBuildResult:
        validate_chunk_options(
            chunk_strategy=chunk_strategy,
            min_chars=min_chars,
            max_chars=max_chars,
            overlap_ratio=overlap_ratio,
        )
        version = self.documents.get_version(version_id)
        if version is None:
            raise ChunkBuildError("Policy document version not found")
        document = self.documents.get_document(version.document_id)
        if document is None:
            raise ChunkBuildError("Policy document not found")

        elements = self.documents.list_elements(version_id=version_id)
        if not elements:
            raise ChunkBuildError("Cannot build chunks from an empty document version")

        specs = build_chunk_specs(
            elements,
            document_title=document.title,
            issuing_agency=document.issuing_agency,
            chunk_strategy=chunk_strategy,
            min_chars=min_chars,
            max_chars=max_chars,
            overlap_ratio=overlap_ratio,
        )
        if not specs:
            raise ChunkBuildError("Chunking produced no chunks")

        rows = [
            chunk_spec_to_row(
                spec,
                document_id=document.id,
                version_id=version.id,
                order_index=index,
            )
            for index, spec in enumerate(specs)
        ]
        chunks, reused_count = self.chunks.create_or_reuse_chunks(chunk_rows=rows)
        self.db.flush()
        return ChunkBuildResult(
            version_id=version.id,
            document_id=document.id,
            chunks=chunks,
            reused_count=reused_count,
        )


def build_chunk_specs(
    elements: list[DocumentElement],
    *,
    document_title: str,
    issuing_agency: str | None,
    chunk_strategy: str = DEFAULT_CHUNK_STRATEGY,
    min_chars: int = DEFAULT_MIN_CHARS,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[ChunkSpec]:
    validate_chunk_options(
        chunk_strategy=chunk_strategy,
        min_chars=min_chars,
        max_chars=max_chars,
        overlap_ratio=overlap_ratio,
    )
    units = build_chunk_units(elements)
    if not units:
        return []

    if chunk_strategy == "section":
        specs = split_by_section(
            units,
            document_title=document_title,
            issuing_agency=issuing_agency,
            min_chars=min_chars,
            max_chars=max_chars,
            overlap_ratio=overlap_ratio,
        )
    elif chunk_strategy == "paragraph":
        specs = split_by_paragraph(
            units,
            document_title=document_title,
            issuing_agency=issuing_agency,
            min_chars=min_chars,
            max_chars=max_chars,
            overlap_ratio=overlap_ratio,
        )
    else:
        specs = split_by_sliding_window(
            units,
            document_title=document_title,
            issuing_agency=issuing_agency,
            max_chars=max_chars,
            overlap_ratio=overlap_ratio,
        )
    return specs


def build_chunk_units(elements: list[DocumentElement]) -> list[ChunkUnit]:
    heading_stack: dict[int, str] = {}
    units: list[ChunkUnit] = []

    for element in elements:
        content = normalize_text(element.content)
        if not content:
            continue

        if element.element_type == "title":
            level = element.heading_level or 1
            heading_stack[level] = content
            for stale_level in list(heading_stack):
                if stale_level > level:
                    heading_stack.pop(stale_level, None)
            heading_path = format_heading_path(heading_stack)
        else:
            heading_path = format_heading_path(heading_stack)

        units.append(
            ChunkUnit(
                content=content,
                element_ids=[str(element.id)],
                heading_path=heading_path,
                element_type=element.element_type,
            )
        )
    return units


def split_by_section(
    units: list[ChunkUnit],
    *,
    document_title: str,
    issuing_agency: str | None,
    min_chars: int,
    max_chars: int,
    overlap_ratio: float,
) -> list[ChunkSpec]:
    groups: list[list[ChunkUnit]] = []
    current: list[ChunkUnit] = []
    for unit in units:
        if current and unit.element_type == "title":
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)

    specs: list[ChunkSpec] = []
    for group in groups:
        text = join_unit_text(group)
        if len(text) <= max_chars:
            specs.append(
                make_chunk_spec(
                    group,
                    chunk_text=text,
                    chunk_strategy="section",
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                )
            )
        else:
            specs.extend(
                split_by_paragraph(
                    group,
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                    min_chars=min_chars,
                    max_chars=max_chars,
                    overlap_ratio=overlap_ratio,
                )
            )
    return specs


def split_by_paragraph(
    units: list[ChunkUnit],
    *,
    document_title: str,
    issuing_agency: str | None,
    min_chars: int,
    max_chars: int,
    overlap_ratio: float,
) -> list[ChunkSpec]:
    specs: list[ChunkSpec] = []
    current: list[ChunkUnit] = []

    for unit in units:
        if len(unit.content) > max_chars:
            if current:
                specs.append(
                    make_chunk_spec(
                        current,
                        chunk_text=join_unit_text(current),
                        chunk_strategy="paragraph",
                        document_title=document_title,
                        issuing_agency=issuing_agency,
                    )
                )
                current = []
            specs.extend(
                split_by_sliding_window(
                    [unit],
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                    max_chars=max_chars,
                    overlap_ratio=overlap_ratio,
                )
            )
            continue

        candidate = [*current, unit]
        candidate_text = join_unit_text(candidate)
        if current and len(candidate_text) > max_chars:
            specs.append(
                make_chunk_spec(
                    current,
                    chunk_text=join_unit_text(current),
                    chunk_strategy="paragraph",
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                )
            )
            current = [unit]
        else:
            current = candidate

        if len(join_unit_text(current)) >= min_chars:
            specs.append(
                make_chunk_spec(
                    current,
                    chunk_text=join_unit_text(current),
                    chunk_strategy="paragraph",
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                )
            )
            current = []

    if current:
        specs.append(
            make_chunk_spec(
                current,
                chunk_text=join_unit_text(current),
                chunk_strategy="paragraph",
                document_title=document_title,
                issuing_agency=issuing_agency,
            )
        )
    return specs


def split_by_sliding_window(
    units: list[ChunkUnit],
    *,
    document_title: str,
    issuing_agency: str | None,
    max_chars: int,
    overlap_ratio: float,
) -> list[ChunkSpec]:
    text = join_unit_text(units)
    overlap = max(1, int(max_chars * overlap_ratio))
    step = max(1, max_chars - overlap)
    specs: list[ChunkSpec] = []

    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        window_text = text[start:end].strip()
        if window_text:
            specs.append(
                make_chunk_spec(
                    units,
                    chunk_text=window_text,
                    chunk_strategy="sliding_window",
                    document_title=document_title,
                    issuing_agency=issuing_agency,
                )
            )
        if end == len(text):
            break
        start += step
    return specs


def make_chunk_spec(
    units: list[ChunkUnit],
    *,
    chunk_text: str,
    chunk_strategy: str,
    document_title: str,
    issuing_agency: str | None,
) -> ChunkSpec:
    heading_path = choose_heading_path(units)
    element_ids = unique_element_ids(units)
    retrieval_text = build_retrieval_text(
        document_title=document_title,
        heading_path=heading_path,
        chunk_text=chunk_text,
    )
    embedding_text = build_embedding_text(
        document_title=document_title,
        issuing_agency=issuing_agency,
        heading_path=heading_path,
        chunk_text=chunk_text,
    )
    return ChunkSpec(
        chunk_text=chunk_text,
        heading_path=heading_path,
        element_ids=element_ids,
        chunk_strategy=chunk_strategy,
        char_count=len(chunk_text),
        token_count=estimate_token_count(chunk_text),
        embedding_text=embedding_text,
        retrieval_text=retrieval_text,
        search_text=retrieval_text,
    )


def chunk_spec_to_row(
    spec: ChunkSpec,
    *,
    document_id: UUID,
    version_id: UUID,
    order_index: int,
) -> dict:
    return {
        "document_id": document_id,
        "version_id": version_id,
        "chunk_text": spec.chunk_text,
        "embedding_text": spec.embedding_text,
        "retrieval_text": spec.retrieval_text,
        "heading_path": spec.heading_path,
        "element_ids_json": spec.element_ids,
        "order_index": order_index,
        "chunk_strategy": spec.chunk_strategy,
        "char_count": spec.char_count,
        "token_count": spec.token_count,
        "content_hash": build_content_hash(
            version_id=version_id,
            order_index=order_index,
            chunk_strategy=spec.chunk_strategy,
            heading_path=spec.heading_path,
            chunk_text=spec.chunk_text,
        ),
        "search_text": spec.search_text,
    }


def build_embedding_text(
    *,
    document_title: str,
    issuing_agency: str | None,
    heading_path: str | None,
    chunk_text: str,
) -> str:
    return "\n".join(
        [
            f"文件标题：{document_title}",
            f"发文机关：{issuing_agency or ''}",
            f"章节路径：{heading_path or ''}",
            f"正文：{chunk_text}",
        ]
    )


def build_retrieval_text(*, document_title: str, heading_path: str | None, chunk_text: str) -> str:
    parts = [document_title, heading_path or "", chunk_text]
    return normalize_text("\n".join(part for part in parts if part))


def build_content_hash(
    *,
    version_id: UUID,
    order_index: int,
    chunk_strategy: str,
    heading_path: str | None,
    chunk_text: str,
) -> str:
    payload = "\n".join([str(version_id), str(order_index), chunk_strategy, heading_path or "", chunk_text])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def join_unit_text(units: list[ChunkUnit]) -> str:
    return "\n\n".join(unit.content for unit in units if unit.content)


def unique_element_ids(units: list[ChunkUnit]) -> list[str]:
    seen: set[str] = set()
    element_ids: list[str] = []
    for unit in units:
        for element_id in unit.element_ids:
            if element_id not in seen:
                seen.add(element_id)
                element_ids.append(element_id)
    return element_ids


def choose_heading_path(units: list[ChunkUnit]) -> str | None:
    for unit in reversed(units):
        if unit.heading_path:
            return unit.heading_path
    return None


def format_heading_path(heading_stack: dict[int, str]) -> str | None:
    if not heading_stack:
        return None
    return " / ".join(heading_stack[level] for level in sorted(heading_stack))


def estimate_token_count(text: str) -> int:
    return max(1, len(text))


def validate_chunk_options(
    *,
    chunk_strategy: str,
    min_chars: int,
    max_chars: int,
    overlap_ratio: float,
) -> None:
    if chunk_strategy not in CHUNK_STRATEGIES:
        raise ChunkBuildError(f"Unsupported chunk_strategy: {chunk_strategy}")
    if min_chars <= 0:
        raise ChunkBuildError("min_chars must be positive")
    if max_chars <= 0:
        raise ChunkBuildError("max_chars must be positive")
    if min_chars > max_chars:
        raise ChunkBuildError("min_chars must be less than or equal to max_chars")
    if not 0.1 <= overlap_ratio <= 0.15:
        raise ChunkBuildError("overlap_ratio must be between 0.10 and 0.15")
