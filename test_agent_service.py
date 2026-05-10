import asyncio
import logging
from dotenv import load_dotenv

from src.agents import InterviewSessionAgent

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_agent_service():
    """测试Agent服务主体的基本功能"""
    logger.info("开始测试Agent服务主体")
    
    try:
        # 创建Agent实例
        agent = InterviewSessionAgent(user_id="test_user_123")
        
        # 启动会话
        opening = await agent.start()
        logger.info(f"Agent开场白: {opening}")
        
        # 模拟用户输入
        user_input = "我叫张三，今年70岁了"
        logger.info(f"用户输入: {user_input}")
        
        # 处理用户输入
        response = await agent.handle_user_input(user_input)
        logger.info(f"Agent响应: {response}")
        
        logger.info("Agent服务主体测试完成！")
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    asyncio.run(test_agent_service())