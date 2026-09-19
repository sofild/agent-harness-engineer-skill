#!/usr/bin/env python3
"""
# ============================================
# 类型: 核心框架
# 模块: tools.registry
# 说明: 工具注册表，管理所有可用工具
# 修改建议: 如需添加新工具，调用register方法
# ============================================

"""
import json
from typing import Dict, List, Any, Callable
from dataclasses import dataclass

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable
    is_concurrency_safe: bool = False


class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        raise NotImplementedError("AI: 实现 __init__")
    def register(self, name: str, description: str, input_schema: Dict[str, Any], 
                 handler: Callable, is_concurrency_safe: bool = False):
        raise NotImplementedError("AI: 实现 register")
    def get_definitions(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("AI: 获取所有工具定义（用于LLM）")
    def execute(self, name: str, input_data: Dict[str, Any]) -> Any:
        raise NotImplementedError("AI: 实现 execute")
    def list_tools(self) -> List[str]:
        raise NotImplementedError("AI: 列出所有工具名称")
    def get_tool_info(self, name: str) -> Dict[str, Any]:
        raise NotImplementedError("AI: 获取工具信息")