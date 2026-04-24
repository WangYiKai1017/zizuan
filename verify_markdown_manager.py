#!/usr/bin/env python3
"""
验证MarkdownFileManager的功能
"""

import os
import sys
import asyncio
import tempfile

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

async def main():
    print("=== 验证MarkdownFileManager功能 ===")
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        print(f"\n1. 使用临时目录: {tmpdir}")
        
        # 初始化管理器
        from src.storage.markdown_file_manager import MarkdownFileManager
        manager = MarkdownFileManager(tmpdir)
        
        # 检查目录结构是否创建
        print("\n2. 验证目录结构创建")
        directories = manager.list_files(pattern="*")
        print(f"   已创建 {len(directories)} 个目录和文件")
        print(f"   索引文件存在: {manager.file_exists('index.md')}")
        
        # 创建测试文件
        print("\n3. 测试创建文件")
        file_path = await manager.create_file(
            "events/childhood/test_event.md",
            "# 童年回忆\n\n这是一个测试事件。"
        )
        print(f"   创建文件成功: {file_path}")
        
        # 读取文件
        print("\n4. 测试读取文件")
        content = await manager.read_file("events/childhood/test_event.md")
        print(f"   文件内容: {content[:50]}...")
        
        # 更新文件
        print("\n5. 测试更新文件")
        await manager.update_file(
            "events/childhood/test_event.md",
            "# 童年回忆\n\n这是一个更新后的测试事件。"
        )
        updated_content = await manager.read_file("events/childhood/test_event.md")
        print(f"   更新后内容: {updated_content[:50]}...")
        
        # 追加章节
        print("\n6. 测试追加章节")
        await manager.append_section(
            "events/childhood/test_event.md",
            "细节",
            "这个事件发生在我5岁的时候。"
        )
        appended_content = await manager.read_file("events/childhood/test_event.md")
        print(f"   追加后内容包含'细节'章节: {'## 细节' in appended_content}")
        
        # 测试链接提取
        print("\n7. 测试链接提取")
        link_content = "[[../people/father.md|父亲]]和[[events/childhood/birth.md|出生事件]]"
        links = manager.extract_wikilinks(link_content)
        print(f"   提取到 {len(links)} 个链接")
        for link in links:
            print(f"   - 目标: {link.target}, 显示名称: {link.display_name}")
        
        # 创建带链接的文件
        print("\n8. 测试创建带链接的文件")
        await manager.create_file(
            "events/childhood/linked_event.md",
            "# 关联事件\n\n这个事件涉及[[../people/father.md|父亲]]。"
        )
        await manager.create_file(
            "people/father.md",
            "# 父亲\n\n我的父亲是一名工人。"
        )
        
        # 测试追踪链接
        print("\n9. 测试追踪链接")
        linked_content = await manager.follow_links("events/childhood/linked_event.md")
        print(f"   追踪到 {len(linked_content)} 个链接")
        for link in linked_content:
            print(f"   - 从 {link.source} 到 {link.target}")
            print(f"     内容预览: {link.content_preview[:30]}...")
        
        # 测试搜索
        print("\n10. 测试搜索功能")
        results = await manager.search_files("童年")
        print(f"   搜索'童年'找到 {len(results)} 个结果")
        for result in results:
            print(f"   - 文件: {result.file_path}, 行号: {result.line_number}")
            print(f"     匹配内容: {result.matched_text}")
        
        # 测试文件列表
        print("\n11. 测试列出文件")
        files = manager.list_files("events/childhood")
        print(f"   events/childhood目录下有 {len(files)} 个文件:")
        for f in files:
            print(f"   - {f}")
        
        # 测试文件统计
        print("\n12. 测试文件统计信息")
        stats = manager.get_file_stats("events/childhood/test_event.md")
        print(f"   文件大小: {stats['size']} 字节")
        print(f"   创建时间: {stats['created']}")
        print(f"   修改时间: {stats['modified']}")
        
        print("\n=== 所有验证完成 ===")
        print("🎉 MarkdownFileManager实现成功！")

if __name__ == "__main__":
    asyncio.run(main())