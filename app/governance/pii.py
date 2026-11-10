import json
import re

# shortcut: regex catches emails and phone numbers only, not names or addresses; add NER (e.g. Presidio) if those must be masked.
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SEP = r"\s.\-‐-―"  # LLMs rewrite "-" as non-breaking/en/em dashes (U+2010..U+2015)
PHONE = re.compile(
    rf"(?:\+\d{{1,3}}|\(\d{{2,4}}\))[{SEP}]?\d[\d{SEP}]{{5,}}\d"
)  # needs +country or (area): dates stay


def mask_pii(text: str) -> str:
    return PHONE.sub("[PHONE]", EMAIL.sub("[EMAIL]", text))


def mask_trace_data(*, data, **_):
    """Langfuse mask hook: data can be any JSON-like structure, so mask its JSON text and parse it back."""
    return json.loads(
        mask_pii(json.dumps(data, default=str))
    )  # the patterns never match quotes or braces
