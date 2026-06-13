from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.rag.retriever import RetrievedChunk


@dataclass(frozen=True)
class EvidenceBlock:
    source_id: str
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    title: str
    issuing_agency: str | None
    publish_date: str | None
    heading_path: str | None
    source_url: str | None
    chunk_text: str
    score: float
    match_sources: list[str]


@dataclass(frozen=True)
class PolicyContext:
    evidence_blocks: list[EvidenceBlock]
    context_text: str


class ContextBuilder:
    def build(self, chunks: list[RetrievedChunk], *, max_blocks: int = 8) -> PolicyContext:
        evidence_blocks = [
            chunk_to_evidence_block(index=index, chunk=chunk)
            for index, chunk in enumerate(chunks[:max_blocks], start=1)
        ]
        return PolicyContext(
            evidence_blocks=evidence_blocks,
            context_text="\n\n".join(block_to_text(block) for block in evidence_blocks),
        )


def chunk_to_evidence_block(*, index: int, chunk: RetrievedChunk) -> EvidenceBlock:
    return EvidenceBlock(
        source_id=f"资料{index}",
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        version_id=chunk.version_id,
        title=chunk.document_title,
        issuing_agency=chunk.issuing_agency,
        publish_date=chunk.publish_date.isoformat() if chunk.publish_date else None,
        heading_path=chunk.heading_path,
        source_url=chunk.source_url,
        chunk_text=chunk.chunk_text,
        score=round(chunk.final_score, 4),
        match_sources=list(chunk.match_sources),
    )


def block_to_text(block: EvidenceBlock) -> str:
    lines = [
        f"[{block.source_id}]",
        f"标题：{block.title}",
        f"发文机关：{block.issuing_agency or ''}",
        f"发布日期：{block.publish_date or ''}",
        f"章节：{block.heading_path or ''}",
        f"来源：{block.source_url or ''}",
        f"正文：{block.chunk_text}",
    ]
    return "\n".join(lines)
