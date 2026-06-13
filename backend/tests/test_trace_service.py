from __future__ import annotations

from app.db.models.trace import QaTraceSpan
from app.trace.service import TraceService
from tests.helpers import make_test_client


def test_trace_service_creates_trace_and_ordered_spans() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        service = TraceService(db)
        trace = service.create_trace(user_id=None, question="北京人口政策是什么？")
        first = service.add_span(
            trace_id=trace.id,
            span_type="router",
            input_json={"question": "北京人口政策是什么？"},
            output_json={"route_type": "POLICY_QA"},
            latency_ms=10,
            status="success",
        )
        second = service.add_span(
            trace_id=trace.id,
            span_type="answer_generation",
            input_json={"step": "answer"},
            output_json={"answer": "ok"},
            latency_ms=20,
            status="success",
        )
        service.finish_trace(
            trace_id=trace.id,
            route_type="POLICY_QA",
            final_answer="ok",
            status="success",
            latency_ms=35,
        )
        db.commit()

        spans = db.query(QaTraceSpan).filter(QaTraceSpan.trace_id == trace.id).order_by(
            QaTraceSpan.span_order
        ).all()

    assert trace.status == "success"
    assert trace.final_answer == "ok"
    assert [span.id for span in spans] == [first.id, second.id]
    assert [span.span_order for span in spans] == [1, 2]
