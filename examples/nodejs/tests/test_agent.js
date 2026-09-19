/**
 * 测试Agent核心功能
 */

const { AgentCore } = require('../src/agent/core');

// 模拟LLM客户端
class MockLLMClient {
  constructor() {
      throw new Error("AI: constructor");
  }
  
  async chat(messages, tools) {
      throw new Error("AI: chat");
  }
  
  validateConfig() {
      throw new Error("AI: validateConfig");
  }
}

describe('AgentCore', () => {
  let agent;
  
  beforeEach(() => {
    agent = new AgentCore({
      provider: 'anthropic',
      model: 'test-model',
      apiKey: 'test-key'
    });
    agent.llmClient = new MockLLMClient();
  });
  
  test('should run agent', async () => {
    const result = await agent.run('Hello');
    expect(result).toBe('Test response');
  });
  
  test('should reset agent state', () => {
    agent.state.messages.push({ role: 'user', content: 'test' });
    agent.reset();
    expect(agent.state.messages).toHaveLength(0);
    expect(agent.state.turnCount).toBe(0);
  });
});
