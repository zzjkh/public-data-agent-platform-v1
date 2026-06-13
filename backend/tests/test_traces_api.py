from __future__ import annotations

from uuid import UUID

from app.db.models.user import User
from app.trace.service import TraceService
from tests.helpers import auth_headers, make_test_client


def seed_trace(
    db,
    *,
    user_id: UUID,
    question: str,
    route_type: str = "POLICY_QA",
    final_answer: str = "回答完成",
    status: str = "success",
) -> UUID:
    service = TraceService(db)
    trace = service.create_trace(user_id=user_id, question=question)
    service.add_span(
        trace_id=trace.id,
        span_type="router",
        input_json={"question": question},
        output_json={"route_type": route_type},
        latency_ms=11,
        status="success",
    )
    service.add_span(
        trace_id=trace.id,
        span_type="answer_generation",
        input_json={"context": "evidence blocks"},
        output_json={"answer": final_answer},
        latency_ms=23,
        status="success",
        model_name="deepseek-v4-pro",
        prompt_name="rag_answer",
        prompt_version="v1",
    )
    service.finish_trace(
        trace_id=trace.id,
        route_type=route_type,
        final_answer=final_answer,
        status=status,
        latency_ms=40,
    )
    trace_id = trace.id
    db.commit()
    return trace_id


def get_user_id(db, username: str) -> UUID:
    return db.query(User).filter(User.username == username).one().id


def test_trace_list_requires_auth() -> None:
    client, _ = make_test_client()

    with client:
        response = client.get("/api/traces")

    assert response.status_code == 401


def test_trace_list_scopes_normal_user_and_supports_admin_filters() -> None:
    client, SessionLocal = make_test_client()

    with SessionLocal() as db:
        admin_id = get_user_id(db, "admin")
        demo_id = get_user_id(db, "demo")
        seed_trace(db, user_id=admin_id, question="管理员问题", route_type="POLICY_QA")
        seed_trace(
            db,
            user_id=demo_id,
            question="普通用户问题",
            route_type="DATA_QA",
            status="failed",
        )

    with client:
        demo_headers = auth_headers(client, username="demo", password="demo123")
        demo_response = client.get("/api/traces", headers=demo_headers)

        admin_headers = auth_headers(client)
        admin_response = client.get(
            "/api/traces",
            headers={**admin_headers, "X-Request-ID": "trace-list-request"},
            params={"status": "success"},
        )

    assert demo_response.status_code == 200
    demo_payload = demo_response.json()
    assert demo_payload["total"] == 1
    assert demo_payload["items"][0]["user_question"] == "普通用户问题"

    assert admin_response.status_code == 200
    admin_payload = admin_response.json()
    assert admin_payload["request_id"] == "trace-list-request"
    assert admin_payload["total"] == 1
    assert admin_payload["items"][0]["user_question"] == "管理员问题"


def test_trace_detail_returns_ordered_spans() -> None:
    client, SessionLocal = make_test_client()

    with SessionLocal() as db:
        demo_id = get_user_id(db, "demo")
        trace_id = seed_trace(db, user_id=demo_id, question="Trace 怎么排查？")

    with client:
        headers = auth_headers(client, username="demo", password="demo123")
        response = client.get(
            f"/api/traces/{trace_id}",
            headers={**headers, "X-Request-ID": "trace-detail-request"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["request_id"] == "trace-detail-request"
    assert payload["user_question"] == "Trace 怎么排查？"
    assert [span["span_order"] for span in payload["spans"]] == [1, 2]
    assert payload["spans"][0]["input_json"] == {"question": "Trace 怎么排查？"}
    assert payload["spans"][1]["prompt_version"] == "v1"
    assert payload["spans"][1]["output_json"] == {"answer": "回答完成"}


def test_trace_detail_hides_other_users_trace() -> None:
    client, SessionLocal = make_test_client()

    with SessionLocal() as db:
        admin_id = get_user_id(db, "admin")
        trace_id = seed_trace(db, user_id=admin_id, question="管理员 Trace")

    with client:
        headers = auth_headers(client, username="demo", password="demo123")
        response = client.get(f"/api/traces/{trace_id}", headers=headers)

    assert response.status_code == 404
