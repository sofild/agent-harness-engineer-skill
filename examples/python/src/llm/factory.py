#!/usr/bin/env python3
"""
# ============================================
# 类型: 核心框架
# 模块: llm.factory
# 说明: LLM客户端工厂函数
# 修改建议: 如需添加新供应商，在providers字典中添加
# ============================================

"""
from typing import Dict, Any

from .client import LLMClient
from .providers.anthropic import AnthropicClient
from .providers.openai import OpenAIClient
from .providers.local import LocalClient


def create_llm_client(config: Dict[str, Any]) -> LLMClient:
    raise NotImplementedError("AI: 实现 create_llm_client")