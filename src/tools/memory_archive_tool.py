from typing import List, Dict, Any
import logging
from datetime import datetime

from src.services.memory_manager import MemoryManager
from src.storage.memory_repository import MemoryRepository
from src.models import ConversationTurn

logger = logging.getLogger(__name__)


def _target_path_is_forbidden(path: str) -> bool:
    """检查归档目标路径是否包含 /biography 片段"""
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    parts = [p for p in normalized.split("/") if p]
    return "biography" in parts


class MemoryArchiveTool:
    """
    记忆归档工具
    
    职责：
    - 封装MemoryManager的归档操作
    - 提供会话结束后的归档接口
    - 处理初始化阶段的知识库生成
    
    使用场景：
    - ProfileCollectionAgent完成初始化后生成基础知识库
    - InterviewAgent结束对话后归档对话记录
    """
    
    def __init__(self, memory_manager: MemoryManager = None):
        if memory_manager:
            self.memory_manager = memory_manager
        else:
            from src.storage.markdown_file_manager import MarkdownFileManager
            self.memory_manager = MemoryManager(repository=MemoryRepository(file_manager=MarkdownFileManager()))
    
    async def create_user_knowledge_base(
        self,
        user_id: str,
        conversation_history: List[Dict],
        profile_info: Dict[str, Any]
    ):
        """
        创建用户基础知识库

        Args:
            user_id: 用户ID
            conversation_history: 初始化阶段的对话记录
            profile_info: 收集到的用户画像信息
        """
        # 安全边界：禁止向 /biography 路径写入
        if _target_path_is_forbidden(user_id):
            logger.warning(f"Blocked create_user_knowledge_base: user_id contains forbidden path segment: {user_id}")
            return

        # 保存用户画像信息
        for key, value in profile_info.items():
            self.memory_manager.repository.update_profile(f"user_{user_id}_{key}", value)
        
        # 简化实现：将对话记录保存到短期记忆
        for i, turn in enumerate(conversation_history):
            self.memory_manager.add_conversation_turn({
                "user_id": user_id,
                "turn_id": i,
                "content": turn,
                "timestamp": turn.get("timestamp")
            })
        
        # 创建/更新 user.md 和 summary_index.md
        try:
            file_manager = self.memory_manager.repository.file_manager
            file_manager.create_or_update_user_md(profile_info)
            file_manager.create_or_update_summary_index()
        except Exception as e:
            logger.warning(f"Failed to generate user.md / summary_index.md: {e}")

        logger.info(f"Created knowledge base for user {user_id}")
        
    
    async def archive_conversation(
        self,
        user_id: str,
        conversation_history: List[Dict],
        session_summary: str
    ):
        """
        归档对话记录

        Args:
            user_id: 用户ID
            conversation_history: 完整的对话记录
            session_summary: 会话总结
        """
        # 安全边界：禁止向 /biography 路径写入
        if _target_path_is_forbidden(user_id):
            logger.warning(f"Blocked archive_conversation: user_id contains forbidden path segment: {user_id}")
            return None

        # 保存会话总结到长期记忆
        self.memory_manager.repository.update_profile(f"conversation_summary_{user_id}", session_summary)
        
        # 将对话记录转换为ConversationTurn对象
        conversation_turns = []
        for i, turn in enumerate(conversation_history):
            # 只以用户输入作为一轮对话的起点，并附带下一条助手回复。
            if turn.get("role") != "user" or not turn.get("content"):
                continue

            agent_response = ""
            if i + 1 < len(conversation_history):
                next_turn = conversation_history[i + 1]
                if next_turn.get("role") == "assistant":
                    agent_response = next_turn.get("content") or ""

            timestamp = turn.get("timestamp")
            if isinstance(timestamp, str) and timestamp:
                try:
                    timestamp = datetime.fromisoformat(timestamp)
                except ValueError:
                    timestamp = datetime.now()
            elif not isinstance(timestamp, datetime):
                timestamp = datetime.now()

            conversation_turns.append(ConversationTurn(
                turn_id=len(conversation_turns),
                user_input=turn["content"],
                agent_response=agent_response,
                timestamp=timestamp,
            ))
        
        # 如果有对话记录，调用MemoryManager进行组织和保存
        organized_memory = None
        if conversation_turns:
            try:
                # 使用默认的人生阶段（可根据实际情况调整）
                from src.enums import PhaseType
                organized_memory = await self.memory_manager.organize_and_save(
                    conversation_turns,
                    PhaseType.CHILDHOOD  # todo: 默认使用童年阶段，可根据实际情况调整
                )
                logger.info(f"Successfully archived conversation for user {user_id}: {organized_memory}")

                # Update user.md if new personal info was discovered
                try:
                    file_manager = self.memory_manager.repository.file_manager
                    if organized_memory and organized_memory.profile_updates:
                        protagonist = organized_memory.profile_updates.protagonist
                        if protagonist:
                            updates = {}
                            if protagonist.birth_place:
                                updates["supplementary"] = f"出生地: {protagonist.birth_place}"
                            if updates:
                                file_manager.create_or_update_user_md(updates)
                    # Regenerate summary index with new content
                    file_manager.create_or_update_summary_index()
                except Exception as e:
                    logger.warning(f"Failed to update user.md / summary_index.md after archive: {e}")

            except Exception as e:
                logger.error(f"Failed to organize and save conversation: {e}")
                # 如果组织失败，至少保存原始对话记录
                for i, turn in enumerate(conversation_history):
                    self.memory_manager.add_conversation_turn({
                        "user_id": user_id,
                        "turn_id": i,
                        "content": turn,
                        "timestamp": turn.get("timestamp")
                    })
        
        logger.info(f"Archived conversation for user {user_id}")
        return organized_memory

    async def create_session_archive(self, user_id: str, session_data: dict) -> str:
        """
        创建采访记录归档文件并更新索引。

        Args:
            user_id: 用户ID
            session_data: 采访记录数据字典

        Returns:
            创建的文件路径
        """
        if _target_path_is_forbidden(user_id):
            logger.warning(f"Blocked create_session_archive: user_id contains forbidden path segment: {user_id}")
            return ""

        file_manager = self.memory_manager.repository.file_manager
        path = file_manager.create_session_archive(session_data)

        # Update summary index to include the new session archive
        try:
            file_manager.create_or_update_summary_index()
        except Exception as e:
            logger.warning(f"Failed to update summary_index after session archive: {e}")

        logger.info(f"Created session archive for user {user_id}: {path}")
        return path
