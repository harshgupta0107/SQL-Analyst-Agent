"""Small in-session context for conversational follow-ups."""

from collections import deque


class ConversationMemory:
    """Keep a bounded set of recent questions and SQL/result summaries."""

    def __init__(self, max_turns: int = 6):
        self.turns = deque(maxlen=max_turns)
        self.pending_clarification: str | None = None

    def set_pending_clarification(self, question: str) -> None:
        """Remember the request that a clarification will complete."""
        self.pending_clarification = question

    def consume_pending_clarification(self) -> str | None:
        """Return and clear the outstanding clarification context."""
        question = self.pending_clarification
        self.pending_clarification = None
        return question

    def add(self, question: str, sql: str, summary: str) -> None:
        self.turns.append({"question": question, "sql": sql, "summary": summary})

    def context(self) -> str:
        return "\n".join(
            f"Q: {t['question']}\nSQL: {t['sql']}\nResult: {t['summary']}"
            for t in self.turns
        )

    def clear(self) -> None:
        self.turns.clear()
        self.pending_clarification = None
