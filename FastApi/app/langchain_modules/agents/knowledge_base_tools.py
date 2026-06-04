from collections.abc import Callable


def build_knowledge_base_tool(retrieve_text: Callable[[str], str]):
    from langchain_core.tools import Tool

    return Tool(
        name="enterprise_knowledge_base_search",
        description="Search the tenant-scoped enterprise knowledge base and return cited evidence.",
        func=retrieve_text,
    )
