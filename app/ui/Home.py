import os
import uuid

import httpx
import streamlit as st

# Streamlit doesn't read .env; the default covers local runs, compose sets it in Docker.
API_URL = os.environ.get("API_URL", "http://localhost:8000")
CHAT_TIMEOUT = httpx.Timeout(
    90, connect=5
)  # the agent took up to ~45 s; a down API should fail in 5 s
UPLOAD_TIMEOUT = httpx.Timeout(
    300, connect=5
)  # image captions are rate-limited to ~18/min
BADGE_COLORS = {
    "Document": "blue",
    "Web": "violet",
    "Model knowledge": "orange",
    "Blocked": "red",
}

st.set_page_config(page_title="Multimodal RAG", page_icon="📄")
st.title("Multimodal Graph RAG")

try:
    httpx.get(f"{API_URL}/health", timeout=2.0).raise_for_status()
except httpx.HTTPError as e:
    st.error(f"Backend API unreachable at {API_URL}: {e}")
    st.stop()

if (
    "session_id" not in st.session_state
):  # runs once per browser session, not on every rerun
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []
session_id = st.session_state.session_id


@st.cache_data(
    show_spinner=False
)  # every rerun redraws the whole history; fetch each image only once
def fetch_image(url: str) -> bytes | None:
    try:
        r = httpx.get(url, timeout=10)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError:
        return None  # a missing figure shouldn't break the answer


def show(message: dict) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message["role"] != "assistant":
            return
        label = message["sources"][0]
        color = (
            "gray"
            if label.endswith("(uncited)")
            else BADGE_COLORS.get(label.split(" + ")[0], "blue")
        )
        st.badge(label, color=color)
        if message["citations"]:
            with st.expander("Sources"):
                for c in message["citations"]:
                    refs = "".join(f"[{n}]" for n in c["refs"])
                    if c["type"] == "Web":
                        st.markdown(f"{refs} [{c['title']}]({c['url']})")
                    else:
                        page = f", p. {c['page']}" if "page" in c else ""
                        st.markdown(f"{refs} **{c['source']}**{page} · {c['section']}")
                        for name in c.get("images", []):
                            if data := fetch_image(
                                f"{API_URL}/images/{c['doc_id']}/{name}"
                            ):
                                st.image(data, caption=f"Figure from {c['source']}")
        st.caption(f"trace {message['trace_id']}")


with st.sidebar:
    st.header("Documents")
    with st.form(
        "upload", clear_on_submit=True
    ):  # a form: the file is sent only on click, not on every rerun
        file = st.file_uploader("PDF or DOCX, up to 20 MB", type=["pdf", "docx"])
        submitted = st.form_submit_button("Upload")
    if submitted and file:
        with st.spinner(
            f"Ingesting {file.name}: parsing, describing images, embedding…"
        ):
            try:
                r = httpx.post(
                    f"{API_URL}/upload",
                    files={"file": (file.name, file.getvalue())},
                    headers={"X-Session-Id": session_id},
                    timeout=UPLOAD_TIMEOUT,
                )
            except httpx.HTTPError as e:
                st.error(f"Upload failed: {e}")
            else:
                body = r.json()
                if not r.is_success:
                    st.error(body.get("detail", "Upload failed"))
                elif body["status"] == "already_ingested":
                    st.info(f"{file.name} is already indexed.")
                else:
                    st.success(f"{file.name}: {body['chunks']} chunks indexed.")
                    if body["failed_images"]:
                        st.warning(
                            f"{len(body['failed_images'])} image(s) could not be described; re-upload to retry."
                        )
    st.caption(f"Session {session_id[:8]}")

for message in st.session_state.messages:
    show(message)

if question := st.chat_input("Ask about your documents"):
    st.session_state.messages.append(
        {"role": "user", "content": question}
    )  # saved first: survives an interrupted run
    show(st.session_state.messages[-1])
    with st.spinner("Searching, grading and writing the answer…"):
        try:
            r = httpx.post(
                f"{API_URL}/chat",
                json={"question": question, "session_id": session_id},
                timeout=CHAT_TIMEOUT,
            )
            r.raise_for_status()
        except httpx.HTTPError as e:
            st.error(f"The assistant could not answer: {e}")
            st.stop()
    body = r.json()
    st.session_state.messages.append(
        {"role": "assistant", "content": body["answer"]} | body
    )
    st.rerun()  # render the new answer through the same history loop as every other message
