# 功能路线图

## v1 - MVP（已完成）
- [x] 基于 DeepSeek + Playwright 的浏览器 Agent
- [x] ReAct 循环：观察 → 思考 → 行动
- [x] prompt_toolkit 基础 TUI
- [x] 静默/显式双模式

## v2 - 架构升级（已完成）
- [x] opencode 风格 TUI（prompt_toolkit）
- [x] Part 架构输出
- [x] sticky-bottom 滚动
- [x] 命令-键位映射系统

## v3 - Textual 框架（已完成）
- [x] Textual 渲染引擎
- [x] Widget 树 + CSS
- [x] UserMessage / AgentMessage 组件
- [x] Esc×3 中断
- [x] 双阶段流程（意图理解 + 感知决策）
- [x] 统一选择器 + 自动提交搜索

## v4 - 双模式 + 操作自动化（当前）
- [x] inform/operate 双模式
- [x] .env 凭证管理
- [x] 浏览器保留模式
- [ ] ~~TextArea 多行输入~~（回退到 Input，待后续解决）

## v5 - 未来规划
- [ ] TextArea 多行输入（解决 prompt_toolkit 兼容问题）
- [ ] 登录自动化（B站/知乎/...）
- [ ] 会话持久化（保存对话历史）
- [ ] 侧边栏完善（会话列表 / TODO / 文件树）
- [ ] 命令面板（Ctrl+P）
- [ ] 多 Agent 协作
- [ ] 插件系统
