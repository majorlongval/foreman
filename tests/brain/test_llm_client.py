"""Tests for brain.llm_client — provider-agnostic LLM interface."""

from unittest.mock import MagicMock, patch
from pydantic import BaseModel
from brain.llm_client import LLMClient


class MySchema(BaseModel):
    answer: str


class TestCompleteResponseFormat:
    def test_response_format_forwarded_to_litellm(self) -> None:
        """When response_format is passed, it must reach litellm.completion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"answer": "yes"}'
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("brain.llm_client.litellm.completion", return_value=mock_response) as mock_litellm:
            client = LLMClient()
            client.complete(
                model="gemini/gemini-3-flash-preview",
                system="You are helpful.",
                message="Answer yes or no.",
                response_format=MySchema,
            )
            call_kwargs = mock_litellm.call_args.kwargs
            assert call_kwargs.get("response_format") == MySchema

    def test_response_format_none_not_forwarded(self) -> None:
        """When response_format is not passed, it must not appear in litellm kwargs."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "hello"
        mock_response.usage.prompt_tokens = 10
        mock_response.usage.completion_tokens = 5

        with patch("brain.llm_client.litellm.completion", return_value=mock_response) as mock_litellm:
            client = LLMClient()
            client.complete(
                model="gemini/gemini-3-flash-preview",
                system="You are helpful.",
                message="Say hello.",
            )
            call_kwargs = mock_litellm.call_args.kwargs
            assert "response_format" not in call_kwargs
