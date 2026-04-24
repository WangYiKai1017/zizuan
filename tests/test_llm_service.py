import pytest
from unittest.mock import AsyncMock, patch
from src.services.llm_service import LLMService, LLMCallResult
from src.config.llm_config import LLMConfig
from src.models import EmotionResult


class TestLLMService:
    @pytest.fixture
    def llm_service(self):
        config = LLMConfig(
            provider="openai",
            model_name="gpt-4o",
            api_key="test-key",
        )
        # 模拟模型初始化，避免实际调用API
        with patch("src.services.llm_service.ChatOpenAI") as mock_openai:
            mock_instance = AsyncMock()
            mock_openai.return_value = mock_instance
            service = LLMService(config)
            service._model = mock_instance
            return service
    
    @pytest.mark.asyncio
    async def test_invoke_success(self, llm_service):
        """测试成功调用"""
        # 模拟模型响应
        mock_response = type('obj', (object,), {'content': '测试响应', 'usage_metadata': {}})()
        llm_service._model.ainvoke = AsyncMock(return_value=mock_response)
        
        result = await llm_service.invoke("你好")
        
        assert result.success
        assert result.content == "测试响应"
        assert llm_service._model.ainvoke.called
    
    @pytest.mark.asyncio
    async def test_invoke_with_retry(self, llm_service):
        """测试重试机制"""
        # 模拟前两次失败，第三次成功
        responses = [
            Exception("Error 1"),
            Exception("Error 2"),
            type('obj', (object,), {'content': '成功', 'usage_metadata': {}})()
        ]
        llm_service._model.ainvoke = AsyncMock(side_effect=responses)
        
        result = await llm_service.invoke("测试重试")
        
        assert result.success
        assert llm_service._model.ainvoke.call_count == 3
    
    @pytest.mark.asyncio
    async def test_invoke_with_template(self, llm_service):
        """测试使用模板调用"""
        # 模拟模板渲染和模型调用
        with patch.object(llm_service, 'invoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = LLMCallResult(
                success=True,
                content='测试问题',
                model_name='gpt-4o'
            )
            
            result = await llm_service.invoke_with_template(
                template_name="question_generation",
                variables={
                    "strategy": "timeline_classic",
                    "current_phase": "childhood",
                    "turn_count": 1,
                    "coverage": "{}",
                    "user_input": "我小时候在农村长大",
                    "related_memory": "",
                    "pending_questions": "[]",
                    "emotion_type": "neutral",
                    "emotion_intensity": "low"
                }
            )
            
            assert result.success
            assert result.content == "测试问题"
            mock_invoke.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_invoke_structured(self, llm_service):
        """测试结构化输出"""
        with patch.object(llm_service, 'invoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = LLMCallResult(
                success=True,
                content='{"emotion_type": "joy", "intensity": "medium", "valence": "positive", "confidence": 0.8}',
            )
            
            result, raw = await llm_service.invoke_structured(
                template_name="emotion_detection",
                variables={"user_input": "我很高兴", "conversation_history": ""},
                output_model=EmotionResult,
            )
            
            assert result is not None
            assert result.emotion_type == "joy"
            assert result.intensity == "medium"
            assert raw.success
    
    @pytest.mark.asyncio
    async def test_invoke_structured_parse_error(self, llm_service):
        """测试结构化输出解析失败"""
        with patch.object(llm_service, 'invoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = LLMCallResult(
                success=True,
                content='不是有效的JSON',
            )
            
            result, raw = await llm_service.invoke_structured(
                template_name="emotion_detection",
                variables={"user_input": "测试", "conversation_history": ""},
                output_model=EmotionResult,
            )
            
            assert result is None
            assert not raw.success
            assert "Parse error" in raw.error
    
    @pytest.mark.asyncio
    async def test_invoke_structured_with_code_block(self, llm_service):
        """测试处理带代码块的JSON输出"""
        with patch.object(llm_service, 'invoke', new_callable=AsyncMock) as mock_invoke:
            mock_invoke.return_value = LLMCallResult(
                success=True,
                content='```json\n{"emotion_type": "neutral", "intensity": "low", "valence": "neutral", "confidence": 0.5}\n```',
            )
            
            result, raw = await llm_service.invoke_structured(
                template_name="emotion_detection",
                variables={"user_input": "测试", "conversation_history": ""},
                output_model=EmotionResult,
            )
            
            assert result is not None
            assert result.emotion_type == "neutral"
            assert result.intensity == "low"
    
    def test_get_stats(self, llm_service):
        """测试统计信息"""
        llm_service._call_history = [
            LLMCallResult(success=True, latency_ms=100, token_usage={"total_tokens": 100}),
            LLMCallResult(success=True, latency_ms=200, token_usage={"total_tokens": 200}),
            LLMCallResult(success=False, latency_ms=50, token_usage={"total_tokens": 50}),
        ]
        llm_service._total_tokens = 350
        
        stats = llm_service.get_stats()
        
        assert stats["total_calls"] == 3
        assert stats["success_rate"] == pytest.approx(2/3)
        assert stats["total_tokens"] == 350
        assert stats["avg_latency_ms"] == pytest.approx(116.6666667)
    
    def test_clear_history(self, llm_service):
        """测试清空调用历史"""
        llm_service._call_history = [
            LLMCallResult(success=True, latency_ms=100)
        ]
        llm_service._total_tokens = 100
        
        llm_service.clear_history()
        
        assert len(llm_service._call_history) == 0
        assert llm_service._total_tokens == 0
    
    def test_load_prompt_templates(self, llm_service):
        """测试加载Prompt模板"""
        # 重新加载模板并验证
        llm_service._load_prompt_templates()
        
        assert "question_generation" in llm_service._prompt_templates
        assert "emotion_detection" in llm_service._prompt_templates
        assert "content_summarization" in llm_service._prompt_templates
        assert "knowledge_base_react" in llm_service._prompt_templates
    
    @pytest.mark.asyncio
    async def test_invoke_failure(self, llm_service):
        """测试调用失败"""
        llm_service._model.ainvoke = AsyncMock(side_effect=Exception("API Error"))
        
        result = await llm_service.invoke("测试失败")
        
        assert not result.success
        assert "API Error" in result.error