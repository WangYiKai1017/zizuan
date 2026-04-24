#!/usr/bin/env python3
"""
记忆存储功能演示脚本
展示新的存储路径结构和主人公单独存储功能
"""

import asyncio
import os
from pathlib import Path
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
from src.models import EventInfo, PersonInfo
from src.enums import PhaseType


async def demo_memory_storage():
    """演示记忆存储功能"""
    print("=== 记忆存储功能演示 ===")
    print("\n1. 创建新的记忆存储实例...")
    
    # 创建MarkdownFileManager实例（自动生成随机ID）
    file_manager = MarkdownFileManager()
    memory_repo = MemoryRepository(file_manager)
    
    print(f"✅ 记忆存储实例创建成功!")
    print(f"   对话ID: {file_manager.conversation_id}")
    print(f"   存储路径: {file_manager.base_path}")
    
    # 2. 存储主人公信息
    print("\n2. 存储主人公信息...")
    protagonist = PersonInfo(
        person_id="protagonist_001",
        name="李小明",
        role="protagonist",
        description="这是自传的主人公，一个平凡而又不平凡的人",
        relation_to_protagonist="自己",
        birth_year="1950年",
        birth_place="北京市",
        characteristics=["善良", "勤奋", "乐观", "坚韧"],
        influence="",
        quotes=["人生就像一场马拉松，重要的不是速度，而是坚持"]
    )
    
    protagonist_path = await memory_repo.save_person(protagonist)
    print(f"✅ 主人公信息存储成功!")
    print(f"   存储路径: {protagonist_path}")
    
    # 3. 存储家庭成员信息
    print("\n3. 存储家庭成员信息...")
    father = PersonInfo(
        person_id="person_001",
        name="李建国",
        role="父亲",
        description="李小明的父亲，一位退休教师",
        relation_to_protagonist="父亲",
        birth_year="1920年",
        characteristics=["严厉", "慈爱", "博学", "严谨"],
        influence="对李小明的学习和人生观产生了深远影响",
        quotes=["知识改变命运", "做人要堂堂正正"]
    )
    
    father_path = await memory_repo.save_person(father)
    print(f"✅ 家庭成员信息存储成功!")
    print(f"   存储路径: {father_path}")
    
    # 4. 存储事件信息
    print("\n4. 存储事件信息...")
    childhood_event = EventInfo(
        event_id="event_001",
        title="童年入学",
        time="1957年9月",
        description="李小明进入北京市第一小学就读，开始了他的学习生涯。在学校里，他表现出了对知识的强烈渴望和好奇心。",
        type="education",
        location="北京市",
        people=["李小明", "李建国"],
        importance="medium"
    )
    
    event_path = await memory_repo.save_event(childhood_event)
    print(f"✅ 事件信息存储成功!")
    print(f"   存储路径: {event_path}")
    
    # 5. 更新时间线
    print("\n5. 更新时间线...")
    await memory_repo.update_timeline(childhood_event)
    print(f"✅ 时间线更新成功!")
    print(f"   时间线文件: {file_manager.base_path / 'timeline' / 'life-events.md'}")
    
    # 6. 展示文件结构
    print("\n6. 生成的文件结构:")
    async def print_directory_tree(path, prefix=""):
        """打印目录树"""
        items = list(path.iterdir())
        items.sort()
        
        for i, item in enumerate(items):
            is_last = i == len(items) - 1
            branch = "└── " if is_last else "├── "
            
            print(f"{prefix}{branch}{item.name}")
            
            if item.is_dir():
                next_prefix = f"{prefix}{'    ' if is_last else '│   '}"
                await print_directory_tree(item, next_prefix)
    
    await print_directory_tree(file_manager.base_path)
    
    print("\n" + "=" * 50)
    print("🎉 演示完成!")
    print(f"\n所有记忆文件已保存到:")
    print(f"   {file_manager.base_path}")
    print("\n您可以在该目录下查看生成的所有markdown文件。")
    print(f"\n主人公信息单独存储在:")
    print(f"   {file_manager.base_path / 'people' / 'protagonist.md'}")


if __name__ == "__main__":
    asyncio.run(demo_memory_storage())