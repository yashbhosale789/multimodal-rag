import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"  # unit tests must not send traces to Langfuse Cloud
