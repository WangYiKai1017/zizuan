import pytest
from unittest.mock import AsyncMock, patch
import tempfile
from datetime import datetime

from src.services.memory_manager import LifePhaseResolutionError, MemoryManager
from src.services.llm_service import LLMCallResult
from src.storage.memory_repository import MemoryRepository
from src.storage.markdown_file_manager import MarkdownFileManager
from src.models import (
    EventInfo, PersonInfo, SummaryContent, ExtractedInfo,
    ConversationTurn, OrganizedMemory, EventExtract, PersonExtract,
    ProfileUpdates, ProtagonistUpdate
)
from src.models.organized_memory import (
    EventLifePhaseResolution,
    EventType,
    Importance,
    RelationType,
    InfluenceLevel,
)
from src.enums import PhaseType


class TestMemoryManager:
    @pytest.fixture
    async def memory_manager(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fm = MarkdownFileManager(tmpdir)
            repository = MemoryRepository(fm)
            
            # 创建带有mock的LLMService
            with patch('src.services.llm_service.get_llm_service') as mock_get_llm:
                mock_llm = AsyncMock()
                mock_get_llm.return_value = mock_llm
                
                yield MemoryManager(repository, llm_service=mock_llm)
    
    @pytest.mark.asyncio
    async def test_organize_and_save(self, memory_manager):
        # 创建测试数据
        turns = [
            ConversationTurn(
                user_input="我记得小时候住在一个小院子里。",
                agent_response="那是怎样的院子呢？",
                timestamp=datetime.now(),
                turn_id=1
            ),
            ConversationTurn(
                user_input="院子不大，但种了一棵枣树。",
                timestamp=datetime.now(),
                turn_id=2
            )
        ]
        
        # 创建模拟的OrganizedMemory
        organized_memory = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_001",
                    title="童年小院生活",
                    time="童年时期",
                    life_phase="childhood",
                    location="家中院子",
                    event_type=EventType.FAMILY,
                    importance=Importance.NORMAL,
                    description="用户童年住在有枣树的小院子里",
                    participants=["ppl_father_001"],
                    emotions=["温馨"],
                    source_turns=[1, 2],
                    confidence=0.9
                )
            ],
            people=[
                PersonExtract(
                    person_id="ppl_father_001",
                    name="父亲",
                    relation="父亲",
                    relation_type=RelationType.FAMILY,
                    first_appear_time="童年时期",
                    description="用户的父亲",
                    personality="关爱孩子",
                    influence_level=InfluenceLevel.HIGH,
                    source_turns=[1]
                )
            ],
            profile_updates=ProfileUpdates(
                protagonist=ProtagonistUpdate(
                    birth_year="1950年",
                    personality_traits=["怀旧"]
                )
            )
        )
        
        # 设置mock返回值
        memory_manager.llm_service.invoke_structured.return_value = (organized_memory, None)
        
        # 执行测试
        result = await memory_manager.organize_and_save(turns, PhaseType.CHILDHOOD)
        
        # 验证结果
        assert result == organized_memory
        assert memory_manager.llm_service.invoke_structured.called
        assert memory_manager.llm_service.invoke_structured.call_args.kwargs["max_tokens"] >= 8192
        assert memory_manager.repository.get_profile("birth_year") == "1950年"

    @pytest.mark.asyncio
    async def test_organize_and_save_retries_in_batches_after_truncated_json(self, memory_manager):
        turns = [
            ConversationTurn(
                user_input="1956年我搬到绍兴乡下老屋。",
                agent_response="那老屋是什么样的？",
                timestamp=datetime.now(),
                turn_id=1,
            ),
            ConversationTurn(
                user_input="1958年父亲骑车带我去看露天电影。",
                agent_response="那一定很难忘。",
                timestamp=datetime.now(),
                turn_id=2,
            ),
        ]
        first_batch = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_1956",
                    title="搬到绍兴乡下老屋",
                    time="1956年",
                    life_phase="childhood",
                    location="绍兴",
                    event_type=EventType.MIGRATION,
                    importance=Importance.NORMAL,
                    description="用户1956年搬到绍兴乡下老屋。",
                    confidence=0.9,
                )
            ]
        )
        second_batch = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_1958",
                    title="父亲骑车带去看露天电影",
                    time="1958年",
                    life_phase="childhood",
                    location="镇上",
                    event_type=EventType.FAMILY,
                    importance=Importance.NORMAL,
                    description="父亲骑自行车带用户去镇上看露天电影。",
                    confidence=0.9,
                )
            ]
        )
        memory_manager.llm_service.invoke_structured.side_effect = [
            (
                None,
                LLMCallResult(
                    success=False,
                    error="Parse error: Unterminated string starting at: line 10 column 2",
                ),
            ),
            (first_batch, LLMCallResult(success=True, content="{}")),
            (second_batch, LLMCallResult(success=True, content="{}")),
        ]

        result = await memory_manager.organize_and_save(turns, PhaseType.CHILDHOOD)

        assert len(result.events) == 2
        assert memory_manager.llm_service.invoke_structured.await_count == 3
        assert len(memory_manager.repository.get_all_events()) == 2

    @pytest.mark.asyncio
    async def test_event_life_phase_alias_controls_event_path(self, memory_manager):
        turns = [
            ConversationTurn(
                user_input="我大概6到12岁是在芳草地小学读书。",
                agent_response="那所学校给您留下了什么印象？",
                timestamp=datetime.now(),
                turn_id=1,
            )
        ]
        organized_memory = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_p001",
                    title="小学就读芳草地",
                    time="约6-12岁",
                    life_phase="童年时期",
                    location="芳草地小学",
                    event_type=EventType.EDUCATION,
                    importance=Importance.NORMAL,
                    description="用户小学阶段就读芳草地小学。",
                    confidence=0.9,
                )
            ]
        )
        memory_manager.llm_service.invoke_structured.return_value = (organized_memory, None)

        await memory_manager.organize_and_save(turns, PhaseType.CHILDHOOD)

        event_path = memory_manager.repository.file_manager.base_path / "events" / "childhood" / "小学就读芳草地.md"
        assert event_path.exists()
        assert not (memory_manager.repository.file_manager.base_path / "events" / "elderly" / "小学就读芳草地.md").exists()

    @pytest.mark.asyncio
    async def test_event_life_phase_resolution_uses_llm_for_unmapped_value(self, memory_manager):
        turns = [
            ConversationTurn(
                user_input="我刚开始工作时去了第一家工厂。",
                agent_response="那是怎样的开始？",
                timestamp=datetime.now(),
                turn_id=1,
            )
        ]
        organized_memory = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_work_001",
                    title="进入第一家工厂",
                    time="成年后",
                    life_phase="青年时期",
                    location="工厂",
                    event_type=EventType.CAREER,
                    importance=Importance.IMPORTANT,
                    description="用户成年后进入第一家工厂工作。",
                    confidence=0.85,
                )
            ]
        )
        memory_manager.llm_service.invoke_structured.side_effect = [
            (organized_memory, LLMCallResult(success=True, content="{}")),
            (EventLifePhaseResolution(life_phase="middle_age", reason="成年后的工作经历"), LLMCallResult(success=True, content="{}")),
        ]

        await memory_manager.organize_and_save(turns, PhaseType.CHILDHOOD)

        event_path = memory_manager.repository.file_manager.base_path / "events" / "middle_age" / "进入第一家工厂.md"
        assert event_path.exists()
        assert memory_manager.llm_service.invoke_structured.await_count == 2
        assert memory_manager.llm_service.invoke_structured.call_args.kwargs["trace_node"] == "memory_organization.event_life_phase_resolution"

    @pytest.mark.asyncio
    async def test_event_life_phase_resolution_failure_does_not_persist_events(self, memory_manager):
        turns = [
            ConversationTurn(
                user_input="那是一段说不清时间的经历。",
                agent_response="您还记得大概是人生哪个阶段吗？",
                timestamp=datetime.now(),
                turn_id=1,
            )
        ]
        organized_memory = OrganizedMemory(
            events=[
                EventExtract(
                    event_id="evt_unknown_001",
                    title="无法定位阶段的经历",
                    time="不详",
                    life_phase="无法判断",
                    location="",
                    event_type=EventType.OTHER,
                    importance=Importance.NORMAL,
                    description="用户讲述了一段无法定位阶段的经历。",
                    confidence=0.5,
                )
            ]
        )
        memory_manager.llm_service.invoke_structured.side_effect = [
            (organized_memory, LLMCallResult(success=True, content="{}")),
            (None, LLMCallResult(success=False, error="Parse error: invalid life_phase")),
        ]

        with pytest.raises(LifePhaseResolutionError):
            await memory_manager.organize_and_save(turns, PhaseType.CHILDHOOD)

        assert memory_manager.repository.get_all_events() == []
        assert not any((memory_manager.repository.file_manager.base_path / "events").rglob("无法定位阶段的经历.md"))
    
    @pytest.mark.asyncio
    async def test_apply_summary(self, memory_manager):
        # 创建测试数据
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
            type="family"
        )
        
        person = PersonInfo(
            person_id="p001",
            name="父亲",
            role="父亲",
            description="测试人物",
        )
        
        extracted_info = ExtractedInfo(
            events=[event],
            people=[person],
            time_markers=[],
            themes=[]
        )
        
        summary = SummaryContent(
            summary_id="sum_001",
            session_id="session_001",
            turn_range=(1, 2),
            memory_updates={},
            extracted_info=extracted_info,
            generated_questions=[],
            emotion_summary=None,
            confidence_scores=None
        )
        
        # 模拟repository的save_event和save_person方法
        memory_manager.repository.save_event = AsyncMock(return_value="events/test.md")
        memory_manager.repository.save_person = AsyncMock(return_value="people/test.md")
        memory_manager.repository.update_timeline = AsyncMock()
        
        # 执行测试
        result = await memory_manager.apply_summary(summary)
        
        # 验证结果
        assert result["events_saved"] == 1
        assert result["people_saved"] == 1
        assert len(result["files_created"]) == 2
        
        # 验证方法调用
        memory_manager.repository.save_event.assert_called_once_with(event)
        memory_manager.repository.save_person.assert_called_once_with(person)
        memory_manager.repository.update_timeline.assert_called_once_with(event)
    
    def test_short_term_memory_management(self, memory_manager):
        # 测试短期记忆更新
        memory_manager.update_short_term("test_key", "test_value")
        assert memory_manager.get_short_term("test_key") == "test_value"
        
        # 测试添加对话轮次
        memory_manager.add_conversation_turn({"turn": 1, "content": "test"})
        history = memory_manager.get_recent_conversations()
        assert len(history) == 1
        assert history[0]["turn"] == 1
        
        # 测试获取最近对话
        recent = memory_manager.get_recent_conversations(1)
        assert len(recent) == 1
    
    @pytest.mark.asyncio
    async def test_query_events(self, memory_manager):
        # 创建测试事件
        event = EventInfo(
            event_id="e001",
            title="童年记忆",
            time="1950年",
            description="测试事件",
            type="family"
        )
        
        # 模拟repository的query_events方法
        memory_manager.repository.query_events = AsyncMock(return_value=[event])
        
        # 执行测试
        results = await memory_manager.query_events(keyword="童年")
        
        # 验证结果
        assert len(results) == 1
        assert results[0] == event
        memory_manager.repository.query_events.assert_called_once_with(keyword="童年", time_range=None, event_type=None)
    
    def test_clear_session(self, memory_manager):
        # 添加一些短期记忆
        memory_manager.update_short_term("test", "value")
        memory_manager.add_conversation_turn({"turn": 1, "content": "test"})
        
        # 清空会话
        memory_manager.clear_session()
        
        # 验证短期记忆被清空
        assert memory_manager.get_short_term("test") is None
        assert len(memory_manager.get_recent_conversations()) == 0
    
    @pytest.mark.asyncio
    async def test_get_event(self, memory_manager):
        # 创建测试事件
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        # 模拟repository的get_event方法
        memory_manager.repository.get_event = AsyncMock(return_value=event)
        
        # 执行测试
        result = await memory_manager.get_event("e001")
        
        # 验证结果
        assert result == event
        memory_manager.repository.get_event.assert_called_once_with("e001")
    
    def test_get_all_people_and_events(self, memory_manager):
        # 创建测试数据
        event = EventInfo(
            event_id="e001",
            title="测试事件",
            time="1970年",
            description="这是一个测试事件",
        )
        
        person = PersonInfo(
            person_id="p001",
            name="父亲",
            role="父亲",
            description="测试人物",
        )
        
        # 模拟repository的方法
        memory_manager.repository.get_all_people = lambda: [person]
        memory_manager.repository.get_all_events = lambda: [event]
        
        # 执行测试
        people = memory_manager.get_all_people()
        events = memory_manager.get_all_events()
        
        # 验证结果
        assert len(people) == 1
        assert people[0] == person
        assert len(events) == 1
        assert events[0] == event
