#!/usr/bin/env python3
"""
集成测试：新用户第一次与Agent对话场景

测试说明：
1. 使用完全空白的知识库路径
2. 在命令行中与Agent进行交互
3. Agent会进行用户信息收集和采访流程
4. 对话结果会保存到指定的知识库路径

使用方法：
$ python3 integration_test_new_user.py

退出方式：
输入 'exit' 或 'quit' 退出测试
输入 'stop' 结束当前对话阶段
"""

import asyncio
import logging
import json
from datetime import datetime
from pathlib import Path

from src.agents import InterviewSessionAgent, SessionPhase
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
from src.services.memory_manager import MemoryManager
from src.services.llm_service import get_llm_service

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 测试配置
TEST_USER_ID = "test_user002"
KNOWLEDGE_BASE_PATH = f"/Users/yikaiwang/Documents/trae_projects/zizhuan/knowledge_base/{TEST_USER_ID}"

async def run_integration_test():
    """运行集成测试"""
    print("=" * 60)
    print("集成测试：新用户第一次与Agent对话")
    print("=" * 60)
    print(f"测试用户ID: {TEST_USER_ID}")
    print(f"知识库路径: {KNOWLEDGE_BASE_PATH}")
    print("=" * 60)
    print()
    
    # 确保知识库路径存在
    Path(KNOWLEDGE_BASE_PATH).mkdir(parents=True, exist_ok=True)
    
    try:
        # 确保日志目录存在
        log_dir = Path(f"/Users/yikaiwang/Documents/trae_projects/zizhuan/knowledge_base/{TEST_USER_ID}/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建日志文件
        log_filename = f"conversation_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"
        log_file_path = log_dir / log_filename
        
        # 1. 初始化组件
        logger.info("正在初始化Agent组件...")
        
        # 创建InterviewSessionAgent（会自动初始化知识库目录）
        llm_service = get_llm_service()
        agent = InterviewSessionAgent(
            user_id=TEST_USER_ID,
            llm_service=llm_service
        )
        
        logger.info("Agent组件初始化完成")
        print()
        
        # 记录到日志文件
        with open(log_file_path, 'a', encoding='utf-8') as log_file:
            log_file.write("Agent组件初始化完成\n\n")
            log_file.write("=== 开始对话 ===\n\n")
        
        # 2. 启动会话
        print("=== 开始对话 ===")
        print()
        
        opening = await agent.start()
        print(f"🤖 Agent: {opening}")
        print()
        
        # 记录开场白到日志文件
        with open(log_file_path, 'a', encoding='utf-8') as log_file:
            log_file.write(f"🤖 Agent: {opening}\n\n")
        
        # 3. 进入对话循环
        conversation_history = [
            {"role": "assistant", "content": opening, "timestamp": datetime.now().isoformat()}
        ]
        
        while True:
            # 获取用户输入
            user_input = input("👤 您: ")
            
            # 记录用户输入到日志文件
            with open(log_file_path, 'a', encoding='utf-8') as log_file:
                log_file.write(f"👤 您: {user_input}\n")
            
            # 检查退出条件
            if user_input.lower() in ['exit', 'quit']:
                print("\n=== 测试结束 ===")
                with open(log_file_path, 'a', encoding='utf-8') as log_file:
                    log_file.write("\n=== 测试结束 ===\n")
                break
            elif user_input.lower() == 'stop':
                print("\n=== 对话阶段结束 ===")
                with open(log_file_path, 'a', encoding='utf-8') as log_file:
                    log_file.write("\n=== 对话阶段结束 ===\n")
                break
            
            # 处理用户输入
            response = await agent.handle_user_input(user_input)
            
            # 记录对话
            conversation_history.append({
                "role": "user", "content": user_input, "timestamp": datetime.now().isoformat()
            })
            conversation_history.append({
                "role": "assistant", "content": response, "timestamp": datetime.now().isoformat()
            })
            
            # 显示Agent响应
            print()
            print(f"🤖 Agent: {response}")
            print()
            
            # 记录Agent响应到日志文件
            with open(log_file_path, 'a', encoding='utf-8') as log_file:
                log_file.write(f"🤖 Agent: {response}\n\n")
            
            # 检查是否完成
            if hasattr(agent, 'phase') and agent.phase == SessionPhase.ENDING:
                print("\n=== 对话已结束 ===")
                print("\n✅ 对话完成！")
                print("程序将自动关闭...")
                
                # 记录对话结束到日志文件
                with open(log_file_path, 'a', encoding='utf-8') as log_file:
                    log_file.write("\n=== 对话已结束 ===\n")
                
                await asyncio.sleep(2)  # 等待2秒，让用户看到提示
                break
        
        # 4. 保存对话历史
        history_file = Path(KNOWLEDGE_BASE_PATH) / f"conversation_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.json"
        with open(history_file, 'w', encoding='utf-8') as f:
            json.dump(conversation_history, f, ensure_ascii=False, indent=2)
        
        print(f"\n对话历史已保存到: {history_file}")
        
        # 5. 显示测试结果
        print("\n" + "=" * 60)
        print("测试结果")
        print("=" * 60)
        print(f"✓ 用户ID: {TEST_USER_ID}")
        print(f"✓ 知识库路径: {KNOWLEDGE_BASE_PATH}")
        print(f"✓ 对话轮次: {len(conversation_history) // 2}")
        print(f"✓ 对话历史已保存")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        print(f"\n❌ 测试失败: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(run_integration_test())