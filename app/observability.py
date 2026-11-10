import json
import logging
from datetime import UTC, datetime

from langfuse import Langfuse

from app.config import settings
from app.governance.pii import mask_pii, mask_trace_data

# Keys passed explicitly: pydantic-settings loads .env into `settings` but not into os.environ,
# so the SDK's own environment lookup finds nothing when running outside Docker.
langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    base_url=settings.langfuse_base_url,
    environment=settings.langfuse_tracing_environment,
    tracing_enabled=settings.langfuse_tracing_enabled,
    mask=mask_trace_data,  # runs on every span's input/output/metadata before it leaves the process
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        return mask_pii(json.dumps(entry | getattr(record, "fields", {}), default=str))


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
