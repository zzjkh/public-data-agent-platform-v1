from __future__ import annotations

import argparse
import math

from app.core.config import get_settings
from app.ingestion.handlers import build_embedding_provider


def check_embedding_provider(*, text: str) -> None:
    settings = get_settings()
    provider = build_embedding_provider(
        settings,
        embedding_model=settings.embedding_model,
        embedding_dim=settings.embedding_dim,
    )
    vector = provider.embed_query(text)
    if len(vector) != settings.embedding_dim:
        raise RuntimeError(
            f"embedding dimension mismatch: expected={settings.embedding_dim} actual={len(vector)}"
        )
    vector_norm = math.sqrt(sum(value * value for value in vector))
    print(
        "embedding_provider_check: "
        f"provider={settings.embedding_provider} "
        f"model={provider.model_name} "
        f"dim={len(vector)} "
        f"norm={vector_norm:.6f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the configured embedding provider.")
    parser.add_argument("--text", default="公共数据资源开发利用")
    args = parser.parse_args()
    check_embedding_provider(text=args.text)


if __name__ == "__main__":
    main()
