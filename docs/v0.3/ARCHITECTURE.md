# LeafCode v0.3 架构

## 模块边界

```text
agent.py / agent_tui_v4.py       入口与界面适配
              │
              ▼
leafcode.runtime                任务编排、模型调用、状态迁移、事件输出
     ├── leafcode.safety         风险判定与确认门
     ├── leafcode.browser        Playwright 会话、快照、浏览器动作
     └── leafcode.models         跨模块数据契约
              │
              ▼
event_log.py                    独立的 JSONL 审计日志
```

## 依赖规则

- `models` 不依赖任何项目模块或第三方 UI/浏览器库。
- `browser` 只依赖 Playwright 和 `models`，不调用模型、不写 UI。
- `safety` 只读取动作与快照，不执行浏览器操作。
- `runtime` 编排浏览器、模型、策略和日志；它不依赖 Textual。
- `runtime` 通过 `RuntimeEvent` 发布计划、思考、动作、结果、错误与确认；TUI 订阅 `BrowserAgent.on_event`，不重定向全局 `stdout`。
- TUI 将模型、页面和动作参数按纯文本渲染，避免 JSON 中的方括号被终端富文本解析为标记。
- `agent.py` 只作为兼容 CLI；业务实现不得回流到该文件。

## 运行时约定

- `inform` 模式在任务完成、失败或取消后关闭 `BrowserSession`；等待风险确认时保持页面，直至确认或取消。
- `operate` 模式保留 `BrowserSession`，后续任务、`/continue` 和 `/retry` 可复用当前页面。
- Playwright 调用固定在 TUI 的单一工作线程；Yes/No 只提交确认信号，由该线程继续执行浏览器操作。

## 尚待完善

- 为真实网站回归补充端到端证据，验证不同站点的动态页面、超时和安全场景。
- 将侧栏扩展为最近任务和标签页列表，而不只显示当前会话摘要。
