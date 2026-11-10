import logging

from langchain_groq import ChatGroq

from app.config import settings

log = logging.getLogger(__name__)

INJECTION_THRESHOLD = 0.5  # Prompt Guard scores are bimodal: ~0.0005 benign vs ~0.9996 jailbreak in our tests

_guard = ChatGroq(
    model=settings.guard_model, api_key=settings.groq_api_key, max_retries=1, timeout=10
)


def injection_score(text: str) -> float | None:
    """Jailbreak probability from Llama Prompt Guard 2, or None if the guard is unavailable."""
    try:
        return float(_guard.invoke(text).content)
    except (
        Exception
    ) as e:  # fail open: the blast radius is small (no tools, grounded and cited answers)
        log.error("Prompt guard unavailable, request allowed: %s", e)
        return None
