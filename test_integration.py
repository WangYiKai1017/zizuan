# test_integration.py
# 系统集成测试脚本

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


async def test_full_conversation_flow():
    """测试完整的对话流程"""
    logger.info("开始完整对话流程测试")
    
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
        
        # 模拟完整对话流程
        conversation_history = [
            "我是李明，今年78岁了",
            "我以前是一名中学教师，教了40年书",
            "我1945年出生在上海，1968年毕业于北京大学",
            "我教的是语文，最喜欢的作家是鲁迅",
            "我和妻子结婚50年了，我们有两个孩子",
            "退休后我喜欢写书法，偶尔也会旅游",
            "我最难忘的是年轻时在农村支教的经历",
            "那时候条件很艰苦，但学生们都很努力",
            "我觉得教师是最神圣的职业之一",
            "现在的生活很幸福，子孙绕膝"
        ]
        
        for i, user_input in enumerate(conversation_history, 1):
            logger.info(f"\n=== 轮次 {i} ===")
            logger.info(f"用户: {user_input}")
            
            # 处理用户输入
            response = await orchestrator.process_turn(user_input)
            
            logger.info(f"助手: {response.message}")
            logger.info(f"状态: {response.state_update}")
            
            # 检查是否需要暂停或交接
            if response.should_pause:
                logger.info(f"提示: 会话需要暂停 - {response.pause_reason}")
                break
                
            if response.handoff_triggered:
                logger.info("提示: 会话将进行交接")
                break
        
        # 终止会话并获取交接包
        logger.info("\n=== 终止会话 ===")
        handoff = await orchestrator.terminate_session()
        
        logger.info(f"交接包信息:")
        logger.info(f"- 交接包ID: {handoff.handoff_id}")
        logger.info(f"- 会话ID: {handoff.session_info.session_id}")
        logger.info(f"- 总轮次: {handoff.session_info.total_turns}")
        logger.info(f"- 使用策略: {handoff.session_info.strategy_used}")
        logger.info(f"- 收集事件数: {len(handoff.collected_data.events)}")
        logger.info(f"- 收集人物数: {len(handoff.collected_data.people)}")
        logger.info(f"- 时间线标记数: {len(handoff.collected_data.timeline)}")
        logger.info(f"- 主题数: {len(handoff.collected_data.themes)}")
        
        # 打印收集的事件
        if handoff.collected_data.events:
            logger.info("\n收集的事件:")
            for i, event in enumerate(handoff.collected_data.events[:3]):  # 只显示前3个
                logger.info(f"  {i+1}. {event.title} ({event.time})")
                logger.info(f"     {event.description[:100]}...")
        
        # 打印收集的人物
        if handoff.collected_data.people:
            logger.info("\n收集的人物:")
            for i, person in enumerate(handoff.collected_data.people[:3]):  # 只显示前3个
                logger.info(f"  {i+1}. {person.name} ({person.role})")
                if person.description:
                    logger.info(f"     {person.description[:100]}...")
        
        logger.info("\n完整对话流程测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_emotion_detection():
    """测试情绪检测功能"""
    logger.info("\n开始情绪检测功能测试")
    
    try:
        from src.services.emotion_detector import EmotionDetector
        from src.services.llm_service import LLMService
        from src.models import ConversationTurn
        
        # 从环境变量创建LLM配置
        llm_config = LLMConfig.from_env()
        llm_service = LLMService(llm_config)
        
        # 初始化情绪检测器
        emotion_detector = EmotionDetector(llm_service)
        
        # 测试不同情绪的输入
        test_cases = [
            "今天天气真好，我心情很愉快",
            "我感到很悲伤，想起了去世的老伴",
            "我很生气，现在的年轻人太不懂礼貌了",
            "我很害怕，晚上一个人在家会胡思乱想",
            "我很平静，退休后每天都过得很充实"
        ]
        
        for i, user_input in enumerate(test_cases, 1):
            logger.info(f"\n测试用例 {i}: {user_input}")
            
            # 构建对话历史
            history = [
                ConversationTurn(
                    turn_id=1,
                    user_input="您好！",
                    agent_response="您好！很高兴见到您。"
                )
            ]
            
            # 检测情绪
            emotion_result = await emotion_detector.detect(user_input, history)
            
            logger.info(f"情绪类型: {emotion_result.emotion_type}")
            logger.info(f"情绪强度: {emotion_result.intensity}")
            logger.info(f"是否需要特殊处理: {emotion_result.needs_special_handling}")
            logger.info(f"是否需要暂停: {emotion_result.should_pause()}")
        
        logger.info("情绪检测功能测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_question_generation():
    """测试问题生成功能"""
    logger.info("\n开始问题生成功能测试")
    
    try:
        from src.services.question_generator import QuestionGenerator
        from src.services.llm_service import LLMService
        from src.models import EmotionResult, MemoryQueryResult, SessionState
        from src.enums import StrategyType
        
        # 从环境变量创建LLM配置
        llm_config = LLMConfig.from_env()
        llm_service = LLMService(llm_config)
        
        # 初始化问题生成器
        question_generator = QuestionGenerator(llm_service)
        
        # 构建测试数据
        session_state = SessionState(
            session_id="test_session_001",
            strategy=StrategyType.SPARKLE_FIRST
        )
        
        emotion_result = EmotionResult(
            emotion_type="joy",
            intensity="medium",
            needs_special_handling=False,
            description="用户感到很开心"
        )
        
        memory_result = MemoryQueryResult.empty()
        
        # 测试问题生成
        test_cases = [
            "我是一名退休教师",
            "我最喜欢的是和学生们在一起的时光",
            "我退休后喜欢写书法和钓鱼",
            "我有两个孩子，他们都很孝顺"
        ]
        
        for i, user_input in enumerate(test_cases, 1):
            logger.info(f"\n测试用例 {i}: {user_input}")
            
            # 生成问题
            question = await question_generator.generate(
                user_input, emotion_result, memory_result, session_state
            )
            
            logger.info(f"生成的问题: {question}")
        
        logger.info("问题生成功能测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """运行所有集成测试"""
    logger.info("开始系统集成测试")
    
    tests = [
        ("情绪检测功能", test_emotion_detection),
        ("问题生成功能", test_question_generation),
        ("完整对话流程", test_full_conversation_flow),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n=== 运行集成测试: {test_name} ===")
        result = await test_func()
        results.append((test_name, result))
    
    # 打印测试结果
    logger.info("\n=== 集成测试结果汇总 ===")
    passed = 0
    for test_name, result in results:
        status = "通过" if result else "失败"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
    
    logger.info(f"\n总测试数: {len(tests)}, 通过数: {passed}, 失败数: {len(tests) - passed}")
    
    if passed == len(tests):
        logger.info("所有集成测试通过！")
        logger.info("系统组装层实现完成，功能正常！")
        return True
    else:
        logger.error("部分集成测试失败！")
        return False


if __name__ == "__main__":
    asyncio.run(main())