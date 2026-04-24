import pytest
import tempfile
import os
from src.storage.memory_repository import MemoryRepository, LRUCache
from src.storage.markdown_file_manager import MarkdownFileManager
from src.models import EventInfo, PersonInfo


class TestLRUCache:
    def test_put_and_get(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        assert cache.get("a") == 1
    
    def test_capacity(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # a should be evicted
        assert cache.get("a") is None
        assert cache.get("b") == 2
        assert cache.get("c") == 3
    
    def test_update_existing(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("a", 3)  # Update a
        cache.put("c", 4)  # b should be evicted
        assert cache.get("a") == 3
        assert cache.get("b") is None
        assert cache.get("c") == 4
    
    def test_clear(self):
        cache = LRUCache(2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


class TestMemoryRepository:
    @pytest.fixture
    async def repository(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(tmpdir)
            yield MemoryRepository(fm)
    
    @pytest.mark.asyncio
    async def test_save_event(self, repository):
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        path = await repository.save_event(event)
        assert path is not None
        
        # 检查路径组件
        path_components = path.split(os.sep)
        assert "events" in path_components
        assert "测试事件.md" in path_components
        
        # 验证索引更新
        assert "e001" in repository._event_index
        assert repository._event_index["e001"] == event
    
    @pytest.mark.asyncio
    async def test_save_person(self, repository):
        person = PersonInfo(
            person_id="p001",
            name="父亲",
            role="父亲",
            description="测试人物",
        )
        
        path = await repository.save_person(person)
        assert path is not None
        
        # 检查路径组件
        path_components = path.split(os.sep)
        assert "people" in path_components
        assert "family" in path_components
        assert "父亲.md" in path_components
        
        # 验证索引更新
        assert "p001" in repository._profile_index
        assert repository._profile_index["p001"] == person
    
    @pytest.mark.asyncio
    async def test_get_event(self, repository):
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        await repository.save_event(event)
        
        # 测试缓存命中
        cached_event = await repository.get_event("e001")
        assert cached_event == event
        
        # 测试不存在的事件
        non_event = await repository.get_event("e999")
        assert non_event is None
    
    @pytest.mark.asyncio
    async def test_get_person(self, repository):
        person = PersonInfo(
            person_id="p001",
            name="父亲",
            role="父亲",
            description="测试人物",
        )
        
        await repository.save_person(person)
        
        # 测试缓存命中
        cached_person = await repository.get_person("p001")
        assert cached_person == person
        
        # 测试不存在的人物
        non_person = await repository.get_person("p999")
        assert non_person is None
    
    @pytest.mark.asyncio
    async def test_update_timeline(self, repository):
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        await repository.update_timeline(event)
        
        # 验证时间线文件创建
        timeline_content = await repository.file_manager.read_file("timeline/life-events.md")
        assert "1970年" in timeline_content
        assert "测试事件" in timeline_content
    
    def test_short_term_memory(self, repository):
        repository.update_short_term("test", "value")
        assert repository.get_short_term("test") == "value"
        
        # 更新短期记忆
        repository.update_short_term("test", "new_value")
        assert repository.get_short_term("test") == "new_value"
        
        # 获取不存在的短期记忆
        assert repository.get_short_term("nonexistent") is None
    
    def test_history_management(self, repository):
        # 添加历史记录
        for i in range(5):
            repository.add_to_history({"turn": i, "content": f"内容{i}"})
        
        # 验证历史记录
        history = repository.get_history()
        assert len(history) == 5
        assert history[0]["turn"] == 0
        assert history[-1]["turn"] == 4
        
        # 测试获取最近n条记录
        recent = repository.get_history(2)
        assert len(recent) == 2
        assert recent[0]["turn"] == 3
        assert recent[1]["turn"] == 4
        
        # 测试历史记录容量限制
        for i in range(20):
            repository.add_to_history({"turn": i+5, "content": f"内容{i+5}"})
        
        history = repository.get_history()
        assert len(history) == 20  # 达到容量限制
    
    def test_clear_short_term(self, repository):
        repository.update_short_term("test", "value")
        repository.add_to_history({"turn": 0, "content": "test"})
        
        repository.clear_short_term()
        
        assert repository.get_short_term("test") is None
        assert len(repository.get_history()) == 0
    
    @pytest.mark.asyncio
    async def test_query_events(self, repository):
        # 添加测试事件
        event1 = EventInfo(
            event_id="e001",
            title="童年记忆",
            time="1950年",
            description="在农村度过的童年时光",
            type="family"
        )
        
        event2 = EventInfo(
            event_id="e002",
            title="求学经历",
            time="1965年",
            description="在县城读中学",
            type="education"
        )
        
        await repository.save_event(event1)
        await repository.save_event(event2)
        
        # 测试关键词查询
        results = await repository.query_events(keyword="童年")
        assert len(results) == 1
        assert results[0].event_id == "e001"
        
        # 测试类型查询
        results = await repository.query_events(event_type="education")
        assert len(results) == 1
        assert results[0].event_id == "e002"
        
        # 测试无匹配查询
        results = await repository.query_events(keyword="不存在的关键词")
        assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_profile_management(self, repository):
        # 更新画像记忆
        repository.update_profile("birth_year", "1950年")
        repository.update_profile("birth_place", "农村")
        
        # 获取画像记忆
        assert repository.get_profile("birth_year") == "1950年"
        assert repository.get_profile("birth_place") == "农村"
        assert repository.get_profile("nonexistent") is None
    
    @pytest.mark.asyncio
    async def test_get_all_people_and_events(self, repository):
        # 添加测试数据
        event = EventInfo(
            event_id="e001",
            title="童年记忆",
            time="1950年",
            description="测试事件",
        )
        
        person = PersonInfo(
            person_id="p001",
            name="父亲",
            role="父亲",
            description="测试人物",
        )
        
        await repository.save_event(event)
        await repository.save_person(person)
        
        # 获取所有人物和事件
        people = repository.get_all_people()
        events = repository.get_all_events()
        
        assert len(people) == 1
        assert people[0].person_id == "p001"
        assert len(events) == 1
        assert events[0].event_id == "e001"