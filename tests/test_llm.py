"""Provider routing tests with mocked SDK clients."""

from types import SimpleNamespace

from pydantic import SecretStr

from agent.llm import LLMClient


class Settings:
    groq_api_key = SecretStr("test-groq-key")
    groq_model = "test-groq-model"
    gemini_api_key = SecretStr("test-gemini-key")
    gemini_model = "test-gemini-model"
    llm_timeout_seconds = 30


class GroqStub:
    def __init__(self, fail=False):
        self.fail = fail
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if self.fail:
            raise TimeoutError("simulated provider timeout")
        message = SimpleNamespace(content="OK")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class GeminiStub:
    def generate_content(self, prompt, generation_config, request_options=None):
        return SimpleNamespace(text="OK")


def test_groq_success_keeps_primary_provider():
    client = LLMClient(Settings(), GroqStub(), GeminiStub())
    result = client.generate([{"role": "user", "content": "Reply OK"}])
    assert result == "OK"
    assert client.provider == "groq"


def test_groq_timeout_falls_back_to_gemini(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda _: None)
    client = LLMClient(Settings(), GroqStub(fail=True), GeminiStub())
    result = client.generate([{"role": "user", "content": "Reply OK"}])
    assert result == "OK"
    assert client.provider == "gemini"
