from typing import Any


def format_history(history: list[dict[str, str]] | None) -> str:
    if not history:
        return "(none)"
    lines: list[str] = []
    for item in history:
        role = str(item.get("role") or "user")[:32]
        content = str(item.get("content") or item.get("message") or "").strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines) if lines else "(none)"


def format_runtime_context(runtime_context: str | list[str] | dict[str, Any] | None) -> str:
    if runtime_context is None:
        return "(none)"
    if isinstance(runtime_context, str):
        value = runtime_context.strip()
        return value if value else "(none)"
    if isinstance(runtime_context, list):
        lines = [str(item).strip() for item in runtime_context if str(item).strip()]
        return "\n".join(lines) if lines else "(none)"
    return "\n".join(f"{key}: {value}" for key, value in runtime_context.items())


def format_context_summary(context_summary: str | None) -> str:
    if not context_summary:
        return "(none)"
    return context_summary.strip() or "(none)"


def format_context_budget(context_compressed: bool, token_budget: int | None, context_window_tokens: int | None) -> str:
    return (
        f"compressed={str(context_compressed).lower()}, "
        f"token_budget={token_budget if token_budget is not None else 'unknown'}, "
        f"context_window_tokens={context_window_tokens if context_window_tokens is not None else 'unknown'}"
    )
