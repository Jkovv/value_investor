"""15 · llm: every model call goes through get_llm().

It returns a LangChain chat model backed by a LiteLLM Router running in
process. The caller always asks for one logical model; the Router decides
who serves it:

    primary    config.LLM_PRIMARY (local Ollama unless told otherwise)
    fallbacks  the other backends that have credentials, Groq before Hugging Face

The Hugging Face router speaks the OpenAI API, so it goes in as an
"openai/" model with a different base URL.
"""

import litellm
from langchain_litellm import ChatLiteLLMRouter
from litellm import Router

from value_investor import config

litellm.drop_params = True

_ORDER = ("ollama", "groq", "huggingface")
_router: "Router | None" = None
_primary: "str | None" = None


def _deployments() -> dict:
    out = {
        "ollama": {
            "model": f"ollama_chat/{config.OLLAMA_MODEL}",
            "api_base": config.OLLAMA_BASE_URL,
            "num_ctx": config.OLLAMA_NUM_CTX,
        },
    }
    if config.GROQ_API_KEY:
        out["groq"] = {"model": f"groq/{config.GROQ_MODEL}", "api_key": config.GROQ_API_KEY}
    if config.HF_TOKEN:
        out["huggingface"] = {
            "model": f"openai/{config.HF_MODEL}",
            "api_base": config.HF_BASE_URL,
            "api_key": config.HF_TOKEN,
        }
    return out


def backends() -> list:
    deployments = _deployments()
    order = [config.LLM_PRIMARY] + [name for name in _ORDER if name != config.LLM_PRIMARY]
    return [name for name in order if name in deployments]


def _get_router() -> "tuple[Router, str]":
    global _router, _primary
    if _router is None:
        deployments = _deployments()
        order = backends()
        names = [f"llm-{name}" for name in order]
        _router = Router(
            model_list=[{"model_name": n, "litellm_params": deployments[b]} for n, b in zip(names, order)],
            num_retries=1,
            fallbacks=[{names[0]: names[1:]}] if len(names) > 1 else [],
        )
        _primary = names[0]
    return _router, _primary


def tune(prompt: str) -> str:
    """Qwen3's soft switch: '/no_think' at the end of a prompt skips the thinking phase."""
    first = backends()[0] if backends() else None
    if first == "ollama" and config.OLLAMA_MODEL.startswith("qwen3") and not config.OLLAMA_THINK:
        return f"{prompt}\n/no_think"
    return prompt


def get_llm():
    router, primary = _get_router()
    return ChatLiteLLMRouter(router=router, model_name=primary, temperature=config.LLM_TEMPERATURE)


if __name__ == "__main__":
    print("Backends in order:", ", ".join(backends()))
    reply = get_llm().invoke("Answer with one word: what is the opposite of 'cheap'?")
    print("Reply:", reply.content.strip())
