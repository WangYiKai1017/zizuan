from typing import List, Dict, Any
import logging

from src.services.memory_manager import MemoryManager
from src.storage.memory_repository import MemoryRepository

logger = logging.getLogger(__name__)


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
        # 保存会话总结到长期记忆
        self.memory_manager.repository.update_profile(f"conversation_summary_{user_id}", session_summary)
        
        # 将对话记录转换为ConversationTurn对象
        conversation_turns = []
        for i, turn in enumerate(conversation_history):
            # 只处理有实际内容的对话轮次
            if "content" in turn and turn["content"]:
                conversation_turn = {
                    "turn_id": i,
                    "user_input": turn["content"] if turn["role"] == "user" else "",
                    "agent_response": turn["content"] if turn["role"] == "assistant" else "",
                    "timestamp": turn.get("timestamp") or ""
                }
                conversation_turns.append(conversation_turn)
        
        # 如果有对话记录，调用MemoryManager进行组织和保存
        if conversation_turns:
            try:
                # 使用默认的人生阶段（可根据实际情况调整）
                from src.enums import PhaseType
                organized_memory = await self.memory_manager.organize_and_save(
                    conversation_turns,
                    PhaseType.CHILDHOOD  # todo: 默认使用童年阶段，可根据实际情况调整
                )
                logger.info(f"Successfully archived conversation for user {user_id}: {organized_memory}")
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