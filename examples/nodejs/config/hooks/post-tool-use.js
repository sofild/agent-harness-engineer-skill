/**
 * Post-tool-use Hook示例
 * 
 * 在工具执行后运行，可用于：
 * - 结果审计
 * - 数据收集
 * - 副作用处理
 * - 通知发送
 */

function postToolUse(toolName, toolInput, toolOutput) {
    throw new Error("AI: Post-tool-use Hook示例 在工具执行后运行，可用于： - 结果审计 - 数据收集 - 副作用处理 - 通知发送");
}

module.exports = { postToolUse };
