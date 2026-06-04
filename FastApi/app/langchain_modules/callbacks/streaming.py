class ThinkingTagParser:
    OPEN = "<think>"
    CLOSE = "</think>"

    def __init__(self, emit_reasoning: bool) -> None:
        self.emit_reasoning = emit_reasoning
        self.in_reasoning = False
        self.pending = ""

    def feed(self, token: str) -> list[dict[str, str]]:
        self.pending += token
        chunks: list[dict[str, str]] = []
        while self.pending:
            if self.in_reasoning:
                close_index = self.pending.lower().find(self.CLOSE)
                if close_index >= 0:
                    self._append(chunks, "reasoning", self.pending[:close_index])
                    self.pending = self.pending[close_index + len(self.CLOSE):]
                    self.in_reasoning = False
                    continue
                emit_length = safe_emit_length(self.pending, [self.CLOSE])
                if emit_length <= 0:
                    break
                self._append(chunks, "reasoning", self.pending[:emit_length])
                self.pending = self.pending[emit_length:]
                continue

            open_index = self.pending.lower().find(self.OPEN)
            if open_index >= 0:
                self._append(chunks, "delta", self.pending[:open_index])
                self.pending = self.pending[open_index + len(self.OPEN):]
                self.in_reasoning = True
                continue
            emit_length = safe_emit_length(self.pending, [self.OPEN])
            if emit_length <= 0:
                break
            self._append(chunks, "delta", self.pending[:emit_length])
            self.pending = self.pending[emit_length:]
        return chunks

    def flush(self) -> list[dict[str, str]]:
        kind = "reasoning" if self.in_reasoning else "delta"
        chunks: list[dict[str, str]] = []
        self._append(chunks, kind, self.pending)
        self.pending = ""
        return chunks

    def _append(self, chunks: list[dict[str, str]], kind: str, text: str) -> None:
        if not text:
            return
        if kind == "reasoning" and not self.emit_reasoning:
            return
        chunks.append({"type": kind, "text": text})


def safe_emit_length(buffer: str, tags: list[str]) -> int:
    lower = buffer.lower()
    keep = 0
    max_tag_length = max(len(tag) for tag in tags)
    for length in range(1, min(len(buffer), max_tag_length - 1) + 1):
        suffix = lower[-length:]
        if any(tag.startswith(suffix) for tag in tags):
            keep = length
    return len(buffer) - keep
