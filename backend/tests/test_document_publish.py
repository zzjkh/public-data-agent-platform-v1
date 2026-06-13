from __future__ import annotations

from datetime import UTC, datetime

from app.db.models.document import PolicyDocument, PolicyDocumentVersion, SourceFile
from app.db.models.rag_chunk import ChunkEmbedding, RagChunk
from tests.helpers import auth_headers, make_test_client


def seed_publishable_version(session_factory, *, include_embedding: bool = True):
    with session_factory() as db:
        source_file = SourceFile(
            file_name="policy.html",
            file_type="html",
            storage_uri="local://policy.html",
            file_hash="a" * 64,
            file_version="v1",
            parse_status="parsed",
        )
        db.add(source_file)
        db.flush()
        document = PolicyDocument(source_file_id=source_file.id, title="旧标题")
        db.add(document)
        db.flush()
        old_version = PolicyDocumentVersion(
            document_id=document.id,
            version_no="v1",
            clean_text="old",
            content_hash="b" * 64,
            parser_type="html",
            publish_status="published",
            published_at=datetime.now(UTC),
        )
        version = PolicyDocumentVersion(
            document_id=document.id,
            version_no="v2",
            clean_text="new",
            content_hash="c" * 64,
            parser_type="html",
        )
        db.add_all([old_version, version])
        db.flush()
        chunk = RagChunk(
            document_id=document.id,
            version_id=version.id,
            chunk_text="公共数据政策内容",
            embedding_text="公共数据政策内容",
            retrieval_text="公共数据政策内容",
            element_ids_json=[],
            order_index=0,
            chunk_strategy="section",
            char_count=8,
            token_count=8,
            content_hash="d" * 64,
            search_text="公共数据政策内容",
        )
        db.add(chunk)
        db.flush()
        if include_embedding:
            db.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding_model="BAAI/bge-small-zh-v1.5",
                    embedding_dim=512,
                    embedding_version="v1",
                    embedding=[0.0] * 512,
                )
            )
        db.commit()
        return version.id, old_version.id, document.id


def test_publish_document_version_archives_old_version_and_updates_metadata(tmp_path) -> None:
    client, session_factory = make_test_client(tmp_path)
    version_id, old_version_id, document_id = seed_publishable_version(session_factory)

    with client:
        response = client.post(
            f"/api/document-versions/{version_id}/publish",
            headers=auth_headers(client),
            json={
                "title": "公共数据资源政策",
                "issuing_agency": "国家数据局",
                "policy_level": "national",
                "validity_status": "active",
                "keywords": ["公共数据", "开发利用"],
            },
        )

    assert response.status_code == 200, response.json()
    assert response.json()["publish_status"] == "published"
    assert response.json()["archived_version_ids"] == [str(old_version_id)]
    with session_factory() as db:
        assert db.get(PolicyDocumentVersion, old_version_id).publish_status == "archived"
        assert db.get(PolicyDocumentVersion, version_id).publish_status == "published"
        document = db.get(PolicyDocument, document_id)
        assert document.title == "公共数据资源政策"
        assert document.keywords_json == {"keywords": ["公共数据", "开发利用"]}


def test_publish_document_version_requires_current_embeddings(tmp_path) -> None:
    client, session_factory = make_test_client(tmp_path)
    version_id, _, _ = seed_publishable_version(session_factory, include_embedding=False)

    with client:
        response = client.post(
            f"/api/document-versions/{version_id}/publish",
            headers=auth_headers(client),
            json={"validity_status": "active"},
        )

    assert response.status_code == 409
    assert "all chunks have embeddings" in response.json()["error"]["message"]


def test_publish_document_version_requires_admin(tmp_path) -> None:
    client, session_factory = make_test_client(tmp_path)
    version_id, _, _ = seed_publishable_version(session_factory)

    with client:
        response = client.post(
            f"/api/document-versions/{version_id}/publish",
            headers=auth_headers(client, username="demo", password="demo123"),
            json={},
        )

    assert response.status_code == 403
