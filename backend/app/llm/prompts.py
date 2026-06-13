from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PromptTemplateError(ValueError):
    pass


@dataclass(frozen=True)
class PromptTemplate:
    prompt_name: str
    prompt_version: str
    purpose: str
    output_model: str
    input_variables: tuple[str, ...]
    body: str
    path: Path

    def render(self, **variables: Any) -> str:
        missing = [name for name in self.input_variables if name not in variables]
        if missing:
            raise PromptTemplateError(
                f"Missing prompt variables for {self.prompt_name}: {', '.join(missing)}"
            )
        rendered = self.body
        for name in self.input_variables:
            rendered = rendered.replace("{" + name + "}", stringify_prompt_value(variables[name]))
        return rendered


class PromptLoader:
    def __init__(self, root_dir: Path | str | None = None) -> None:
        self.root_dir = Path(root_dir) if root_dir is not None else default_prompt_root()
        self._cache: dict[str, PromptTemplate] = {}

    def load(self, prompt_name: str) -> PromptTemplate:
        if prompt_name not in self._cache:
            path = self.root_dir / f"{prompt_name}.md"
            self._cache[prompt_name] = load_prompt_file(path)
        return self._cache[prompt_name]

    def render(self, prompt_name: str, **variables: Any) -> str:
        return self.load(prompt_name).render(**variables)

    def clear_cache(self) -> None:
        self._cache.clear()


def default_prompt_root() -> Path:
    return Path(__file__).resolve().parent / "prompts"


def load_prompt_file(path: Path) -> PromptTemplate:
    if not path.exists():
        raise PromptTemplateError(f"Prompt template not found: {path}")
    text = path.read_text(encoding="utf-8")
    front_matter, body = split_front_matter(text, path=path)
    required_fields = ("prompt_name", "prompt_version", "purpose", "output_model")
    missing = [field for field in required_fields if not front_matter.get(field)]
    if missing:
        raise PromptTemplateError(f"Prompt {path.name} missing front matter: {', '.join(missing)}")
    input_variables = parse_list_field(front_matter.get("input_variables", ""))
    prompt_name = front_matter["prompt_name"]
    if path.stem != prompt_name:
        raise PromptTemplateError(
            f"Prompt filename {path.name} does not match prompt_name={prompt_name}"
        )
    return PromptTemplate(
        prompt_name=prompt_name,
        prompt_version=front_matter["prompt_version"],
        purpose=front_matter["purpose"],
        output_model=front_matter["output_model"],
        input_variables=tuple(input_variables),
        body=body.strip(),
        path=path,
    )


def split_front_matter(text: str, *, path: Path) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptTemplateError(f"Prompt {path.name} must start with front matter")
    end_index = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise PromptTemplateError(f"Prompt {path.name} front matter is not closed")

    front_matter: dict[str, str] = {}
    for line in lines[1:end_index]:
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            raise PromptTemplateError(f"Invalid front matter line in {path.name}: {line}")
        key, value = line.split(":", 1)
        front_matter[key.strip()] = value.strip()
    return front_matter, "\n".join(lines[end_index + 1 :])


def parse_list_field(value: str) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def stringify_prompt_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    return str(value)
