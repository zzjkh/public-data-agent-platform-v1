from __future__ import annotations

import threading
from typing import Protocol

from embedding_server.config import ServerSettings


class EmbeddingEngine(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def loaded(self) -> bool: ...

    def load(self) -> None: ...

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class TransformersEmbeddingEngine:
    def __init__(self, settings: ServerSettings) -> None:
        self.settings = settings
        self._tokenizer = None
        self._model = None
        self._torch = None
        self._lock = threading.Lock()
        self._dimension = settings.embedding_dim

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    def load(self) -> None:
        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - depends on deployment environment.
            raise RuntimeError("torch and transformers are required to run the model") from exc

        tokenizer = AutoTokenizer.from_pretrained(
            self.settings.model_path,
            local_files_only=True,
            padding_side="left",
        )
        dtype = getattr(torch, self.settings.model_dtype)
        model = AutoModel.from_pretrained(
            self.settings.model_path,
            local_files_only=True,
            torch_dtype=dtype,
        )
        model.to(self.settings.device)
        model.eval()

        native_dimension = int(model.config.hidden_size)
        if self.settings.embedding_dim > native_dimension:
            raise RuntimeError(
                "configured embedding dimension exceeds model hidden size: "
                f"configured={self.settings.embedding_dim} native={native_dimension}"
            )

        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
        self._dimension = self.settings.embedding_dim

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not self.loaded or self._torch is None:
            raise RuntimeError("embedding model is not loaded")

        result: list[list[float]] = []
        with self._lock:
            for start in range(0, len(texts), self.settings.encode_batch_size):
                batch = texts[start : start + self.settings.encode_batch_size]
                encoded = self._tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=self.settings.max_sequence_length,
                    return_tensors="pt",
                )
                encoded = {
                    name: value.to(self.settings.device) for name, value in encoded.items()
                }
                with self._torch.inference_mode():
                    output = self._model(**encoded)
                    vectors = last_token_pool(
                        output.last_hidden_state,
                        encoded["attention_mask"],
                    )
                    vectors = vectors[:, : self.settings.embedding_dim].float()
                    if self.settings.normalize_embeddings:
                        vectors = self._torch.nn.functional.normalize(vectors, p=2, dim=1)
                result.extend(vectors.cpu().tolist())
        return result


def last_token_pool(last_hidden_states, attention_mask):
    """Pool the final non-padding token, matching the Qwen3 embedding contract."""
    left_padding = attention_mask[:, -1].sum() == attention_mask.shape[0]
    if left_padding:
        return last_hidden_states[:, -1]
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]
    batch_indices = attention_mask.new_tensor(range(batch_size))
    return last_hidden_states[batch_indices, sequence_lengths]
