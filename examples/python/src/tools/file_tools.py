#!/usr/bin/env python3
"""
# ============================================
# 类型: 教学参考骨架（禁止直接复制）
# 模块: tools.file_tools
# 说明: 文件操作工具的**契约与骨架**，不含实现
#
# 铁律：本仓库所有代码仅为"真实签名 + raise NotImplementedError + AI 构建提示"。
#      AI coding 工具必须自行设计实现，不得复制。
#
# ⚠️ 安全硬约束（本文件最容易被忽略、也最危险的一点）：
#      任何文件读写都必须先做路径校验——把路径 canonicalize（resolve 符号链接、
#      归一化 ".." 与 "."），再判断它是否仍在允许的根目录之内。
#      直接 open(path) 而没有任何白名单校验，会让 Agent 读到工作目录之外的
#      任意文件（SSH 私钥、.env、宿主机配置），这是 prompt injection 之后
#      最常见的数据泄漏路径。
#      详见 references/06-phase-permissions.md 与 references/12-sandbox-advanced.md。
# ============================================

from typing import Any, Dict, List

from ..utils.logging import get_logger

logger = get_logger(__name__)


class FileTools:
    """文件操作工具 —— 骨架实现，全部方法待 AI 自行设计。

    AI 构建提示：
      1. 构造函数必须接收 allowed_roots: List[str]（允许的根目录），默认取当前工作目录。
      2. 所有涉及路径的方法，第一步必须调用 _resolve_within_roots()：
         - 用 Path(path).resolve() canonicalize（会解符号链接、归一化 ..）
         - 逐个判断是否在某个 allowed_root 之下（用 is_relative_to 或 commonpath，
           注意 commonpath 对 "/foo/bar" 与 "/foo/barbaz" 会误判，必须比较分隔符边界）
         - 拒绝任何逃逸路径，返回**面向 Agent 的可纠正错误**，而不是抛裸异常
      3. 错误信息必须可执行化（这既是纠正提示也是防泄漏）：
         ❌ "Error: permission denied"
         ✅ "Error: path '/etc/passwd' is outside the allowed roots ['<cwd>'].
             Read files under the project directory, or ask the user to add the path to allowed_roots."
      4. 返回值要结构化且精简（不要整份内容塞回上下文）：至少包含
         truncated 标记与总行数，超限截断但明确告知被截断了多少。
      5. 不要把异常原文 str(e) 直接回传给 LLM——可能含绝对路径等敏感信息。
    """

    # 工具 Schema 定义（保留：这是接口契约，不是实现）
    read_file_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（必须在允许的根目录之内）"},
            "offset": {"type": "integer", "description": "起始行号（1-based）", "minimum": 1},
            "limit": {"type": "integer", "description": "最大读取行数", "minimum": 1, "maximum": 2000},
        },
        "required": ["path"],
    }

    write_file_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（必须在允许的根目录之内）"},
            "content": {"type": "string", "description": "文件内容"},
        },
        "required": ["path", "content"],
    }

    list_files_schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径（必须在允许的根目录之内）"},
            "recursive": {"type": "boolean", "description": "是否递归"},
            "pattern": {"type": "string", "description": "文件匹配模式"},
        },
        "required": ["path"],
    }

    def __init__(self, allowed_roots: List[str] | None = None) -> None:
        """AI: 设计构造函数。

        必须做的事：把 allowed_roots 逐个 Path(...).resolve() 存起来；为空时默认 [Path.cwd()]。
        额外建议：注入一个可选的根目录别名映射，让 Agent 能用 "@project/src/x.py" 这类
        语义路径，避免它一路试探绝对路径。
        """
        raise NotImplementedError(
            "AI: 实现 __init__ —— resolve 并保存 allowed_roots（默认取当前工作目录）"
        )

    def _resolve_within_roots(self, raw_path: str) -> str:
        """AI: 实现路径校验（**本文件最关键的私有方法**）。

        步骤：
          1. resolved = Path(raw_path).resolve()
          2. 对每个 root in self.allowed_roots：判断 resolved 是否在其内部
          3. 全部不匹配 → 抛出面向 Agent 的可纠正错误（说明原因 + 给出正确做法）
        陷阱提示：
          - 必须 resolve 符号链接，否则 ln -s /etc 就能绕过
          - 必须拒绝包含 NUL 字节的路径
          - Windows 下还要注意大小写与 8.3 短名
        """
        raise NotImplementedError(
            "AI: 实现路径白名单校验 —— canonicalize 后必须仍落在 allowed_roots 之内，"
            "否则返回可纠正错误（指明越界路径 + 允许的根目录）"
        )

    def read_file(self, input_data: Dict[str, Any]) -> str:
        """AI: 实现文件读取。

        必须先调用 self._resolve_within_roots(input_data["path"])，再 open。
        返回结构化精简结果（含 truncated / total_lines），超限截断。
        不要把原始异常 stacktrace 回传给 LLM。
        """
        raise NotImplementedError(
            "AI: 实现 read_file —— 先做路径白名单校验，再按 offset/limit 读取并返回结构化结果"
        )

    def write_file(self, input_data: Dict[str, Any]) -> str:
        """AI: 实现文件写入。

        同样必须先过 _resolve_within_roots。
        额外提示：写入前先判断父目录是否已存在，按需 makedirs；
        考虑是否写 .bak 备份（本 Skill 的"可逆性优先"哲学）。
        """
        raise NotImplementedError(
            "AI: 实现 write_file —— 路径校验 + 必要时的目录创建 + 可逆性（备份/差异预览）"
        )

    def list_files(self, input_data: Dict[str, Any]) -> List[str]:
        """AI: 实现目录列举。

        陷阱提示：
          - os.walk 递归时要跳过 .git / node_modules / __pycache__，否则会淹没上下文
          - 结果数量要有上限，超限要明确告知"还有 N 项未列出"
          - 同样需要路径校验
        """
        raise NotImplementedError(
            "AI: 实现 list_files —— 路径校验 + 噪声目录过滤 + 结果数量上限"
        )
