#!/usr/bin/env python3
"""
LLMService 测试入口

可以持久化一个LLMService实例，在终端与大模型进行交互
"""

import os
import sys
import asyncio
import logging
from datetime import datetime

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LLMChat:
    """LLM聊天客户端"""
    
    def __init__(self):
        self.llm_service = None
        self.conversation_history = []
    
    async def initialize(self):
        """初始化LLMService"""
        try:
            from src.services.llm_service import get_llm_service
            from src.config.llm_config import get_default_config
            
            config = get_default_config()
            logger.info(f"使用模型配置: {config.provider}/{config.model_name}")
            logger.info(f"API URL: {config.base_url}")
            
            self.llm_service = get_llm_service()
            logger.info("LLMService初始化成功")
            logger.info(f"已加载 {len(self.llm_service._prompt_templates)} 个Prompt模板")
            for name in self.llm_service._prompt_templates.keys():
                logger.info(f"  - {name}")
            
            return True
        except Exception as e:
            logger.error(f"LLMService初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def chat(self):
        """开始聊天会话"""
        if not self.llm_service:
            logger.error("LLMService未初始化")
            return
        
        print("\n=== LLM 聊天客户端 ===")
        print("输入 'exit' 或 'quit' 退出聊天")
        print("输入 'clear' 清空对话历史")
        print("输入 'stats' 查看调用统计")
        print("输入 'templates' 查看可用模板")
        print("=" * 50)
        
        while True:
            try:
                user_input = input("\n你: ").strip()
                
                if user_input.lower() in ["exit", "quit"]:
                    print("\n再见！")
                    break
                
                if user_input.lower() == "clear":
                    self.conversation_history.clear()
                    print("对话历史已清空")
                    continue
                
                if user_input.lower() == "stats":
                    stats = self.llm_service.get_stats()
                    print("\n=== 调用统计 ===")
                    print(f"总调用次数: {stats['total_calls']}")
                    print(f"总Token数: {stats['total_tokens']}")
                    print(f"成功率: {stats['success_rate']:.2%}")
                    print(f"平均延迟: {stats['avg_latency_ms']:.0f}ms")
                    continue
                
                if user_input.lower() == "templates":
                    print("\n=== 可用Prompt模板 ===")
                    for name in self.llm_service._prompt_templates.keys():
                        template = self.llm_service._prompt_templates[name]
                        print(f"- {name}: {template.description}")
                    continue
                
                if not user_input:
                    continue
                
                # 记录用户输入
                self.conversation_history.append({
                    "role": "user",
                    "content": user_input,
                    "timestamp": datetime.now()
                })
                
                # 使用简单的对话模板
                prompt = self._build_chat_prompt(user_input)
                
                print("\nAI: 正在思考...", end="", flush=True)
                
                # 调用LLM
                result = await self.llm_service.invoke(prompt)
                
                print("\rAI: " + (result.content if result.success else f"错误: {result.error}"))
                
                # 记录AI响应
                if result.success:
                    self.conversation_history.append({
                        "role": "assistant",
                        "content": result.content,
                        "timestamp": datetime.now(),
                        "token_usage": result.token_usage
                    })
                
            except KeyboardInterrupt:
                print("\n\n再见！")
                break
            except Exception as e:
                logger.error(f"聊天时发生错误: {e}")
                print(f"\nAI: 抱歉，发生了错误: {e}")
    
    def _build_chat_prompt(self, user_input: str) -> str:
        """构建聊天Prompt"""
        # 简单的对话历史构建
        history = ""
        if self.conversation_history:
            history_lines = []
            for msg in self.conversation_history[-5:]:  # 只保留最近5轮
                role = "用户" if msg["role"] == "user" else "助手"
                history_lines.append(f"{role}: {msg['content']}")
            history = "\n".join(history_lines) + "\n"
        
        return f"{history}用户: {user_input}\n\n助手: "

async def main():
    """主函数"""
    chat_client = LLMChat()
    
    print("正在初始化LLMService...")
    if not await chat_client.initialize():
        print("初始化失败，无法继续")
        return 1
    
    await chat_client.chat()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))