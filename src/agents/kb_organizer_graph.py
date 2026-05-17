"""知识库整理 Agent 的 LangGraph 执行图定义

定义 Plan-Execute-Observe 循环的 StateGraph，
通过条件边实现任务完成判断与循环控制。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.models.kb_organizer_state import KBOrganizerState

if TYPE_CHECKING:
    from src.agents.kb_organizer_agent import KBOrganizerAgent


def build_kb_organizer_graph(agent: "KBOrganizerAgent"):
    """构建知识库整理 Agent 的 LangGraph 执行图

    节点：
    - plan: 获取下一个待执行任务，标记为 IN_PROGRESS
    - execute: 执行当前任务
    - observe: 评估结果并决定下一步

    边：
    - plan -> execute
    - execute -> observe
    - observe -> plan (如果还有未完成任务)
    - observe -> END (如果所有任务完成)

    Args:
        agent: KBOrganizerAgent 实例，提供节点方法

    Returns:
        编译后的 LangGraph 可执行图
    """
    graph = StateGraph(KBOrganizerState)

    # 注册节点
    graph.add_node("plan", agent.plan_node)
    graph.add_node("execute", agent.execute_node)
    graph.add_node("observe", agent.observe_node)

    # 定义边
    graph.set_entry_point("plan")
    graph.add_edge("plan", "execute")
    graph.add_edge("execute", "observe")
    graph.add_conditional_edges(
        "observe",
        agent.should_continue,
        {
            "continue": "plan",
            "end": END,
        },
    )

    return graph.compile()
