from langgraph.graph import END, START, StateGraph

from app.agent import nodes
from app.agent.state import RAGState

builder = StateGraph(RAGState)
builder.add_node("guard", nodes.guard)
builder.add_node("retrieve", nodes.retrieve)
builder.add_node("grade", nodes.grade)
builder.add_node("rewrite", nodes.rewrite)
builder.add_node("web_search", nodes.web_search)
builder.add_node("generate", nodes.generate)
builder.add_node("attribute", nodes.attribute)

builder.add_edge(START, "guard")
builder.add_conditional_edges("guard", nodes.after_guard, {"blocked": END, "retrieve": "retrieve"})
builder.add_edge("retrieve", "grade")
builder.add_conditional_edges("grade", nodes.after_grade, ["generate", "web_search", "rewrite"])
builder.add_edge("rewrite", "retrieve")  # the corrective loop; after_grade caps it via retries
builder.add_edge("web_search", "generate")
builder.add_edge("generate", "attribute")
builder.add_edge("attribute", END)

graph = builder.compile()
