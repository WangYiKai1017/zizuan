# test_system_assembly.py
# 系统组装层测试脚本

import asyncio
import logging
import os
from dotenv import load_dotenv

from src.core.conversation_orchestrator import ConversationOrchestrator
from src.config.llm_config import LLMConfig
from src.enums import StateType

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_conversation_orchestrator():
    """测试对话主控器的基本功能"""
    logger.info("开始测试对话主控器")
    
    try:
        # 从环境变量创建LLM配置
        llm_config = LLMConfig.from_env()
        
        # 初始化对话主控器
        orchestrator = ConversationOrchestrator(
            llm_config=llm_config,
            memory_base_path="C:\\Users\\MSI\\AppData\\Local\\Temp\\memory"
        )
        
        # 初始化会话
        user_profile = {"name": "测试用户"}
        session = await orchestrator.initialize_session(user_profile)
        logger.info(f"会话初始化成功: {session.session_id}")
        
        # 测试用户输入1
        user_input1 = "我是李明，今年78岁了"
        logger.info(f"用户输入: {user_input1}")
        
        response1 = await orchestrator.process_turn(user_input1)
        logger.info(f"助手响应: {response1.message}")
        logger.info(f"状态更新: {response1.state_update}")
        
        # 测试用户输入2
        user_input2 = "我以前是一名教师，教了40年书"
        logger.info(f"用户输入: {user_input2}")
        
        response2 = await orchestrator.process_turn(user_input2)
        logger.info(f"助手响应: {response2.message}")
        logger.info(f"状态更新: {response2.state_update}")
        
        # 测试用户输入3
        user_input3 = "我是1945年出生在上海的"
        logger.info(f"用户输入: {user_input3}")
        
        response3 = await orchestrator.process_turn(user_input3)
        logger.info(f"助手响应: {response3.message}")
        logger.info(f"状态更新: {response3.state_update}")
        
        # 终止会话
        handoff = await orchestrator.terminate_session()
        logger.info(f"会话终止成功")
        logger.info(f"交接包ID: {handoff.handoff_id}")
        logger.info(f"收集事件数: {len(handoff.collected_data.events)}")
        logger.info(f"收集人物数: {len(handoff.collected_data.people)}")
        
        logger.info("对话主控器测试完成")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_content_summarizer():
    """测试内容归纳服务"""
    logger.info("开始测试内容归纳服务")
    
    try:
        from src.services.content_summarizer import ContentSummarizer
        from src.services.llm_service import LLMService
        
        # 从环境变量创建LLM配置
        llm_config = LLMConfig.from_env()
        llm_service = LLMService(llm_config)
        
        # 初始化内容归纳服务
        summarizer = ContentSummarizer(llm_service=llm_service)
        
        # 测试内容归纳
        user_input = "我1945年出生在上海，1968年毕业于北京大学，之后在一所中学当老师，教了40年书直到2008年退休"
        summary = await summarizer.summarize_async(user_input, 1, "test_session_001")
        
        if summary:
            logger.info(f"内容归纳成功")
            logger.info(f"摘要ID: {summary.summary_id}")
            logger.info(f"提取事件数: {len(summary.extracted_info.events)}")
            logger.info(f"提取人物数: {len(summary.extracted_info.people)}")
            
            if summary.extracted_info.events:
                for event in summary.extracted_info.events:
                    logger.info(f"事件: {event.title} - {event.time}")
            
            if summary.extracted_info.people:
                for person in summary.extracted_info.people:
                    logger.info(f"人物: {person.name}")
            
            logger.info("内容归纳服务测试完成")
            return True
        else:
            logger.error("内容归纳失败")
            return False
            
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_event_bus():
    """测试事件总线"""
    logger.info("开始测试事件总线")
    
    try:
        from src.core.event_bus import EventBus, EventType
        
        # 初始化事件总线
        event_bus = EventBus()
        
        # 测试事件订阅和发布
        received_events = []
        
        def sync_handler(event_data):
            logger.info(f"同步处理器收到事件: {event_data}")
            received_events.append(event_data)
        
        async def async_handler(event_data):
            logger.info(f"异步处理器收到事件: {event_data}")
            received_events.append(event_data)
        
        # 订阅事件
        event_bus.subscribe(EventType.TURN_STARTED, sync_handler)
        event_bus.subscribe_async(EventType.TURN_COMPLETED, async_handler)
        
        # 发布事件
        event_bus.emit(EventType.TURN_STARTED, {"turn_id": 1, "user_input": "测试输入"})
        await asyncio.sleep(0.1)  # 等待异步处理
        
        event_bus.emit(EventType.TURN_COMPLETED, {"turn_id": 1, "response": "测试响应"})
        await asyncio.sleep(0.1)  # 等待异步处理
        
        logger.info(f"共收到{len(received_events)}个事件")
        logger.info("事件总线测试完成")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有测试"""
    logger.info("开始系统组装层测试")
    
    tests = [
        ("事件总线", test_event_bus),
        ("内容归纳服务", test_content_summarizer),
        ("对话主控器", test_conversation_orchestrator),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n=== 运行测试: {test_name} ===")
        result = await test_func()
        results.append((test_name, result))
    
    # 打印测试结果
    logger.info("\n=== 测试结果汇总 ===")
    passed = 0
    for test_name, result in results:
        status = "通过" if result else "失败"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\n总测试数: {len(tests)}, 通过数: {passed}, 失败数: {len(tests) - passed}")
    
    if passed == len(tests):
        logger.info("所有测试通过！")
        return True
    else:
        logger.error("部分测试失败！")
        return False


if __name__ == "__main__":
    asyncio.run(main())