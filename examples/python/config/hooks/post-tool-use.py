#!/usr/bin/env python3
"""
Post-tool-use Hook示例

在工具执行后运行，可用于：
- 结果审计
- 数据收集
- 副作用处理
- 通知发送
"""

def post_tool_use(tool_name: str, tool_input: dict, tool_output: str) -> str:
    raise NotImplementedError("AI: 实现 post_tool_use")