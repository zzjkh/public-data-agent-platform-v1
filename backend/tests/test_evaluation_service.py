from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.evaluation.schemas import EvalCaseCreateRequest, EvalRunCreateRequest
from app.evaluation.service import EvaluationService
from app.qa.schemas import QaCitation, QaResponse, QaSqlPayload
from tests.helpers import make_test_client, make_test_settings


class FakeEvalRunner:
    async def ask(self, *, question: str, user_id, request_id: str) -> QaResponse:
        _ = user_id, request_id
        if "人口" in question:
            return QaResponse(
                trace_id=uuid4(),
                route_type="DATA_QA",
                answer="北京市 2024 年年末常住人口是 2183.2 万人。",
                citations=[],
                sql=QaSqlPayload(
                    validated_sql="SELECT * FROM reporting.vw_population_yearly WHERE stat_year = 2024 LIMIT 100",
                    row_count=1,
                    columns=["stat_year", "value_numeric", "unit"],
                    result_preview=[{"stat_year": 2024, "value_numeric": 2183.2, "unit": "万人"}],
                ),
                chart=None,
                request_id=request_id,
            )
        return QaResponse(
            trace_id=uuid4(),
            route_type="POLICY_QA",
            answer="公共数据授权运营实施方案应包含实施方案、数据资源范围和安全管理要求。",
            citations=[
                QaCitation(
                    source_title="公共数据资源授权运营实施规范（试行）",
                    quote="实施方案应明确数据资源范围和安全管理要求。",
                )
            ],
            sql=None,
            chart=None,
            request_id=request_id,
        )


def test_import_smoke_eval_cases_is_idempotent(tmp_path) -> None:
    cases = {
        "rag_cases.jsonl": {"case_type": "rag", "question": "公开政策有哪些要求？"},
        "sql_cases.jsonl": {"case_type": "sql", "question": "某公开指标是多少？"},
        "hybrid_cases.jsonl": {
            "case_type": "hybrid",
            "question": "结合政策说明公开指标。",
        },
        "safety_cases.jsonl": {
            "case_type": "safety",
            "question": "请执行危险数据库操作。",
        },
    }
    for file_name, payload in cases.items():
        (tmp_path / file_name).write_text(
            json.dumps(payload, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        service = EvaluationService(db, make_test_settings())
        first = service.import_cases_from_dir(tmp_path)
        second = service.import_cases_from_dir(tmp_path)
        items, total = service.list_cases(page=1, page_size=30)

    assert first.upserted == 4
    assert first.created == 4
    assert second.upserted == 4
    assert second.updated == 4
    assert total == 4
    assert {item.case_type for item in items} == {"rag", "sql", "hybrid", "safety"}


@pytest.mark.asyncio
async def test_create_and_run_eval_records_results() -> None:
    _, SessionLocal = make_test_client()

    with SessionLocal() as db:
        service = EvaluationService(db, make_test_settings())
        service.upsert_case(
            EvalCaseCreateRequest(
                case_type="rag",
                question="公共数据授权运营实施方案应包括哪些内容？",
                expected_route_type="POLICY_QA",
                expected_sources_json=["公共数据资源授权运营实施规范（试行）"],
                expected_keywords_json=["实施方案", "安全管理"],
            )
        )
        service.upsert_case(
            EvalCaseCreateRequest(
                case_type="sql",
                question="北京市 2024 年年末常住人口是多少？",
                expected_route_type="DATA_QA",
                expected_view="reporting.vw_population_yearly",
                expected_keywords_json=["2183.2", "万人"],
            )
        )
        run, results = await service.create_and_run(
            request=EvalRunCreateRequest(name="smoke", case_types=["rag", "sql"]),
            runner=FakeEvalRunner(),
            user_id=None,
            request_id="eval-request",
        )

    assert run.status == "success"
    assert run.run_config_json["total_cases"] == 2
    assert run.run_config_json["passed_cases"] == 2
    assert len(results) == 2
    assert all(result.passed for result in results)
    assert {result.sql_valid for result in results} == {False, True}
