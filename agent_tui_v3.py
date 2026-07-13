# -*- coding: utf-8 -*-
"""
Browser Agent TUI v3 —— Textual 框架，直接对标 opencode TUI 架构

用法: python agent_tui_v3.py  或  leafcode（全局命令）
"""
import sys, os, re, asyncio, threading, queue, io, time
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, Input, Label
from textual.widget import Widget
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from textual.css.query import NoMatches
from textual.events import MouseScrollDown, MouseScrollUp

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from agent import BrowserAgent

APP_CSS = """
Screen { background: #0d1117; }

/* 加载条 */
#loading-bar {
    height: 1;
    color: #d29922;
    background: #161b22;
    padding: 0 1;
}

/* 消息区 */
#message-area { background: #0d1117; }

/* 侧边栏 */
#sidebar {
    width: 30;
    background: #161b22;
    border-left: solid #30363d;
}

/* 输入区 */
#input-area {
    height: 3;
    background: #161b22;
    border-top: solid #30363d;
}
#input-area Input {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
}
#input-area Input:focus { border: solid #58a6ff; }

/* 用户消息 */
UserMessage {
    margin: 1 0 0 0;
    width: auto;
    color: #58a6ff;
}

/* Agent 消息 */
AgentMessage { margin: 0 0; padding: 0 1; }

ThinkingPart { color: #8b949e; padding: 0 2; }
ToolPart { color: #79c0ff; padding: 0 2; }
TextPart { color: #c9d1d9; padding: 0 2; }
ErrorPart { color: #f85149; padding: 0 2; }
StatusPart { color: #3fb950; padding: 0 2; }

Divider { height: 1; color: #30363d; margin: 1 0; }
"""


class ThinkingPart(Static):
    def __init__(self, text: str):
        super().__init__(f"  💭 {text}")

class ToolPart(Static):
    def __init__(self, text: str, icon: str = "▸"):
        super().__init__(f"  {icon} {text}")

class TextPart(Static):
    def __init__(self, text: str):
        super().__init__(text)

class ErrorPart(Static):
    def __init__(self, text: str):
        super().__init__(f"  ❌ {text}")

class StatusPart(Static):
    def __init__(self, text: str = "完成"):
        super().__init__(f"  ✅ {text}")

class Divider(Static):
    def __init__(self):
        super().__init__("─" * 50)


class UserMessage(Static):
    """用户消息：左边界 `│` 跟文字宽度对齐"""
    def __init__(self, text: str, color: str = "#58a6ff"):
        rendered = "\n".join(f"│ {line}" for line in text.split("\n"))
        super().__init__(rendered)


class AgentMessage(Vertical):
    def __init__(self):
        super().__init__()

    def add_part(self, widget: Widget):
        self.mount(widget)


class Sidebar(Widget):
    def compose(self) -> ComposeResult:
        yield Static("  📂 会话列表 (TODO)")
        yield Static("  ────────────────")
        yield Static("  (预留功能)")


class PartFactory:
    def __init__(self):
        self.parts: list = []
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
        if not line: return
        if line.startswith("===") or line.startswith("──"): return
        if line.startswith("🎯") and "意图" in line:
            self.parts.append(ToolPart(line, icon="🎯"))
            return
        if line.startswith("📝") and "计划" in line:
            self.parts.append(TextPart(line))
            return
        if re.match(r'📍\s*第\s*\d+', line): return
        if line.startswith("👁"):
            title = re.sub(r'👁\s*\[感知\]\s*', '', line)
            self.parts.append(ToolPart(title, icon="👁"))
            return
        if line.startswith("💭"):
            thought = re.sub(r'💭\s*', '', line)
            self.parts.append(ThinkingPart(thought))
            return
        if line.startswith("🤔"):
            thought_match = re.search(r'"thought"\s*:\s*"([^"]*)"', line)
            if thought_match:
                self.parts.append(ThinkingPart(thought_match.group(1)))
            return
        if any(line.startswith(p) for p in ["🚀", "📋", "📺", "🔑", "💡"]): return
        if "✅" in line and "任务" in line:
            self.parts.append(StatusPart())
            return
        if "📝" in line: return
        if "已达最大步数" in line:
            self.parts.append(ErrorPart(line))
            return
        if line.startswith("已"):
            self.parts.append(ToolPart(line))
            return
        self.parts.append(TextPart(line))


class _FactoryStream(io.TextIOBase):
    def __init__(self, factory: PartFactory):
        self.factory = factory
    def write(self, s: str):
        self.factory.feed(s)
    def flush(self):
        self.factory.flush()


class BrowserAgentApp(App):
    CSS = APP_CSS
    BINDINGS = [
        Binding("tab", "toggle_focus", "切换焦点", show=False),
        Binding("ctrl+b", "toggle_sidebar", "侧边栏"),
        Binding("ctrl+p", "command_palette", "命令面板"),
        Binding("pageup", "scroll_page_up", "上翻页", show=False),
        Binding("pagedown", "scroll_page_down", "下翻页", show=False),
        Binding("home", "scroll_home", "跳到顶", show=False),
        Binding("end", "scroll_end", "跳到底", show=False),
        Binding("escape", "esc_handler", "回输入/3次中断", show=False),
        Binding("ctrl+l", "clear_messages", "清屏", show=False),
    ]

    mode = reactive("agent")
    auto_scroll = reactive(True)
    loading = reactive(False)
    sidebar_visible = reactive(False)

    def __init__(self):
        super().__init__()
        self.agent: BrowserAgent | None = None
        self.agent_thread: threading.Thread | None = None
        self._output_queue = queue.Queue()
        self._pending_factory: PartFactory | None = None
        self._esc_times = []  # Esc 按下的时间戳列表

    def compose(self) -> ComposeResult:
        yield Label("", id="loading-bar")
        with Horizontal():
            with VerticalScroll(id="message-area"):
                pass
            yield Sidebar(id="sidebar")
        with Container(id="input-area"):
            yield Input(placeholder="输入任务开始执行... (home 退出)", id="user-input")

    def watch_loading(self, loading: bool):
        try:
            bar = self.query_one("#loading-bar", Label)
            bar.update("  ⏳ Preparing..." if loading else "")
        except NoMatches:
            pass

    def watch_sidebar_visible(self, old: bool, new: bool):
        try:
            self.query_one("#sidebar", Sidebar).display = new
        except NoMatches:
            pass

    def _get_message_area(self) -> VerticalScroll:
        return self.query_one("#message-area", VerticalScroll)

    def _add_widget(self, widget: Widget):
        if threading.current_thread() is threading.main_thread():
            self._mount_widget(widget)
        else:
            self.call_from_thread(self._mount_widget, widget)

    def _mount_widget(self, widget: Widget):
        self._get_message_area().mount(widget)

    def _scroll_to_bottom(self):
        if not self.auto_scroll: return
        try:
            self._get_message_area().scroll_end(animate=False)
        except NoMatches:
            pass

    def on_mouse_scroll_up(self, event: MouseScrollUp):
        self.auto_scroll = False

    def on_mouse_scroll_down(self, event: MouseScrollDown):
        try:
            if self._get_message_area().is_vertical_scroll_end:
                self.auto_scroll = True
        except NoMatches:
            pass

    # ── 按键动作 ────────────────

    def action_toggle_focus(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus:
                self.query_one("#message-area", VerticalScroll).focus()
            else:
                inp.focus()
        except NoMatches: pass

    def action_toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible

    def action_command_palette(self):
        self.notify("命令面板 (预留)", title="TODO", severity="information")

    def action_scroll_page_up(self):
        self.auto_scroll = False
        try: self._get_message_area().scroll_page_up()
        except NoMatches: pass

    def action_scroll_page_down(self):
        try:
            area = self._get_message_area()
            area.scroll_page_down()
            if area.is_vertical_scroll_end: self.auto_scroll = True
        except NoMatches: pass

    def action_scroll_home(self):
        self.auto_scroll = False
        try: self._get_message_area().scroll_home()
        except NoMatches: pass

    def action_scroll_end(self):
        self.auto_scroll = True
        try: self._get_message_area().scroll_end()
        except NoMatches: pass

    def action_clear_messages(self):
        try:
            for child in list(self._get_message_area().children):
                if not isinstance(child, (Input, Sidebar)):
                    child.remove()
        except NoMatches: pass

    def action_esc_handler(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus:
                # 只在 loading 状态下计数，否则直接切焦点
                if not self.loading:
                    self.query_one("#message-area", VerticalScroll).focus()
                    return

                now = time.time()
                self._esc_times.append(now)
                # 清理 1.5 秒前的旧记录
                self._esc_times = [t for t in self._esc_times if now - t < 1.5]

                if len(self._esc_times) >= 3:
                    self._esc_times.clear()
                    self.loading = False
                    if self.agent:
                        self.agent.abort = True
                    self._mount_widget(Divider())
                    self._mount_widget(ErrorPart("已中断 (Esc×3)"))
                    self._scroll_to_bottom()
                    return

                remaining = 3 - len(self._esc_times)
                self.notify(f"Esc 连按 {remaining} 次中断", timeout=1.0)
                return

            # 没焦点 → 回到输入框
            inp.focus()
        except NoMatches:
            pass

    # ── 输入处理 ────────────────

    @on(Input.Submitted, "#user-input")
    async def on_input(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#user-input", Input)
        inp.value = ""
        if not text: return

        user_msg = UserMessage(text)
        self._add_widget(user_msg)
        self._add_widget(Divider())

        if text.strip().lower() == "home":
            self.mode = "idle"
            self._add_widget(StatusPart("Agent 已退出"))
            self._add_widget(Divider())
            self._scroll_to_bottom()
            return

        if self.agent_thread and self.agent_thread.is_alive():
            self._add_widget(TextPart("  ⏳ 上一个任务还在执行"))
            self._scroll_to_bottom()
            return

        auto_headless, clean_task = BrowserAgent.detect_mode(text)
        actual_task = clean_task if auto_headless else text
        self.agent.headless = auto_headless

        if auto_headless:
            self._add_widget(ThinkingPart("静默模式"))

        factory = PartFactory()
        self._pending_factory = factory
        self.loading = True
        self.agent_thread = threading.Thread(
            target=self._run_agent, args=(actual_task, factory), daemon=True)
        self.agent_thread.start()
        self._scroll_to_bottom()

    def _run_agent(self, task: str, factory: PartFactory):
        old_stdout = sys.stdout
        sys.stdout = _FactoryStream(factory)
        try:
            self.agent.run(task)
        except Exception as e:
            factory.feed(f"\n❌ 执行出错: {e}")
        finally:
            sys.stdout = old_stdout
            factory.flush()

    def on_mount(self):
        self.set_interval(0.3, self._tick)
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if api_key:
            self.agent = BrowserAgent(api_key=api_key, headless=True)
        try:
            self.query_one("#sidebar", Sidebar).display = False
            inp = self.query_one("#user-input", Input)
            inp.placeholder = "输入任务开始执行... (home 退出)"
            inp.focus()
        except NoMatches: pass

    def _tick(self):
        if not self._pending_factory: return
        parts = self._pending_factory.parts
        if parts:
            batch = parts[:]
            parts.clear()
            for pw in batch:
                self._mount_widget(pw)
            self._scroll_to_bottom()
        if self.agent_thread and not self.agent_thread.is_alive():
            self.agent_thread = None
            self._pending_factory = None
            self.loading = False
            self._mount_widget(Divider())
            self._mount_widget(StatusPart())
            self.auto_scroll = True
            self._scroll_to_bottom()


if __name__ == "__main__":
    app = BrowserAgentApp()
    app.run()
