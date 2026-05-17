"""大纲规划 Agent 的 LangGraph 执行图定义

定义线性执行流程的 StateGraph:
scan_kb -> analyze_materials -> generate_outline -> diff_and_update -> END
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph

from src.models.biography_outline_state import OutlineAgentState

if TYPE_CHECKING:
    from src.agents.biography_outline_agent import BiographyOutlineAgent


def build_biography_outline_graph(agent: "BiographyOutlineAgent"):
    """构建大纲规划 Agent 的 LangGraph 执行图

    节点:
    - scan_kb: 扫描知识库材料，检测变更
    - analyze_materials: LLM 分析材料，提取主题/弧线/关系
    - generate_outline: LLM 生成章节大纲
    - diff_and_update: 对比已有大纲，写入文件

    边:
    - scan_kb -> should_continue_after_scan (conditional)
    - analyze_materials -> generate_outline
    - generate_outline -> diff_and_update
    - diff_and_update -> END
    """
    graph = StateGraph(OutlineAgentState)

    # 注册节点
    graph.add_node("scan_kb", agent.scan_kb_node)
    graph.add_node("analyze_materials", agent.analyze_materials_node)
    graph.add_node("generate_outline", agent.generate_outline_node)
    graph.add_node("diff_and_update", agent.diff_and_update_node)

    # 定义边
    graph.set_entry_point("scan_kb")

    # scan_kb之后检查是否有变更，无变更则直接结束
    graph.add_conditional_edges(
        "scan_kb",
        agent.should_continue_after_scan,
        {
            "continue": "analyze_materials",
            "end": END,
        },
    )

    graph.add_edge("analyze_materials", "generate_outline")
    graph.add_edge("generate_outline", "diff_and_update")
    graph.add_edge("diff_and_update", END)

    return graph.compile()
