"""传记写作 Agent 的 LangGraph 执行图定义

定义循环写作流程的 StateGraph:
load_tasks -> gather_materials -> write_chapter -> review_and_save -> should_continue
                ^                                                          |
                |__________________________________________________________|
                              (more chapters to write -> loop back)
                                         |
                                    merge_biography -> END
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.models.biography_writing_state import WritingAgentState

if TYPE_CHECKING:
    from src.agents.biography_writing_agent import BiographyWritingAgent


def build_biography_writing_graph(agent: "BiographyWritingAgent"):
    """构建传记写作 Agent 的 LangGraph 执行图"""
    graph = StateGraph(WritingAgentState)

    # 注册节点
    graph.add_node("load_tasks", agent.load_tasks_node)
    graph.add_node("gather_materials", agent.gather_materials_node)
    graph.add_node("write_chapter", agent.write_chapter_node)
    graph.add_node("review_and_save", agent.review_and_save_node)
    graph.add_node("merge_biography", agent.merge_biography_node)

    # 定义边
    graph.set_entry_point("load_tasks")

    # load_tasks -> check if there are tasks
    graph.add_conditional_edges(
        "load_tasks",
        agent.should_continue_after_load,
        {
            "continue": "gather_materials",
            "end": END,  # No confirmed chapters to write
        },
    )

    graph.add_edge("gather_materials", "write_chapter")
    graph.add_edge("write_chapter", "review_and_save")

    # After review_and_save, check if more chapters
    graph.add_conditional_edges(
        "review_and_save",
        agent.should_continue,
        {
            "continue": "gather_materials",  # Loop back for next chapter
            "merge": "merge_biography",  # All done, merge
        },
    )

    graph.add_edge("merge_biography", END)

    return graph.compile()
