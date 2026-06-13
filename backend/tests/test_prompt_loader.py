from __future__ import annotations

from pathlib import Path

import pytest

from app.llm.contracts import get_contract_model
from app.llm.prompts import PromptLoader, PromptTemplateError, load_prompt_file


def test_prompt_loader_parses_front_matter_and_renders_router_prompt() -> None:
    loader = PromptLoader()
    template = loader.load("router")
    rendered = template.render(
        question="北京市近五年人口变化如何？",
        available_capabilities="- DATA_QA",
        current_date="2026-06-04",
    )

    assert template.prompt_name == "router"
    assert template.prompt_version == "v1.1"
    assert template.purpose == "question_router"
    assert template.output_model == "QuestionRoute"
    assert "北京市近五年人口变化如何？" in rendered
    assert "{question}" not in rendered
    assert '"route_type"' in rendered
    assert "JSON object" in rendered
    assert "policy_topics" in rendered


def test_prompt_loader_rejects_missing_variable() -> None:
    template = PromptLoader().load("sql_generation")

    with pytest.raises(PromptTemplateError, match="Missing prompt variables"):
        template.render(question="北京 GDP 是多少？")


def test_prompt_loader_rejects_invalid_front_matter(tmp_path: Path) -> None:
    prompt_path = tmp_path / "bad.md"
    prompt_path.write_text(
        "---\nprompt_name: bad\nprompt_version: v1.0\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(PromptTemplateError, match="missing front matter"):
        load_prompt_file(prompt_path)


def test_all_prompt_output_models_are_registered() -> None:
    loader = PromptLoader()
    for prompt_path in loader.root_dir.glob("*.md"):
        template = loader.load(prompt_path.stem)
        assert get_contract_model(template.output_model)
