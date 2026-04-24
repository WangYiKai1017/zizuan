#!/usr/bin/env python3
"""
验证记忆存储路径修改的脚本（版本2）
检查：
1. MarkdownFileManager是否自动生成随机ID并创建独立目录
2. 主人公信息是否单独存储在people/protagonist.md中
3. 目录结构是否正确创建
"""

import os
import sys
import asyncio
from pathlib import Path
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
from src.models import EventInfo, PersonInfo


async def test_random_id_generation():
    """测试随机ID生成功能"""
    print("=== 测试随机ID生成 ===")
    
    # 创建两个不同的MarkdownFileManager实例
    fm1 = MarkdownFileManager()
    fm2 = MarkdownFileManager()
    
    # 获取它们的路径和ID
    path1 = fm1.base_path
    path2 = fm2.base_path
    id1 = fm1.conversation_id
    id2 = fm2.conversation_id
    
    print(f"实例1: ID={id1}, 路径={path1}")
    print(f"实例2: ID={id2}, 路径={path2}")
    
    # 验证ID不同
    if id1 != id2:
        print("✅ 随机ID生成成功，两个实例的ID不同!")
    else:
        print("❌ 随机ID生成失败，两个实例的ID相同!")
        return False
    
    # 验证路径包含ID
    if id1 in str(path1) and id2 in str(path2):
        print("✅ 存储路径正确包含随机ID!")
    else:
        print("❌ 存储路径不包含随机ID!")
        return False
    
    return True


async def test_protagonist_storage():
    """测试主人公信息存储功能"""
    print("\n=== 测试主人公信息存储 ===")
    
    # 创建MarkdownFileManager实例
    file_manager = MarkdownFileManager()
    memory_repo = MemoryRepository(file_manager)
    
    try:
        # 创建主人公信息
        protagonist = PersonInfo(
            person_id="protagonist_001",
            name="主人公",
            role="protagonist",
            description="这是自传的主人公",
            relation_to_protagonist="自己",
            birth_year="1950年",
            characteristics=["善良", "勤奋", "乐观"],
            influence="",
            quotes=["人生就是一场旅行"]
        )
        
        # 保存主人公
        path = await memory_repo.save_person(protagonist)
        print(f"主人公保存路径: {path}")
        
        # 检查文件是否存在且路径正确
        protagonist_file = file_manager.base_path / "people" / "protagonist.md"
        if protagonist_file.exists():
            print("✅ 主人公信息正确存储在people/protagonist.md!")
            
            # 读取文件内容验证
            content = protagonist_file.read_text(encoding='utf-8')
            if "# 主人公" in content and "1950年" in content:
                print("✅ 主人公信息内容正确!")
            else:
                print("⚠️  主人公信息内容可能不完整!")
            
            return True
        else:
            print("❌ 主人公信息文件不存在!")
            print(f"预期路径: {protagonist_file}")
            return False
    
    except Exception as e:
        print(f"❌ 主人公信息存储过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_other_person_storage():
    """测试其他人物信息存储功能"""
    print("\n=== 测试其他人物信息存储 ===")
    
    # 创建MarkdownFileManager实例
    file_manager = MarkdownFileManager()
    memory_repo = MemoryRepository(file_manager)
    
    try:
        # 创建家庭成员信息
        family_member = PersonInfo(
            person_id="person_001",
            name="父亲",
            role="父亲",
            description="主人公的父亲",
            relation_to_protagonist="父亲",
            birth_year="1920年",
            characteristics=["严厉", "慈爱"],
            influence="对主人公的成长影响很大",
            quotes=["做人要诚实"]
        )
        
        # 保存家庭成员
        path = await memory_repo.save_person(family_member)
        print(f"家庭成员保存路径: {path}")
        
        # 检查文件是否存在且路径正确
        path_obj = Path(path)
        expected_path = file_manager.base_path / "people" / "family" / "父亲.md"
        if path_obj == expected_path:
            print("✅ 其他人物信息正确存储在相应的角色目录!")
            return True
        else:
            print(f"❌ 其他人物信息存储路径不正确!")
            print(f"预期: {expected_path}")
            print(f"实际: {path_obj}")
            return False
    
    except Exception as e:
        print(f"❌ 其他人物信息存储过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_directory_structure():
    """测试目录结构是否正确创建"""
    print("\n=== 测试目录结构 ===")
    
    file_manager = MarkdownFileManager()
    base_path = file_manager.base_path
    
    # 检查主要目录是否存在
    directories_to_check = [
        "events/childhood",
        "events/youth", 
        "events/middle_age",
        "events/elderly",
        "people/family",
        "people/friends",
        "people/colleagues",
        "people/others",
        "timeline",
        "themes"
    ]
    
    all_exist = True
    for dir_path in directories_to_check:
        full_path = base_path / dir_path
        if full_path.exists() and full_path.is_dir():
            print(f"✅ {full_path}")
        else:
            print(f"❌ {full_path}")
            all_exist = False
    
    return all_exist


async def main():
    """主函数"""
    print("记忆存储路径修改验证脚本（版本2）")
    print("=" * 60)
    
    # 测试随机ID生成
    random_id_ok = await test_random_id_generation()
    
    # 测试目录结构
    structure_ok = await test_directory_structure()
    
    # 测试主人公存储
    protagonist_ok = await test_protagonist_storage()
    
    # 测试其他人物存储
    other_person_ok = await test_other_person_storage()
    
    print("\n" + "=" * 60)
    if random_id_ok and structure_ok and protagonist_ok and other_person_ok:
        print("🎉 所有测试通过! 记忆存储路径修改成功!")
        print(f"\n记忆文件将保存在: {Path(os.environ.get('TEMP', '/tmp')) / 'memory'}/{{conversation_id}}")
        print("主人公信息单独存储在: people/protagonist.md")
        return 0
    else:
        print("❌ 部分测试失败，请检查修改!")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))