"""Provider adapters. One per API shape, not one per model."""

from .base import (
    Adapter,
    GeneratedImage,
    GenerationParams,
    ProviderError,
    Result,
)
from .echo import EchoAdapter

__all__ = [
    "Adapter",
    "EchoAdapter",
    "GeneratedImage",
    "GenerationParams",
    "ProviderError",
    "Result",
    "get_adapter",
]


def get_adapter(name: str | None = None, **kwargs):
    """Resolve an adapter by name. Defaults to `echo` so nothing costs money by accident.

    `foundry` is imported lazily — it needs httpx and a configured endpoint, and the
    echo path should stay usable when neither exists.
    """
    name = (name or "echo").lower()
    if name == "echo":
        return EchoAdapter(**kwargs)
    if name == "foundry":
        from .foundry import FoundryAdapter

        return FoundryAdapter(**kwargs)
    raise ValueError(f"Unknown adapter {name!r}. Available: echo, foundry.")
