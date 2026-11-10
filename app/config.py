from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # extra="ignore": .env also holds UI-only vars (API_URL) that the backend doesn't declare.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    google_api_key: str  # embeddings only
    pinecone_api_key: str
    openrouter_api_key: str
    groq_api_key: str
    tavily_api_key: str
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_base_url: str
    langfuse_tracing_environment: str = "development"
    langfuse_tracing_enabled: bool = True  # tests set it false so they don't send traces

    # Image captioning: OpenRouter primary, Groq fallback. Both verified to read images.
    vision_model: str = "nvidia/nemotron-3.5-super-vl:free"
    vision_fallback_model: str = "qwen/qwen3.8-27b"

    # Grading and generation: OpenRouter primary, Groq fallback. Both support structured output.
    chat_model: str = "nvidia/nemotron-3.5-super-vl:free"
    chat_fallback_model: str = "openai/gpt-oss-120b"

    # Prompt-injection classifier on Groq; 512-token window, so questions are capped at 1000 chars.
    guard_model: str = "meta-llama/llama-prompt-guard-2-86m"

    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768

    @property
    def pinecone_index(self) -> str:
        # Derived, never configured: a new model/dim can't silently query an old index.
        return f"rag-{self.embedding_model}-{self.embedding_dim}"


settings = Settings()
