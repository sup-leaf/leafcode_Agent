# LeafCode

LeafCode 是一个基于 DeepSeek 与 Playwright 的命令行浏览器 Agent。它会将自然语言任务拆为浏览器操作，并在 Textual 终端界面中展示执行过程。

当前处于 v0.3 开发阶段；计划、架构和测试状态见 [docs/v0.3](docs/v0.3/)。

## 环境要求

- Python 3.10 或更高版本。
- 可用的 DeepSeek API Key。
- Windows PowerShell（使用 `leafcode.ps1` 时）。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

将 `.env.example` 复制为 `.env`，再填入 API Key：

```powershell
Copy-Item .env.example .env
```

```dotenv
DEEPSEEK_API_KEY=你的真实密钥
```

`.env` 和运行日志都已被 Git 忽略；不要把真实密钥写入代码、Issue 或截图。

## 启动

Textual 界面：

```powershell
python agent_tui_v4.py
```

或从项目目录调用：

```powershell
.\leafcode.ps1
```

也可使用简单命令行入口：

```powershell
python agent.py
```

## 当前快捷键

| 快捷键 | 操作 |
| --- | --- |
| `Enter` | 提交任务 |
| `Tab` | 在输入区和消息区之间切换焦点 |
| `Ctrl+T` | 切换 inform / operate 模式 |
| `Ctrl+B` | 显示或隐藏侧栏 |
| `Ctrl+P` | 显示或隐藏命令面板 |
| `F2` | 显示或隐藏调试信息 |
| `Ctrl+L` | 清空消息 |
| `Esc` 连按三次 | 中断当前任务 |

## 模式

- `inform`：检索、阅读并输出总结；在任务完成、失败或取消后关闭浏览器。等待风险操作确认时会暂时保留页面。
- `operate`：任务结束后保留浏览器会话；后续任务以及 `/continue`、`/retry` 可在该会话的当前页面上继续执行。
- 任务中包含“后台”“静默”或 `headless` 等关键词时，使用无头浏览器。

## 确认与命令

可能产生外部影响的操作会暂停任务。界面会显示 **Yes，执行操作** 与 **No，拒绝操作** 两个按钮；也可输入 `/confirm` 或 `/reject`。确认结果由浏览器工作线程执行，避免跨线程访问页面。

常用命令包括：`/new`、`/stop`、`/continue`、`/retry`、`/tabs`、`/mode`、`/clear` 与 `/help`。`/continue` 和 `/retry` 适合在 `operate` 模式下使用；`inform` 的已结束任务会释放浏览器会话。

## 运行日志

每次任务会在 `logs/` 写入一个 JSONL 事件文件，用于定位失败和回归测试。日志会脱敏已知环境变量密钥以及常见的 API Key、Token、Password 字段；任务文本本身仍可能包含敏感信息，运行前请避免在任务中输入密码或个人数据。

## 本地回归

无需 API Key 的离线回归测试使用本地 HTML 验证浏览器会话、稳定元素 ID、动作验证、安全确认、日志脱敏、TUI 动作文本渲染，以及 `inform` 的会话释放：

```powershell
python -m unittest tests.test_v03_regression -v
```

它不替代 `docs/v0.3/TEST_CASES.md` 中的真实网站验收任务。

## 已知限制

- 模型每次最多执行 10 个原子步骤；重复的相同动作会被停止，复杂页面可能需要重新规划或人工继续。
- `inform` 是一次性浏览模式，任务结束后不保留会话；需要跨任务继续网页操作时请选择 `operate`。
- 离线回归已覆盖核心契约，但 `docs/v0.3/TEST_CASES.md` 中的真实网站验收任务尚未执行，不代表真实站点通过率。
- 不支持验证码绕过，不应自动执行支付、发帖、删除、下载或提交表单等高风险操作。
- 请仅在有权访问的网站上使用自动化。
