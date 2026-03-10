"""
FOREMAN LLM Client — provider-agnostic interface for AI calls.

Supports:
  - Anthropic (Claude)
  - Google Gemini (via google-genai SDK)
  - OpenAI-compatible APIs (OpenAI, Groq, Together, local models via LM Studio/Ollama)

All providers expose the same interface: complete(system, user_message) → LLMResponse

Model strings use a "provider/model" format:
  - "anthropic/claude-sonnet-4-20250514"
  - "gemini/gemini-2.5-flash"
  - "openai/gpt-4o"
  - "groq/llama-3.3-70b-versatile"
  - "ollama/codellama"          (local via OpenAI-compat endpoint)

Usage:
    from llm_client import LLMClient

    llm = LLMClient()
    response = llm.complete(
        model="gemini/gemini-2.5-flash",
        system="You are a helpful assistant.",
        message="Refine this ticket...",
        max_tokens=2000,
    )
    print(response.text)
    print(response.input_tokens, response.output_tokens, response.cost_usd)
"""

import os
import logging
from dataclasses import dataclass
from typing import List

log = logging.getLogger("foreman.llm")


# ─── Response ────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # estimated based on known pricing
    raw: object = None  # original provider response for debugging


# ─── Pricing ─────────────────────────────────────────────────

# Per 1M tokens: (input, output)
# Update these as pricing changes. Agent can update this file itself later.
PRICING = {
    # Anthropic
    "anthropic/claude-opus-4-20250514":    (15.0, 75.0),
    "anthropic/claude-sonnet-4-20250514":  (3.0, 15.0),
    "anthropic/claude-haiku-4-5-20251001": (0.80, 4.0),

    # Google Gemini — 2.5 series (stable)
    "gemini/gemini-2.5-pro":               (1.25, 10.0),
    "gemini/gemini-2.5-flash":             (0.15, 0.60),
    "gemini/gemini-2.5-flash-lite":        (0.075, 0.30),
    # Google Gemini — 3.x series (preview, pricing TBD — estimated)
    "gemini/gemini-3.1-pro-preview":       (1.25, 10.0),
    "gemini/gemini-3-flash-preview":       (0.15, 0.60),
    "gemini/gemini-3.1-flash-lite-preview":(0.075, 0.30),

    # OpenAI
    "openai/gpt-4o":                       (2.50, 10.0),
    "openai/gpt-4o-mini":                  (0.15, 0.60),
    "openai/o3-mini":                      (1.10, 4.40),
    "openai/text-embedding-3-small":       (0.02, 0.0),
    "openai/text-embedding-3-large":       (0.13, 0.0),

    # Groq (fast inference)
    "groq/llama-3.3-70b-versatile":        (0.59, 0.79),
    "groq/gemma2-9b-it":                   (0.20, 0.20),

    # Local models (free)
    "ollama/any":                          (0.0, 0.0),
}

def estimate_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a completion."""
    pricing = PRICING.get(model_key)
    if not pricing:
        # Try matching just the provider for local models
        provider = model_key.split("/")[0]
        if provider in ("ollama", "lmstudio", "local"):
            return 0.0
        log.warning(f"No pricing found for model {model_key}, using 0.0")
        return 0.0
    
    in_cost = (input_tokens / 1_000_000) * pricing[0]
    out_cost = (output_tokens / 1_000_000) * pricing[1]
    return in_cost + out_cost


# ─── Client ──────────────────────────────────────────────────

class LLMClient:
    def __init__(self):
        self.default_model = os.getenv("LLM_MODEL", "openai/gpt-4o")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")

    def complete(self, system: str, message: str, model: str = None, max_tokens: int = 4000) -> LLMResponse:
        """Standard completion interface."""
        target_model = model or self.default_model
        provider = target_model.split("/")[0]
        
        try:
            if provider == "openai":
                return self._openai_complete(target_model, system, message, max_tokens)
            elif provider == "anthropic":
                return self._anthropic_complete(target_model, system, message, max_tokens)
            elif provider == "gemini":
                return self._gemini_complete(target_model, system, message, max_tokens)
            elif provider == "groq":
                return self._groq_complete(target_model, system, message, max_tokens)
            elif provider in ("ollama", "local"):
                return self._openai_complete(target_model, system, message, max_tokens, base_url=os.getenv("LOCAL_LLM_URL", "http://localhost:11434/v1"))
            else:
                raise ValueError(f"Unknown provider: {provider}")
        except Exception as e:
            log.error(f"LLM completion failed for {target_model}: {e}")
            raise

    def get_embedding(self, text: str, model: str = None) -> List[float]:
        """
        Generate an embedding vector for the provided text.
        Defaults to OpenAI text-embedding-3-small or EMBEDDING_MODEL env var.
        """
        target_model = model or self.embedding_model
        provider = target_model.split("/")[0]
        
        try:
            log.info(f"Generating embedding using {target_model}")
            if provider == "openai":
                return self._openai_embedding(target_model, text)
            elif provider == "gemini":
                return self._gemini_embedding(target_model, text)
            else:
                # Fallback to OpenAI-compatible for other providers if they support it
                return self._openai_embedding(target_model, text)
        except Exception as e:
            log.error(f"Embedding generation failed for {target_model}: {e}")
            raise

    # ─── Provider Implementations ────────────────────────────

    def _openai_complete(self, model: str, system: str, message: str, max_tokens: int, base_url: str = None) -> LLMResponse:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), base_url=base_url)
        
        model_name = model.split("/", 1)[1] if "/" in model else model
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message}
            ],
            max_tokens=max_tokens,
        )
        
        in_tokens = response.usage.prompt_tokens
        out_tokens = response.usage.completion_tokens
        
        return LLMResponse(
            text=response.choices[0].message.content,
            model=model,
            provider="openai",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=estimate_cost(model, in_tokens, out_tokens),
            raw=response
        )

    def _openai_embedding(self, model: str, text: str) -> List[float]:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        model_name = model.split("/", 1)[1] if "/" in model else model
        
        response = client.embeddings.create(
            input=text,
            model=model_name
        )
        return response.data[0].embedding

    def _anthropic_complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        import anthropic
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        
        model_name = model.split("/", 1)[1]
        
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": message}]
        )
        
        in_tokens = response.usage.input_tokens
        out_tokens = response.usage.output_tokens
        
        return LLMResponse(
            text=response.content[0].text,
            model=model,
            provider="anthropic",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=estimate_cost(model, in_tokens, out_tokens),
            raw=response
        )

    def _gemini_complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        
        model_name = model.split("/", 1)[1]
        gemini_model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system
        )
        
        response = gemini_model.generate_content(
            message,
            generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens)
        )
        
        # Gemini usage metadata
        in_tokens = response.usage_metadata.prompt_token_count
        out_tokens = response.usage_metadata.candidates_token_count
        
        return LLMResponse(
            text=response.text,
            model=model,
            provider="gemini",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=estimate_cost(model, in_tokens, out_tokens),
            raw=response
        )

    def _gemini_embedding(self, model: str, text: str) -> List[float]:
        import google.generativeai as genai
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model_name = model.split("/", 1)[1] if "/" in model else "models/text-embedding-004"
        
        response = genai.embed_content(
            model=model_name,
            content=text,
            task_type="retrieval_document"
        )
        return response['embedding']

    def _groq_complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        model_name = model.split("/", 1)[1]
        
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message}
            ],
            max_tokens=max_tokens,
        )
        
        in_tokens = response.usage.prompt_tokens
        out_tokens = response.usage.completion_tokens
        
        return LLMResponse(
            text=response.choices[0].message.content,
            model=model,
            provider="groq",
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            cost_usd=estimate_cost(model, in_tokens, out_tokens),
            raw=response
        )