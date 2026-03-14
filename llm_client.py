"""
FOREMAN LLM Client — provider-agnostic interface for AI calls via LiteLLM.

Supports:
  - Anthropic (Claude)
  - Google Gemini
  - OpenAI, Groq, Together, Ollama, LM Studio
  - Any LiteLLM-supported provider

All providers expose the same interface: complete(system, user_message) → LLMResponse

Model strings use a "provider/model" format:
  - "anthropic/claude-3-5-sonnet-20241022"
  - "gemini/gemini-2.0-flash"
  - "openai/gpt-4o"
  - "groq/llama-3.3-70b-versatile"
  - "ollama/qwen2.5-coder:32b"

Usage:
    from llm_client import LLMClient

    llm = LLMClient()
    response = llm.complete(
        model="gemini/gemini-2.0-flash",
        system="You are a helpful assistant.",
        message="Refine this ticket...",
        max_tokens=2000,
    )
    print(response.text)
    print(response.input_tokens, response.output_tokens, response.cost_usd)
"""

import os
import logging
import litellm
from dataclasses import dataclass
from typing import List

log = logging.getLogger("foreman.llm")

# LiteLLM configuration
litellm.telemetry = False
litellm.drop_params = True # Silently drop unsupported params like thinking_config

# ─── Response ────────────────────────────────────────────────

@dataclass
class TokenUsage:
    """Unified token usage counts for cost tracking."""
    input_tokens: int
    output_tokens: int

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
PRICING = {
    # Anthropic (bare keys for callers that pass model name without provider prefix)
    "claude-sonnet-4-6":         {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-6":           {"input": 15.0, "output": 75.0},
    "anthropic/claude-sonnet-4-6":         {"input": 3.0,  "output": 15.0},
    "anthropic/claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "anthropic/claude-opus-4-6":           {"input": 15.0, "output": 75.0},
    # Gemini
    "gemini/gemini-2.5-pro":               {"input": 1.25, "output": 10.0},
    "gemini/gemini-2.5-flash":             {"input": 0.15, "output": 0.60},
    "gemini/gemini-2.5-flash-lite":        {"input": 0.075, "output": 0.30},
    "gemini/gemini-3.1-pro-preview":       {"input": 1.25, "output": 10.0},
    "gemini/gemini-3-flash-preview":       {"input": 0.15, "output": 0.60},
    "gemini/gemini-3.1-flash-lite-preview":{"input": 0.075, "output": 0.30},

    # Embedding models
    "gemini/text-embedding-004":           {"input": 0.0, "output": 0.0}, 

    # OpenAI
    "openai/gpt-4o":                       {"input": 2.50, "output": 10.0},
    "openai/gpt-4o-mini":                  {"input": 0.15, "output": 0.60},
    "openai/o3-mini":                      {"input": 1.10, "output": 4.40},
    "openai/text-embedding-3-small":       {"input": 0.02, "output": 0.0},
    "openai/text-embedding-3-large":       {"input": 0.13, "output": 0.0},

    # Groq
    "groq/llama-3.3-70b-versatile":        {"input": 0.59, "output": 0.79},
    "groq/gemma2-9b-it":                   {"input": 0.20, "output": 0.20},

    # Local models (free)
    "ollama/any":                          {"input": 0.0, "output": 0.0},
}

def estimate_cost(model_key: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a completion."""
    pricing = PRICING.get(model_key)
    
    # Fallback to check without provider prefix
    if not pricing and "/" in model_key:
        pricing = PRICING.get(model_key.split("/", 1)[1])
        
    if not pricing:
        provider = model_key.split("/")[0]
        if provider in ("ollama", "lmstudio", "local"):
            return 0.0
        # Default to most expensive if unknown to be safe
        pricing = {"input": 15.0, "output": 75.0}
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


# ─── Unified Client ──────────────────────────────────────────

class LLMClient:
    """Provider-agnostic LLM client using LiteLLM.

    Usage:
        llm = LLMClient()
        resp = llm.complete("gemini/gemini-2.5-flash", "You are...", "Do X", 2000)
    """

    def __init__(self, tracker=None):
        self.tracker = tracker
        self._ollama_base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        # Map existing env vars to litellm expected names if needed
        if os.environ.get("GEMINI_API_KEY") and not os.environ.get("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = os.environ.get("GEMINI_API_KEY")

    def complete(
        self,
        model: str,
        system: str,
        message: str,
        max_tokens: int = None,
        agent: str = "unknown",
        action: str = "unknown",
    ) -> LLMResponse:
        """Send a completion request to any supported provider via LiteLLM."""
        try:
            if "/" not in model:
                raise ValueError(f"Model must be in 'provider/model' format, got: '{model}'")

            provider, model_name = model.split("/", 1)

            kwargs = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": message},
                ],
            }
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            
            if provider == "ollama":
                kwargs["api_base"] = self._ollama_base

            log.info(f"  🤖 {model}" + (f" (max {max_tokens} tokens)" if max_tokens else ""))
            
            response = litellm.completion(**kwargs)
            if not getattr(response, "choices", None):
                raise ValueError(f"LLM API returned no choices (possibly blocked). Raw response: {response}")
            text = response.choices[0].message.content or ""
            
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            cost = estimate_cost(model, input_tokens, output_tokens)

            # Record cost if tracker is attached
            if self.tracker:
                try:
                    self.tracker.record(
                        model=model,
                        usage=TokenUsage(input_tokens, output_tokens),
                        agent=agent,
                        action=action
                    )
                except Exception as e:
                    log.error(f"  Cost recording failed: {e}")

            log.info(f"  ✓ {input_tokens} in / {output_tokens} out = ${cost:.4f}")
            return LLMResponse(
                text=text,
                model=model_name,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost,
                raw=response,
            )
        except Exception as e:
            log.error(f"  LLM complete call failed: {e}")
            raise

    def generate_embedding(self, text: str, model: str = None, agent: str = "unknown", action: str = "embed") -> List[float]:
        """Generate a text embedding using LiteLLM."""
        try:
            if not model:
                if os.environ.get("OPENAI_API_KEY"):
                    model = "openai/text-embedding-3-small"
                elif os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
                    model = "gemini/text-embedding-004"
                else:
                    raise ValueError("No default embedding model found (neither OPENAI_API_KEY nor GEMINI_API_KEY set)")

            if "/" not in model:
                raise ValueError(f"Model must be in 'provider/model' format, got: '{model}'")

            provider, _ = model.split("/", 1)
            kwargs = {"model": model, "input": [text]}
            
            if provider == "ollama":
                kwargs["api_base"] = self._ollama_base

            log.info(f"  🧬 Generating embedding with {model}")
            response = litellm.embedding(**kwargs)
            if not getattr(response, "data", None):
                raise ValueError(f"LLM API returned no embedding data (possibly blocked). Raw response: {response}")
            
            # Record cost if tracker is attached
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            cost = estimate_cost(model, input_tokens, 0)
            
            if self.tracker:
                try:
                    self.tracker.record(
                        model=model,
                        usage=TokenUsage(input_tokens, 0),
                        agent=agent,
                        action=action
                    )
                except Exception as e:
                    log.error(f"  Cost recording for embedding failed: {e}")
            
            log.info(f"  ✓ embedding {input_tokens} tokens = ${cost:.4f}")
            return response.data[0].embedding
        except Exception as e:
            log.error(f"  Embedding generation failed: {e}")
            raise


# ─── Model Router ─────────────────────────────────────────────

ROUTING_PROFILES = {
    "cheap": {
        "refine": "gemini/gemini-3-flash-preview",
        "brainstorm": "gemini/gemini-3-flash-preview",
        "review": "gemini/gemini-3.1-pro-preview",
        "review_confirm": "gemini/gemini-3.1-pro-preview",
        "fix": "gemini/gemini-3-flash-preview",
        "title_gen": "gemini/gemini-3.1-flash-lite-preview",
        "commit_msg": "gemini/gemini-3.1-flash-lite-preview",
        "implement": "gemini/gemini-3-flash-preview",
        "plan": "gemini/gemini-3.1-pro-preview",
        "embed": "gemini/text-embedding-004",
    },
    "balanced": {
        "refine": "anthropic/claude-sonnet-4-6",
        "brainstorm": "anthropic/claude-sonnet-4-6",
        "review": "anthropic/claude-opus-4-6",
        "review_confirm": "anthropic/claude-opus-4-6",
        "fix": "anthropic/claude-sonnet-4-6",
        "title_gen": "gemini/gemini-3.1-flash-lite-preview",
        "commit_msg": "gemini/gemini-3.1-flash-lite-preview",
        "implement": "anthropic/claude-sonnet-4-6",
        "plan": "anthropic/claude-opus-4-6",
        "embed": "openai/text-embedding-3-small",
    },
    "quality": {
        "refine": "anthropic/claude-sonnet-4-6",
        "brainstorm": "anthropic/claude-opus-4-6",
        "review": "anthropic/claude-opus-4-6",
        "review_confirm": "anthropic/claude-opus-4-6",
        "fix": "anthropic/claude-sonnet-4-6",
        "title_gen": "anthropic/claude-sonnet-4-6",
        "commit_msg": "anthropic/claude-sonnet-4-6",
        "implement": "anthropic/claude-opus-4-6",
        "plan": "anthropic/claude-opus-4-6",
        "embed": "openai/text-embedding-3-large",
    },
}


class ModelRouter:
    """Routes tasks to appropriate models based on a routing profile."""

    def __init__(self, profile: str = "balanced", overrides: dict = None):
        if profile not in ROUTING_PROFILES:
            raise ValueError(f"Unknown profile: '{profile}'. Use: {list(ROUTING_PROFILES.keys())}")

        self.profile_name = profile
        self.routes = {**ROUTING_PROFILES[profile]}

        if overrides:
            self.routes.update(overrides)
            log.info(f"  Router: {profile} profile with overrides: {overrides}")
        else:
            log.info(f"  Router: {profile} profile")

    def get(self, task: str) -> str:
        """Get the model string for a task type."""
        if task not in self.routes:
            log.warning(f"  No route for task '{task}', falling back to refine model")
            return self.routes.get("refine", "anthropic/claude-sonnet-4-6")
        return self.routes[task]

    def summary(self) -> str:
        lines = [f"Router profile: {self.profile_name}"]
        for task, model in sorted(self.routes.items()):
            pricing = PRICING.get(model, {"input": 0, "output": 0})
            lines.append(f"  {task:12s} → {model:45s} (${pricing['input']:.2f}/${pricing['output']:.2f} per 1M)")
        return "\n".join(lines)