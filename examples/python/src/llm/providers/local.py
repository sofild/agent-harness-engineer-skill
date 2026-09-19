#!/usr/bin/env python3
"""
# ============================================
# 类型: 核心框架
# 模块: llm.providers.local
# 说明: 本地模型客户端实现（兼容OpenAI API）
# 修改建议: 如需扩展，继承LocalClient并覆盖方法
# ============================================

"""
from typing import Dict, Any, Optional, List

import httpx

from ..client import LLMClient, Message, ToolCall, LLMResponse


class LocalClient(LLMClient):
    """本地模型客户端（兼容OpenAI API）"""
    
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