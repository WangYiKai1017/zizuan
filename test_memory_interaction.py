#!/usr/bin/env python3
"""
Memory Manager 交互式测试脚本
让用户可以输入采访内容，并通过 MemoryManager 将其提炼成结构化记忆存储
"""

import asyncio
import tempfile
import os, sys, logging
from datetime import datetime
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
from src.services.memory_manager import MemoryManager
from src.models import ConversationTurn
from src.enums import PhaseType
from src.services.llm_service import get_llm_service

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv()

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def main():
    print("=== Memory Manager 交互式测试 ===")
    print("这个脚本将帮助您测试 MemoryManager 的功能。")
    print("您可以输入采访内容，系统会自动将其提炼并存储为结构化记忆。\n")
    
    # 1. 初始化组件
    try:
        # 使用默认临时目录作为存储（C:\Users\MSI\AppData\Local\Temp\memory\）
        file_manager = MarkdownFileManager()
        repository = MemoryRepository(file_manager)
        llm_service = get_llm_service()
        memory_manager = MemoryManager(repository, llm_service)
        
        print(f"\n存储目录: {file_manager.base_path}")
        print("\n✅ 组件初始化成功!")
        print("\n当前人生阶段: 童年时期")
        print(f"\n当前prompt列表：{llm_service._prompt_templates.keys()}")
        
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return
    
    # 2. 设置当前人生阶段
    phase_options = {
        "1": PhaseType.CHILDHOOD,
        "2": PhaseType.YOUTH,
        "3": PhaseType.MIDDLE_AGE,
        "4": PhaseType.ELDERLY
    }
    
    print("\n请选择当前采访的人生阶段:")
    print("1. 童年时期")
    print("2. 少年时期")
    print("3. 中年时期")
    print("4. 老年时期")
    
    phase_choice = input("输入选项 (1-4): ")
    if phase_choice not in phase_options:
        print("无效选择，默认使用童年时期")
        current_phase = PhaseType.CHILDHOOD
    else:
        current_phase = phase_options[phase_choice]
    
    print(f"当前人生阶段: {current_phase}")
    
    # 3. 开始交互式输入
    print("\n=== 开始采访 ===")
    print("输入 'exit' 结束采访")
    print("输入 'history' 查看历史记录")
    print("输入 'clear' 清空历史记录")
    
    conversation_turns = []
    turn_id = 1
    
    while True:
        try:
            # 获取用户输入
            user_input = input("\n用户: ")
            
            if user_input.strip().lower() == "exit":
                print("结束采访...")
                break
                
            elif user_input.strip().lower() == "history":
                print("\n=== 历史记录 ===")
                if not conversation_turns:
                    print("暂无历史记录")
                else:
                    for turn in conversation_turns:
                        print(f"轮次 {turn.turn_id}: {turn.user_input[:50]}...")
                continue
                
            elif user_input.strip().lower() == "clear":
                conversation_turns = []
                turn_id = 1
                memory_manager.clear_session()
                print("历史记录已清空")
                continue
            
            # 创建对话轮次
            turn = ConversationTurn(
                turn_id=turn_id,
                user_input=user_input,
                timestamp=datetime.now()
            )
            
            conversation_turns.append(turn)
            turn_id += 1
            
            # 添加到短期记忆
            memory_manager.add_conversation_turn(turn.dict())
            print(f"已添加到短期记忆: {turn.user_input[:50]}...")
            
            # 调用 MemoryManager 处理
            print("\n🔄 正在处理采访内容...")
            organized_memory = await memory_manager.organize_and_save(
                conversation_turns[-5:],  # 只传递最近5轮对话
                current_phase
            )
            
            # 显示处理结果
            print("\n✅ 内容处理完成!")
            
            if organized_memory.events:
                print(f"\n📅 提取的事件 ({len(organized_memory.events)}个):")
                for event in organized_memory.events:
                    print(f"   - {event.title} ({event.time})")
                    if event.description:
                        print(f"     {event.description[:100]}...")
            
            if organized_memory.people:
                print(f"\n👤 提取的人物 ({len(organized_memory.people)}个):")
                for person in organized_memory.people:
                    print(f"   - {person.name} ({person.relation})")
                    if person.description:
                        print(f"     {person.description[:100]}...")
            
            if organized_memory.profile_updates:
                print("\n👤 人物画像更新:")
                if organized_memory.profile_updates.protagonist:
                    protag = organized_memory.profile_updates.protagonist
                    if protag.birth_year:
                        print(f"   - 出生年份: {protag.birth_year}")
                    if protag.birth_place:
                        print(f"   - 出生地: {protag.birth_place}")
                    if protag.personality_traits:
                        print(f"   - 性格特点: {', '.join(protag.personality_traits[:3])}...")
            
            print("\n📁 所有内容已保存到:")
            print(f"   - 时间线: {os.path.join(file_manager.base_path, 'timeline', 'life-events.md')}")
            print(f"   - 事件: {os.path.join(file_manager.base_path, 'events')}")
            print(f"   - 人物: {os.path.join(file_manager.base_path, 'people')}")
            
        except Exception as e:
            print(f"\n❌ 处理失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 4. 显示最终结果
    print("\n=== 采访结束 ===")
    print(f"总共处理了 {len(conversation_turns)} 轮对话")
    print(f"记忆文件保存在: {file_manager.base_path}")
    print("您可以在该目录下查看生成的markdown文件")
    
    # 清理资源
    print("\n按 Enter 键退出...")
    input()


if __name__ == "__main__":
    asyncio.run(main())