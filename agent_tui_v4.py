# -*- coding: utf-8 -*-
"""
Browser Agent TUI v4
用法: python agent_tui_v4.py  或  leafcode
"""
import sys, os, re, json, asyncio, threading, time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Static, Input, Label
from textual.widget import Widget
from textual.binding import Binding
from textual.reactive import reactive
from textual.css.query import NoMatches
from textual.events import MouseScrollDown, MouseScrollUp, Click, Resize

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from agent import BrowserAgent, AgentMode
from leafcode.models import RuntimeEvent, TaskState


def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("'").strip('"')
                if key not in os.environ:
                    os.environ[key] = val


_load_dotenv()


APP_CSS = """
Screen {
    background: #0d1117;
}

#status-bar {
    height: 1;
    color: #c9d1d9;
    background: #161b22;
    padding: 0 1;
}
#loading-bar {
    height: 1;
    color: #d29922;
    background: #161b22;
    padding: 0 1;
}
#message-area {
    background: #0d1117;
    scrollbar-size: 1 1;
    scrollbar-background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #484f58;
    scrollbar-color-active: #58a6ff;
}
#sidebar {
    width: 30;
    background: #161b22;
    border-left: solid #30363d;
}
#command-palette {
    display: none;
    dock: top;
    height: auto;
    background: #161b22;
    border: solid #58a6ff;
    color: #c9d1d9;
    padding: 1 2;
    margin: 1 2;
}
#debug-panel {
    display: none;
    height: auto;
    max-height: 12;
    overflow-y: auto;
    background: #161b22;
    color: #8b949e;
    border-top: solid #30363d;
    padding: 0 1;
}

/* 输入区 */
#input-section {
    background: #161b22;
    border-top: solid #30363d;
    padding: 0 1;
    height: auto;
}
#confirmation-actions {
    display: none;
    height: 3;
    padding: 0 1;
}
#confirmation-actions Button {
    margin: 0 1;
    min-width: 12;
}
#confirm-yes {
    background: #238636;
}
#confirm-no {
    background: #da3633;
}

#user-input {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
    margin: 1 0;
}
#user-input:focus {
    border: solid #58a6ff;
}

/* 模式栏 */
#mode-row {
    height: 1;
    background: #161b22;
    padding: 0 1;
}
#mode-label {
    text-style: bold;
}
.mode-inform {
    color: #d29922;
}
.mode-operate {
    color: #58a6ff;
}
#mode-hint {
    color: #8b949e;
}

#bottom-pad {
    height: 1;
    background: #161b22;
}

/* Part */
UserMessage {
    width: auto;
    color: #58a6ff;
    margin: 1 0 0 1;
}
AgentMessage {
    margin: 0 0;
    padding: 0 1;
}
ThinkingPart {
    color: #8b949e;
    padding: 0 2;
}
ToolPart {
    color: #79c0ff;
    padding: 0 2;
}
TextPart {
    color: #c9d1d9;
    padding: 0 2;
}
ErrorPart {
    color: #f85149;
    padding: 0 2;
}
StatusPart {
    color: #3fb950;
    padding: 0 2;
}
ActivityPart {
    color: #c9d1d9;
    padding: 0 2;
}
ConfirmationPart {
    color: #d29922;
    border: solid #d29922;
    padding: 1 2;
    margin: 1 1;
}
Divider {
    height: 1;
    color: #30363d;
    margin: 1 0;
}
"""


class ThinkingPart(Static):
    def __init__(self, text: str):
        super().__init__(f"  THOUGHT: {text}", markup=False)


class ToolPart(Static):
    def __init__(self, text: str, icon: str = "▸"):
        super().__init__(f"  {icon} {text}", markup=False)


class TextPart(Static):
    def __init__(self, text: str):
        super().__init__(text, markup=False)


class ErrorPart(Static):
    def __init__(self, text: str):
        super().__init__(f"  ERROR: {text}", markup=False)


class StatusPart(Static):
    def __init__(self, text: str = "完成"):
        super().__init__(f"  DONE: {text}", markup=False)


class Divider(Static):
    def __init__(self):
        super().__init__("─" * 50, markup=False)


class ActivityPart(Static):
    def __init__(self, text: str):
        super().__init__(f"  • {text}", markup=False)


class ConfirmationPart(Static):
    def __init__(self, text: str):
        super().__init__(
            f"  CONFIRMATION: {text}\n  请选择 Yes/No，或输入 /confirm、/reject",
            markup=False,
        )


class UserMessage(Static):
    def __init__(self, text: str):
        super().__init__(
            "\n".join(f"│ {line}" for line in text.split("\n")), markup=False
        )


class AgentMessage(Vertical):
    def add_part(self, w: Widget):
        self.mount(w)


class Sidebar(Widget):
    def compose(self) -> ComposeResult:
        yield Static("  SESSION", id="sidebar-title", markup=False)
        yield Static("  ──────────", markup=False)
        yield Static("  暂无活动会话", id="sidebar-content", markup=False)


class PartFactory:
    def __init__(self):
        self.parts = []
        self._buf = ""

    def feed(self, text: str):
        self._buf += text
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            self._buf = lines.pop()
            for line in lines:
                self._process_line(line)

    def flush(self):
        if self._buf.strip():
            self._process_line(self._buf)
            self._buf = ""

    def _process_line(self, line: str):
        line = line.strip()
        if not line:
            return
        if line.startswith("THOUGHT:"):
            self.parts.append(ThinkingPart(line.removeprefix("THOUGHT:").strip()))
            return
        if line.startswith("ACTION:"):
            self.parts.append(ToolPart(line))
            return
        if line.startswith("ERROR:"):
            self.parts.append(ErrorPart(line.removeprefix("ERROR:").strip()))
            return
        if line.startswith("OK:") or line.startswith("CONFIRMED:"):
            self.parts.append(StatusPart(line))
            return
        if line.startswith("===") or line.startswith("──"):
            return
        if line.startswith("🎯"):
            self.parts.append(ToolPart(line, icon="🎯"))
            return
        if line.startswith("📝"):
            self.parts.append(TextPart(line))
            return
        if re.match(r"📍\s*第\s*\d+", line):
            return
        if line.startswith("👁"):
            self.parts.append(ToolPart(re.sub(r"👁\s*\[感知\]\s*", "", line), icon="👁"))
            return
        if line.startswith("💭"):
            self.parts.append(ThinkingPart(re.sub(r"💭\s*", "", line)))
            return
        if line.startswith("🤔"):
            m = re.search(r'"thought"\s*:\s*"([^"]*)"', line)
            if m:
                self.parts.append(ThinkingPart(m.group(1)))
                return
        if any(line.startswith(p) for p in ["🚀", "📋", "📺", "🔑", "💡"]):
            return
        if "✅" in line and "任务" in line:
            self.parts.append(StatusPart())
            return
        if "已达最大步数" in line or "已中断" in line:
            self.parts.append(ErrorPart(line))
            return
        if line.startswith("已"):
            self.parts.append(ToolPart(line))
            return
        self.parts.append(TextPart(line))


class BrowserAgentApp(App):
    CSS = APP_CSS
    BINDINGS = [
        Binding("tab", "toggle_focus", "焦点", show=False),
        Binding("ctrl+t", "switch_mode", "切换模式"),
        Binding("ctrl+b", "toggle_sidebar", "侧边栏"),
        Binding("ctrl+p", "command_palette", "命令面板"),
        Binding("f2", "toggle_debug", "调试信息", show=False),
        Binding("pageup", "scroll_page_up", "上翻页", show=False),
        Binding("pagedown", "scroll_page_down", "下翻页", show=False),
        Binding("home", "scroll_home", "跳到顶", show=False),
        Binding("end", "scroll_end", "跳到底", show=False),
        Binding("escape", "esc_handler", "回输入/中断", show=False),
        Binding("ctrl+l", "clear_messages", "清屏", show=False),
    ]

    mode = reactive(AgentMode.INFORM)
    auto_scroll = reactive(True)
    loading = reactive(False)
    sidebar_visible = reactive(False)
    palette_visible = reactive(False)
    debug_visible = reactive(False)
    confirmation_visible = reactive(False)
    task_status = reactive("idle")
    current_url = reactive("")
    step_label = reactive("-")
    task_started_at: float | None = None

    def __init__(self):
        super().__init__()
        self.agent: BrowserAgent | None = None
        # 所有 Playwright 调用固定在同一个工作线程，避免跨线程访问页面对象。
        self.agent_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="leafcode-browser"
        )
        self.agent_future: Future | None = None
        self._pending_factory: PartFactory | None = None
        self._esc_times: list = []

    def compose(self) -> ComposeResult:
        yield Label("  idle · 未连接浏览器 · 步骤 -", id="status-bar")
        yield Label("", id="loading-bar")
        yield Static(
            "命令面板\n/new 新任务  /stop 停止  /retry 重试  /continue 继续\n/confirm 确认  /reject 拒绝  /tabs 标签页  /mode 模式\n/clear 清屏  /help 帮助",
            id="command-palette",
            markup=False,
        )
        with Horizontal():
            with VerticalScroll(id="message-area"):
                pass
            yield Sidebar(id="sidebar")
        with Container(id="input-section"):
            yield Input(
                placeholder="单行输入任务… Enter 提交（多行暂不支持）", id="user-input"
            )
            with Horizontal(id="confirmation-actions"):
                yield Button("Yes，执行操作", id="confirm-yes", variant="success")
                yield Button("No，拒绝操作", id="confirm-no", variant="error")
            with Horizontal(id="mode-row"):
                yield Static(
                    "  INFORM  ", id="mode-label", classes="mode-inform", markup=False
                )
                yield Static("  Ctrl+T 切换模式  ", id="mode-hint", markup=False)
        yield Static(
            "调试信息将在任务执行时显示。按 F2 展开或收起。",
            id="debug-panel",
            markup=False,
        )
        yield Static("", id="bottom-pad", markup=False)

    def watch_mode(self, old, new):
        try:
            label = self.query_one("#mode-label", Static)
            label.update(f"  {new.value.upper()}  ")
            label.set_class(old == AgentMode.INFORM, "mode-inform")
            label.set_class(old == AgentMode.OPERATE, "mode-operate")
            label.set_class(new == AgentMode.INFORM, "mode-inform")
            label.set_class(new == AgentMode.OPERATE, "mode-operate")
        except NoMatches:
            pass
        self.notify(f"切换 → {new.value}", timeout=1.0)

    def watch_loading(self, loading: bool):
        try:
            self.query_one("#loading-bar", Label).update(
                "  Preparing..." if loading else ""
            )
        except NoMatches:
            pass

    def _refresh_chrome(self):
        try:
            domain = (
                self.current_url.split("/")[2]
                if "://" in self.current_url
                else (self.current_url or "未连接浏览器")
            )
            elapsed = (
                f"{int(time.time() - self.task_started_at)}s"
                if self.task_started_at
                else "0s"
            )
            self.query_one("#status-bar", Label).update(
                f"  {self.task_status} · {self.mode.value} · {domain} · {elapsed} · 步骤 {self.step_label}/10"
            )
            self.query_one("#sidebar-content", Static).update(
                f"  状态: {self.task_status}\n  页面: {domain}\n  步骤: {self.step_label}\n\n  命令\n  /confirm  /reject\n  /continue /retry"
            )
        except NoMatches:
            pass

    def _handle_runtime_event(self, event: RuntimeEvent):
        self.step_label = str(event.data.get("step", self.step_label))
        self.current_url = event.data.get("url", self.current_url)
        if event.kind == "confirmation":
            self.task_status = "awaiting confirmation"
            self.confirmation_visible = True
            params = json.dumps(event.data.get("params", {}), ensure_ascii=False)
            details = (
                f"{event.message}\n"
                f"  ACTION: {event.data.get('action', 'unknown')}\n"
                f"  TARGET: {event.data.get('url', 'unknown')}\n"
                f"  PARAMS: {params}"
            )
            self._mount(ConfirmationPart(details))
        else:
            self.task_status = (
                "failed"
                if event.kind == "error"
                else (
                    "running"
                    if event.kind in {"plan", "action", "thought"}
                    else event.kind
                )
            )
            self._mount(ActivityPart(event.message))
            if event.kind == "action":
                self._mount(Divider())
        self._refresh_chrome()
        try:
            details = event.data.get("params") or event.data
            self.query_one("#debug-panel", Static).update(
                f"[{event.kind}] {event.message}\n{details}"
            )
        except NoMatches:
            pass
        self._scroll_end()

    def watch_sidebar_visible(self, old, new):
        try:
            self.query_one("#sidebar", Sidebar).display = new
        except NoMatches:
            pass

    def watch_palette_visible(self, old, new):
        try:
            self.query_one("#command-palette", Static).display = new
        except NoMatches:
            pass

    def watch_debug_visible(self, old, new):
        try:
            self.query_one("#debug-panel", Static).display = new
        except NoMatches:
            pass

    def watch_confirmation_visible(self, old, new):
        try:
            self.query_one("#confirmation-actions", Horizontal).display = new
            self.query_one("#user-input", Input).display = not new
        except NoMatches:
            pass

    def on_resize(self, event: Resize):
        if event.size.width < 100:
            self.sidebar_visible = False

    # ── 工具方法 ──

    def _msg_area(self) -> VerticalScroll:
        return self.query_one("#message-area", VerticalScroll)

    def _mount(self, w: Widget):
        if threading.current_thread() is threading.main_thread():
            self._msg_area().mount(w)
        else:
            self.call_from_thread(lambda: self._msg_area().mount(w))

    def _scroll_end(self):
        if not self.auto_scroll:
            return
        try:
            self._msg_area().scroll_end(animate=False)
        except NoMatches:
            pass

    # ── 滚动 ──

    def on_mouse_scroll_up(self, e):
        self.auto_scroll = False

    def on_mouse_scroll_down(self, e):
        try:
            if self._msg_area().is_vertical_scroll_end:
                self.auto_scroll = True
        except NoMatches:
            pass

    # ── 按键 ──

    def action_toggle_focus(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus:
                self._msg_area().focus()
            else:
                inp.focus()
        except NoMatches:
            pass

    def action_switch_mode(self):
        self.mode = (
            AgentMode.OPERATE if self.mode == AgentMode.INFORM else AgentMode.INFORM
        )

    def action_toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible

    def action_command_palette(self):
        self.palette_visible = not self.palette_visible

    def action_toggle_debug(self):
        self.debug_visible = not self.debug_visible

    def action_scroll_page_up(self):
        self.auto_scroll = False
        try:
            self._msg_area().scroll_page_up()
        except NoMatches:
            pass

    def action_scroll_page_down(self):
        try:
            a = self._msg_area()
            a.scroll_page_down()
            if a.is_vertical_scroll_end:
                self.auto_scroll = True
        except NoMatches:
            pass

    def action_scroll_home(self):
        self.auto_scroll = False
        try:
            self._msg_area().scroll_home()
        except NoMatches:
            pass

    def action_scroll_end(self):
        self.auto_scroll = True
        try:
            self._msg_area().scroll_end()
        except NoMatches:
            pass

    def action_clear_messages(self):
        try:
            for c in list(self._msg_area().children):
                if not isinstance(c, (Input, Sidebar)):
                    c.remove()
        except NoMatches:
            pass

    def action_esc_handler(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus:
                if not self.loading:
                    self._msg_area().focus()
                    return
                now = time.time()
                self._esc_times.append(now)
                self._esc_times = [t for t in self._esc_times if now - t < 1.5]
                if len(self._esc_times) >= 3:
                    self._esc_times.clear()
                    self.loading = False
                    if self.agent:
                        self.agent.abort = True
                    self._mount(Divider())
                    self._mount(ErrorPart("已中断"))
                    self._scroll_end()
                    return
                self.notify(f"Esc x{3-len(self._esc_times)} 中断", timeout=1.0)
                return
            inp.focus()
        except NoMatches:
            pass

    # ── 模式标签点击 ──

    @on(Click, "#mode-label")
    def on_mode_click(self, event: Click):
        self.action_switch_mode()

    @on(Button.Pressed, "#confirm-yes")
    def on_confirm_yes(self, event: Button.Pressed):
        self._submit_confirmation(True)

    @on(Button.Pressed, "#confirm-no")
    def on_confirm_no(self, event: Button.Pressed):
        self._submit_confirmation(False)

    def _submit_confirmation(self, approved: bool):
        if not self.agent:
            return
        message = self.agent.submit_confirmation(approved)
        self.confirmation_visible = False
        self.task_status = "running" if approved else "cancelling"
        self._refresh_chrome()
        self._mount(ActivityPart(message))
        self._scroll_end()

    # ── 输入提交 ──

    @on(Input.Submitted, "#user-input")
    async def on_submit(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#user-input", Input)
        inp.value = ""
        if not text:
            return

        self._mount(UserMessage(text))
        self._mount(Divider())
        command = text.lower()

        if command == "/clear":
            self.action_clear_messages()
            return
        if command == "/new":
            self.task_status, self.current_url, self.step_label = "idle", "", "-"
            self._refresh_chrome()
            self._mount(StatusPart("已创建新任务上下文"))
            return
        if command == "/mode":
            self.action_switch_mode()
            self._refresh_chrome()
            return
        if command == "/help":
            self._mount(
                ActivityPart(
                    "命令: /new /stop /retry /continue /confirm /reject /tabs /mode /clear /help"
                )
            )
            return
        if command == "/tabs":
            pages = (
                self.agent.session.context.pages
                if self.agent and self.agent.session and self.agent.session.context
                else []
            )
            self._mount(
                ActivityPart(
                    "标签页: "
                    + (" | ".join(page.url for page in pages) if pages else "无")
                )
            )
            return
        if command == "/stop":
            if self.agent:
                self.agent.abort = True
            self.task_status = "cancelling"
            self._refresh_chrome()
            self._mount(ActivityPart("已请求停止当前任务。"))
            return

        if text.lower() == "home":
            self._mount(StatusPart("Agent 已退出"))
            self._mount(Divider())
            self._scroll_end()
            return

        if not self.agent:
            self._mount(
                ErrorPart("未配置 DEEPSEEK_API_KEY；请在 .env 中配置后重新启动。")
            )
            self._scroll_end()
            return

        if command in {"/confirm", "/reject"}:
            self._submit_confirmation(command == "/confirm")
            return

        if self.loading:
            self._mount(TextPart("  上一个任务执行中"))
            self._scroll_end()
            return

        if command in {"/continue", "/retry"}:
            self.task_status = "running"
            self._refresh_chrome()
            factory = PartFactory()
            self._pending_factory = factory
            self.loading = True
            self.agent_future = self.agent_executor.submit(
                self._run_control, command, factory
            )
            self._scroll_end()
            return

        auto_headless, clean_task = BrowserAgent.detect_mode(text)
        actual_task = clean_task if auto_headless else text
        if self.agent:
            self.agent.headless = auto_headless
        if auto_headless:
            self._mount(ThinkingPart("静默模式"))

        factory = PartFactory()
        self._pending_factory = factory
        self.loading = True
        self.task_status = "planning"
        self.step_label = "0"
        self.task_started_at = time.time()
        self._refresh_chrome()
        self.agent_future = self.agent_executor.submit(
            self._run_agent, actual_task, factory
        )
        self._scroll_end()

    def _run_agent(self, task: str, factory: PartFactory):
        try:
            # TUI 只渲染结构化事件，避免与终端文本流重复显示。
            self.agent.on_output = lambda _text: None
            self.agent.on_event = lambda event: self.call_from_thread(
                self._handle_runtime_event, event
            )
            self.agent.run(task, mode=self.mode)
        except Exception as e:
            factory.feed(f"\nERROR: {e}")
        finally:
            factory.flush()

    def _run_control(self, command: str, factory: PartFactory):
        self.agent.on_output = lambda _text: None
        self.agent.on_event = lambda event: self.call_from_thread(
            self._handle_runtime_event, event
        )
        try:
            result = self.agent.continue_task(retry=command == "/retry")
            factory.feed(f"{result}\n")
        except Exception as e:
            factory.feed(f"\nERROR: {e}")
        finally:
            factory.flush()

    def on_mount(self):
        self.set_interval(0.3, self._tick)
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        self.agent = BrowserAgent(api_key=api_key, headless=False) if api_key else None
        try:
            self.query_one("#sidebar", Sidebar).display = False
            self.query_one("#user-input", Input).focus()
            self._refresh_chrome()
        except NoMatches:
            pass

    def on_unmount(self):
        if self.agent:
            self.agent.abort = True
            self.agent.submit_confirmation(False)
            self.agent_executor.submit(self.agent.close)
        self.agent_executor.shutdown(wait=False, cancel_futures=False)

    def _tick(self):
        if self.loading:
            self._refresh_chrome()
        if not self._pending_factory:
            return
        parts = self._pending_factory.parts
        if parts:
            batch = parts[:]
            parts.clear()
            for pw in batch:
                self._mount(pw)
            self._scroll_end()
        if self.agent_future and self.agent_future.done():
            self.agent_future = None
            self._pending_factory = None
            self.loading = False
            if self.agent and self.agent.task_context:
                self.task_status = self.agent.task_context.state.value
                if self.agent.task_context.latest_snapshot:
                    self.current_url = self.agent.task_context.latest_snapshot.url
                self.step_label = str(
                    self.agent.task_context.current_step or self.step_label
                )
                self._refresh_chrome()
            self._mount(Divider())
            state = (
                self.agent.task_context.state
                if self.agent and self.agent.task_context
                else None
            )
            if state == TaskState.COMPLETED:
                status = (
                    "完成 (浏览器已保留)" if self.mode == AgentMode.OPERATE else "完成"
                )
                self._mount(StatusPart(status))
            elif state == TaskState.AWAITING_CONFIRMATION:
                self._mount(ConfirmationPart("任务暂停，等待你的确认。"))
            elif state == TaskState.CANCELLED:
                self._mount(StatusPart("任务已取消"))
            else:
                detail = (
                    self.agent.task_context.error
                    if self.agent and self.agent.task_context
                    else "任务未完成"
                )
                self._mount(ErrorPart(f"任务失败：{detail}"))
            self.auto_scroll = True
            self._scroll_end()


if __name__ == "__main__":
    BrowserAgentApp().run()
