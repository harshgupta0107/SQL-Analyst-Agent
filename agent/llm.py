"""Groq-first model client with automatic Gemini fallback."""

from __future__ import annotations
import logging
import time
from typing import Any, Sequence
from config import Settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Generate text from Groq, switching to Gemini after provider failure."""

    def __init__(
        self,
        settings: Settings,
        groq_client: Any | None = None,
        gemini_model: Any | None = None,
    ) -> None:
        self.settings = settings
        self._groq = groq_client
        self._gemini = gemini_model
        self.provider = "groq"

    def _clients(self):
        if self._groq is None:
            try:
                from groq import Groq

                self._groq = Groq(
                    api_key=self.settings.groq_api_key.get_secret_value(),
                    timeout=self.settings.llm_timeout_seconds,
                )
            except Exception:
                logger.warning("Groq client initialization failed.")
        if self._gemini is None:
            try:
                import google.generativeai as genai

                genai.configure(api_key=self.settings.gemini_api_key.get_secret_value())
                self._gemini = genai.GenerativeModel(self.settings.gemini_model)
            except Exception:
                logger.warning("Gemini client initialization failed.")

    def generate(
        self, messages: Sequence[dict[str, str]], json_mode: bool = False
    ) -> str:
        """Generate a response with up to three attempts and provider fallback."""
        prompt = "\n\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
        )
        providers = ("groq", "gemini") if self.provider == "groq" else ("gemini",)
        last = None
        for provider in providers:
            for attempt in range(3):
                try:
                    self._clients()
                    if provider == "groq":
                        if self._groq is None:
                            raise RuntimeError("Groq client is unavailable.")
                        kwargs = {
                            "model": self.settings.groq_model,
                            "messages": list(messages),
                            "temperature": 0,
                            "timeout": self.settings.llm_timeout_seconds,
                        }
                        if json_mode:
                            kwargs["response_format"] = {"type": "json_object"}
                        response = self._groq.chat.completions.create(**kwargs)
                        self.provider = "groq"
                        return response.choices[0].message.content or ""
                    if self._gemini is None:
                        raise RuntimeError("Gemini client is unavailable.")
                    response = self._gemini.generate_content(
                        prompt,
                        generation_config={
                            "temperature": 0,
                            "response_mime_type": "application/json"
                            if json_mode
                            else "text/plain",
                        },
                        request_options={
                            "timeout": self.settings.llm_timeout_seconds
                        },
                    )
                    self.provider = "gemini"
                    return response.text
                except Exception as exc:
                    last = exc
                    logger.warning(
                        "LLM provider %s failed (attempt %d).", provider, attempt + 1
                    )
                    if attempt < 2:
                        time.sleep(0.25 * (2**attempt))
            self.provider = "gemini"
        raise RuntimeError(
            "Both AI providers are unavailable. Please retry in a moment."
        ) from last
