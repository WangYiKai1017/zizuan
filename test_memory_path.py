#!/usr/bin/env python3
"""
验证记忆存储路径修改的脚本
检查MarkdownFileManager是否正确使用C:\\Users\\MSI\\AppData\\Local\\Temp\\memory\\路径
"""

import os
import sys
from pathlib import Path
from src.storage.markdown_file_manager import MarkdownFileManager
from src.storage.memory_repository import MemoryRepository
from src.models import EventInfo, PersonInfo


def test_default_path():
    """测试默认路径设置"""
    print("=== 测试默认路径设置 ===")
    
    # 初始化MarkdownFileManager，不指定路径
    file_manager = MarkdownFileManager()
    
    # 获取实际路径
    actual_path = file_manager.base_path
    expected_path = Path(os.environ.get("TEMP", "/tmp")) / "memory"
    
    print(f"预期路径: {expected_path}")
    print(f"实际路径: {actual_path}")
    
    # 验证路径
    if actual_path == expected_path:
        print("✅ 默认路径设置正确!")
        return True
    else:
        print("❌ 默认路径设置错误!")
        return False


def test_directory_structure():
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
    
    # 检查索引文件是否存在
    index_path = base_path / "index.md"
    if index_path.exists() and index_path.is_file():
        print(f"✅ {index_path}")
    else:
        print(f"❌ {index_path}")
        all_exist = False
    
    return all_exist


def main():
    """主函数"""
    print("记忆存储路径修改验证脚本")
    print("=" * 50)
    
    # 测试默认路径
    path_ok = test_default_path()
    
    # 测试目录结构
    structure_ok = test_directory_structure()
    
    print("\n" + "=" * 50)
    if path_ok and structure_ok:
        print("🎉 所有测试通过! 记忆存储路径修改成功!")
        print(f"\n记忆文件将保存在: {Path(os.environ.get('TEMP', '/tmp')) / 'memory'}")
        return 0
    else:
        print("❌ 部分测试失败，请检查修改!")
        return 1


if __name__ == "__main__":
    sys.exit(main())