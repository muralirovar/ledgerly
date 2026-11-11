from __future__ import annotations

import os


def provider_status() -> dict[str, bool]:
    return {
        "OpenAI": bool(os.getenv("OPENAI_API_KEY")),
        "Anthropic / Claude": bool(os.getenv("ANTHROPIC_API_KEY")),
    }


def guidance() -> str:
    return (
        "AI is optional and currently disabled for transaction decisions. "
        "Set OPENAI_API_KEY or ANTHROPIC_API_KEY in your environment (or Docker .env) "
        "when you are ready. Keys are never stored in the bookkeeping database."
    )
