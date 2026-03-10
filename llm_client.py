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
        log.warning(f"No pricing data for {model_key}, estimating $0")
        return 0.0
    input_price, output_price = pricing
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


# ─── Provider Backends ───────────────────────────────────────

class AnthropicBackend:
    def __init__(self):
        import anthropic
        self.client = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY")
        )

    def complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": message}],
        )
        model_key = f"anthropic/{model}"
        return LLMResponse(
            text=response.content[0].text,
            model=model,
            provider="anthropic",
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost_usd=estimate_cost(model_key, response.usage.input_tokens, response.usage.output_tokens),
            raw=response,
        )


class GeminiBackend:
    def __init__(self):
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        self.client = genai.Client(api_key=api_key)

    def complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        from google.genai import types

        config_kwargs = dict(
            system_instruction=system,
            max_output_tokens=max_tokens,
        )
        # Flash supports disabling thinking (saves tokens); Pro requires it
        if "flash" in model.lower():
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)

        response = self.client.models.generate_content(
            model=model,
            contents=message,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        # Extract token counts from usage metadata
        usage = response.usage_metadata
        input_tokens = usage.prompt_token_count or 0
        output_tokens = usage.candidates_token_count or 0

        text = response.text
        if text is None:
            # Response was blocked or empty — log finish reason for debugging
            try:
                reason = response.candidates[0].finish_reason
                log.warning(f"  Gemini returned None text, finish_reason={reason}")
            except Exception:
                log.warning("  Gemini returned None text (no candidates)")
            text = ""

        model_key = f"gemini/{model}"
        return LLMResponse(
            text=text,
            model=model,
            provider="gemini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(model_key, input_tokens, output_tokens),
            raw=response,
        )


class OpenAICompatBackend:
    """Works with OpenAI, Groq, Together, LM Studio, Ollama, and any
    OpenAI-compatible API endpoint."""

    # Known base URLs for different providers
    BASE_URLS = {
        "openai": "https://api.openai.com/v1",
        "groq": "https://api.groq.com/openai/v1",
        "together": "https://api.together.xyz/v1",
        "ollama": "http://localhost:11434/v1",
        "lmstudio": "http://localhost:1234/v1",
    }

    # Env var names for API keys per provider
    KEY_VARS = {
        "openai": "OPENAI_API_KEY",
        "groq": "GROQ_API_KEY",
        "together": "TOGETHER_API_KEY",
        "ollama": None,  # no key needed
        "lmstudio": None,
    }

    def __init__(self, provider: str):
        import openai
        self.provider = provider
        base_url = self.BASE_URLS.get(provider)
        key_var = self.KEY_VARS.get(provider)
        api_key = os.environ.get(key_var) if key_var else "not-needed"

        # Allow override via env
        base_url = os.environ.get(f"{provider.upper()}_BASE_URL", base_url)

        self.client = openai.OpenAI(api_key=api_key, base_url=base_url)

    def complete(self, model: str, system: str, message: str, max_tokens: int) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
        )

        choice = response.choices[0]
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        model_key = f"{self.provider}/{model}"
        return LLMResponse(
            text=choice.message.content,
            model=model,
            provider=self.provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=estimate_cost(model_key, input_tokens, output_tokens),
            raw=response,
        )


# ─── Unified Client ──────────────────────────────────────────

class LLMClient:
    """Provider-agnostic LLM client.

    Usage:
        llm = LLMClient()
        resp = llm.complete("gemini/gemini-2.5-flash", "You are...", "Do X", 2000)
    """

    def __init__(self):
        self._backends = {}  # lazy-loaded

    def _get_backend(self, provider: str):
        """Lazy-load and cache backends."""
        if provider not in self._backends:
            if provider == "anthropic":
                self._backends[provider] = AnthropicBackend()
            elif provider == "gemini":
                self._backends[provider] = GeminiBackend()
            elif provider in ("openai", "groq", "together", "ollama", "lmstudio"):
                self._backends[provider] = OpenAICompatBackend(provider)
            else:
                raise ValueError(
                    f"Unknown provider: '{provider}'. "
                    f"Use: anthropic, gemini, openai, groq, together, ollama, lmstudio"
                )
            log.info(f"  Initialized {provider} backend")
        return self._backends[provider]

    def complete(
        self,
        model: str,
        system: str,
        message: str,
        max_tokens: int = 2000,
    ) -> LLMResponse:
        """Send a completion request to any supported provider.

        Args:
            model: "provider/model-name" format (e.g. "gemini/gemini-2.5-flash")
            system: System prompt
            message: User message
            max_tokens: Max response tokens

        Returns:
            LLMResponse with text, token counts, and cost estimate
        """
        if "/" not in model:
            raise ValueError(
                f"Model must be in 'provider/model' format, got: '{model}'. "
                f"Example: 'anthropic/claude-sonnet-4-20250514'"
            )

        provider, model_name = model.split("/", 1)
        backend = self._get_backend(provider)

        log.info(f"  🤖 {provider}/{model_name} (max {max_tokens} tokens)")
        response = backend.complete(model_name, system, message, max_tokens)

        log.info(
            f"  ✓ {response.input_tokens} in / {response.output_tokens} out "
            f"= ${response.cost_usd:.4f}"
        )
        return response


# ─── Model Router ─────────────────────────────────────────────

# Predefined routing profiles — maps task types to models
ROUTING_PROFILES = {
    "cheap": {
        # 3.1 Flash for decisions, Flash Lite for cheap mechanical tasks
        "refine": "gemini/gemini-3-flash-preview",
        "brainstorm": "gemini/gemini-3-flash-preview",
        "review": "gemini/gemini-3-flash-preview",
        "review_confirm": "gemini/gemini-3.1-pro-preview",
        "title_gen": "gemini/gemini-3.1-flash-lite-preview",
        "commit_msg": "gemini/gemini-3.1-flash-lite-preview",
        "implement": "gemini/gemini-3-flash-preview",
        "plan": "gemini/gemini-3-flash-preview",
    },
    "balanced": {
        # Balance cost and quality
        "refine": "anthropic/claude-sonnet-4-20250514",
        "brainstorm": "anthropic/claude-sonnet-4-20250514",
        "review": "anthropic/claude-sonnet-4-20250514",
        "review_confirm": "anthropic/claude-opus-4-20250514",
        "title_gen": "gemini/gemini-3.1-flash-lite-preview",
        "commit_msg": "gemini/gemini-3.1-flash-lite-preview",
        "implement": "anthropic/claude-sonnet-4-20250514",
        "plan": "anthropic/claude-opus-4-20250514",
    },
    "quality": {
        # Maximize quality — use best models everywhere
        "refine": "anthropic/claude-sonnet-4-20250514",
        "brainstorm": "anthropic/claude-opus-4-20250514",
        "review": "anthropic/claude-opus-4-20250514",
        "review_confirm": "anthropic/claude-opus-4-20250514",
        "title_gen": "anthropic/claude-sonnet-4-20250514",
        "commit_msg": "anthropic/claude-sonnet-4-20250514",
        "implement": "anthropic/claude-opus-4-20250514",
        "plan": "anthropic/claude-opus-4-20250514",
    },
}


class ModelRouter:
    """Routes tasks to appropriate models based on a routing profile.

    Usage:
        router = ModelRouter("cheap")  # or "balanced" or "quality"
        model = router.get("refine")   # → "gemini/gemini-2.5-flash"

        # Override specific routes:
        router = ModelRouter("cheap", overrides={"brainstorm": "anthropic/claude-opus-4-20250514"})
    """

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
            return self.routes.get("refine", "anthropic/claude-sonnet-4-20250514")
        return self.routes[task]

    def summary(self) -> str:
        lines = [f"Router profile: {self.profile_name}"]
        for task, model in sorted(self.routes.items()):
            pricing = PRICING.get(model, (0, 0))
            lines.append(f"  {task:12s} → {model:45s} (${pricing[0]:.2f}/${pricing[1]:.2f} per 1M)")
        return "\n".join(lines)
