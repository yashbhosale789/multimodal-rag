from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

from app.config import settings

# OpenRouter's free tier allows ~20 requests/min; pace below that instead of burning retries on 429s.
_openrouter_limiter = InMemoryRateLimiter(requests_per_second=0.3)


def make_llm(openrouter_model: str, groq_model: str, schema=None):
    primary = ChatOpenAI(
        model=openrouter_model,
        base_url="https://openrouter.ai/api/v1",  # OpenRouter speaks the OpenAI API
        api_key=settings.openrouter_api_key,
        rate_limiter=_openrouter_limiter,
        max_retries=1,  # free models 429 when their host is congested; fail over fast instead of waiting
        timeout=60,
        temperature=0,
    )
    fallback = ChatGroq(
        model=groq_model,
        api_key=settings.groq_api_key,
        max_retries=6,  # last line of defence: Groq's free tier is 8K tokens/min, so wait for the window to refill
        timeout=60,
        temperature=0,
    )
    if (
        schema
    ):  # must wrap each model before chaining, so the fallback returns the same schema
        primary, fallback = primary.with_structured_output(
            schema
        ), fallback.with_structured_output(schema)
    return primary.with_fallbacks([fallback])
