from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.db.models.semantic_metadata import SemanticMetadataEmbedding, SemanticMetadataItem
from app.db.repositories.chunk_embedding import vector_to_pg_literal


class SemanticMetadataRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_item(self, item_id: UUID) -> SemanticMetadataItem | None:
        return self.db.get(SemanticMetadataItem, item_id)

    def get_by_identity(
        self,
        *,
        metadata_type: str,
        name: str,
        related_table: str,
        related_field: str,
    ) -> SemanticMetadataItem | None:
        return self.db.scalar(
            select(SemanticMetadataItem).where(
                SemanticMetadataItem.metadata_type == metadata_type,
                SemanticMetadataItem.name == name,
                SemanticMetadataItem.related_table == related_table,
                SemanticMetadataItem.related_field == related_field,
            )
        )

    def upsert_item(self, values: dict) -> tuple[SemanticMetadataItem, bool, bool]:
        related_table = values.get("related_table") or ""
        related_field = values.get("related_field") or ""
        values = {**values, "related_table": related_table, "related_field": related_field}
        item = self.get_by_identity(
            metadata_type=values["metadata_type"],
            name=values["name"],
            related_table=related_table,
            related_field=related_field,
        )
        created = item is None
        changed = True
        if item is None:
            item = SemanticMetadataItem(**values)
            self.db.add(item)
        else:
            changed = semantic_item_changed(item, values)
            if changed:
                for key, value in values.items():
                    setattr(item, key, value)
                item.updated_at = datetime.now(UTC)
        self.db.flush()
        return item, created, changed

    def list_items(
        self,
        *,
        page: int,
        page_size: int,
        metadata_type: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[SemanticMetadataItem], int]:
        statement = select(SemanticMetadataItem)
        statement = self._apply_item_filters(statement, metadata_type=metadata_type, keyword=keyword)

        count_statement = select(func.count(SemanticMetadataItem.id))
        count_statement = self._apply_item_filters(
            count_statement,
            metadata_type=metadata_type,
            keyword=keyword,
        )
        total = self.db.scalar(count_statement) or 0
        items = list(
            self.db.scalars(
                statement.order_by(
                    SemanticMetadataItem.metadata_type.asc(),
                    SemanticMetadataItem.related_table.asc(),
                    SemanticMetadataItem.name.asc(),
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        return items, total

    def list_items_for_embedding(self, *, metadata_types: list[str] | None = None) -> list[SemanticMetadataItem]:
        statement = select(SemanticMetadataItem)
        if metadata_types:
            statement = statement.where(SemanticMetadataItem.metadata_type.in_(metadata_types))
        return list(
            self.db.scalars(
                statement.order_by(
                    SemanticMetadataItem.metadata_type.asc(),
                    SemanticMetadataItem.related_table.asc(),
                    SemanticMetadataItem.name.asc(),
                )
            )
        )

    def get_existing_embedding_item_ids(
        self,
        *,
        item_ids: list[UUID],
        embedding_model: str,
        embedding_version: str,
    ) -> set[UUID]:
        if not item_ids:
            return set()
        rows = self.db.scalars(
            select(SemanticMetadataEmbedding.metadata_item_id).where(
                SemanticMetadataEmbedding.metadata_item_id.in_(item_ids),
                SemanticMetadataEmbedding.embedding_model == embedding_model,
                SemanticMetadataEmbedding.embedding_version == embedding_version,
            )
        )
        return set(rows)

    def delete_embeddings(
        self,
        *,
        item_ids: list[UUID],
        embedding_model: str,
        embedding_version: str,
    ) -> int:
        if not item_ids:
            return 0
        result = self.db.execute(
            delete(SemanticMetadataEmbedding).where(
                SemanticMetadataEmbedding.metadata_item_id.in_(item_ids),
                SemanticMetadataEmbedding.embedding_model == embedding_model,
                SemanticMetadataEmbedding.embedding_version == embedding_version,
            )
        )
        self.db.flush()
        return int(result.rowcount or 0)

    def create_embeddings(self, *, rows: list[dict]) -> list[SemanticMetadataEmbedding]:
        created: list[SemanticMetadataEmbedding] = []
        if not rows:
            return created

        if self.db.bind is not None and self.db.bind.dialect.name == "postgresql":
            for row in rows:
                embedding_id = uuid4()
                self.db.execute(
                    text(
                        """
                        INSERT INTO semantic_metadata_embeddings (
                            id,
                            metadata_item_id,
                            embedding_model,
                            embedding_dim,
                            embedding_version,
                            embedding
                        )
                        VALUES (
                            :id,
                            :metadata_item_id,
                            :embedding_model,
                            :embedding_dim,
                            :embedding_version,
                            CAST(:embedding AS vector)
                        )
                        """
                    ),
                    {
                        "id": embedding_id,
                        "metadata_item_id": row["metadata_item_id"],
                        "embedding_model": row["embedding_model"],
                        "embedding_dim": row["embedding_dim"],
                        "embedding_version": row["embedding_version"],
                        "embedding": vector_to_pg_literal(row["embedding"]),
                    },
                )
                created_embedding = self.db.get(SemanticMetadataEmbedding, embedding_id)
                if created_embedding is not None:
                    created.append(created_embedding)
        else:
            for row in rows:
                embedding = SemanticMetadataEmbedding(**row)
                self.db.add(embedding)
                created.append(embedding)
            self.db.flush()
        return created

    def _apply_item_filters(
        self,
        statement: Select,
        *,
        metadata_type: str | None,
        keyword: str | None,
    ) -> Select:
        if metadata_type:
            statement = statement.where(SemanticMetadataItem.metadata_type == metadata_type)
        if keyword:
            like_keyword = f"%{keyword}%"
            statement = statement.where(
                or_(
                    SemanticMetadataItem.name.ilike(like_keyword),
                    SemanticMetadataItem.description.ilike(like_keyword),
                    SemanticMetadataItem.search_text.ilike(like_keyword),
                    SemanticMetadataItem.related_table.ilike(like_keyword),
                    SemanticMetadataItem.related_field.ilike(like_keyword),
                )
            )
        return statement


def semantic_item_changed(item: SemanticMetadataItem, values: dict) -> bool:
    for key, value in values.items():
        if getattr(item, key) != value:
            return True
    return False
