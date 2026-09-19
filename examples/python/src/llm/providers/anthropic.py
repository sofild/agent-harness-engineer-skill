#!/usr/bin/env python3
"""
# ============================================
# 类型: 核心框架
# 模块: llm.providers.anthropic
# 说明: Anthropic Claude客户端实现
# 修改建议: 如需扩展，继承AnthropicClient并覆盖方法
# ============================================

"""
import json as json_mod
from typing import Dict, Any, Optional, List

from ..client import LLMClient, Message, ToolCall, LLMResponse

# 可选依赖
try:
    import anthropic
except ImportError:
    anthropic = None


class AnthropicClient(LLMClient):
    """Anthropic Claude客户端"""
    
    def __init__(self, config: Dict[str, Any]):
        raise NotImplementedError("AI: 实现 __init__")
    async def chat(
        self,
        messages: List[Message],
        tools: Optional[List[Dict]] = None,
        **kwargs
    ) -> LLMResponse:
        raise NotImplementedError("AI: 发送聊天请求")
    def validate_config(self) -> bool:
        raise NotImplementedError("AI: 验证配置")