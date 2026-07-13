# -*- coding: utf-8 -*-
"""
Browser Agent TUI v4
用法: python agent_tui_v4.py  或  leafcode
"""
import sys, os, re, asyncio, threading, io, time
from pathlib import Path

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.widgets import Static, Input, Label
from textual.widget import Widget
from textual.binding import Binding
from textual.reactive import reactive
from textual.css.query import NoMatches
from textual.events import MouseScrollDown, MouseScrollUp, Click

sys.path.insert(0, str(Path(__file__).parent.resolve()))
from agent import BrowserAgent, AgentMode

def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line: continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("'").strip('"')
                if key not in os.environ: os.environ[key] = val
_load_dotenv()


APP_CSS = """
Screen { background: #0d1117; }

#loading-bar { height: 1; color: #d29922; background: #161b22; padding: 0 1; }
#message-area {
    background: #0d1117;
    scrollbar-size: 1 1;
    scrollbar-background: #0d1117;
    scrollbar-color: #30363d;
    scrollbar-color-hover: #484f58;
    scrollbar-color-active: #58a6ff;
}
#sidebar { width: 30; background: #161b22; border-left: solid #30363d; }

/* 输入区 */
#input-section {
    background: #161b22;
    border-top: solid #30363d;
    padding: 0 1;
    height: auto;
}

#user-input {
    background: #0d1117;
    color: #c9d1d9;
    border: solid #30363d;
    margin: 1 0;
}
#user-input:focus { border: solid #58a6ff; }

/* 模式栏 */
#mode-row {
    height: 1;
    background: #161b22;
    padding: 0 1;
}
#mode-label {
    text-style: bold;
}
.mode-inform { color: #d29922; }
.mode-operate { color: #58a6ff; }
#mode-hint {
    color: #8b949e;
}

#bottom-pad { height: 1; background: #161b22; }

/* Part */
UserMessage { width: auto; color: #58a6ff; margin: 1 0 0 1; }
AgentMessage { margin: 0 0; padding: 0 1; }
ThinkingPart { color: #8b949e; padding: 0 2; }
ToolPart { color: #79c0ff; padding: 0 2; }
TextPart { color: #c9d1d9; padding: 0 2; }
ErrorPart { color: #f85149; padding: 0 2; }
StatusPart { color: #3fb950; padding: 0 2; }
Divider { height: 1; color: #30363d; margin: 1 0; }
"""


class ThinkingPart(Static):
    def __init__(self, text: str): super().__init__(f"  💭 {text}")
class ToolPart(Static):
    def __init__(self, text: str, icon: str = "▸"): super().__init__(f"  {icon} {text}")
class TextPart(Static):
    def __init__(self, text: str): super().__init__(text)
class ErrorPart(Static):
    def __init__(self, text: str): super().__init__(f"  ❌ {text}")
class StatusPart(Static):
    def __init__(self, text: str = "完成"): super().__init__(f"  ✅ {text}")
class Divider(Static):
    def __init__(self): super().__init__("─" * 50)

class UserMessage(Static):
    def __init__(self, text: str):
        super().__init__("\n".join(f"│ {line}" for line in text.split("\n")))

class AgentMessage(Vertical):
    def add_part(self, w: Widget): self.mount(w)

class Sidebar(Widget):
    def compose(self) -> ComposeResult:
        yield Static("  📂 会话 (TODO)")
        yield Static("  ──────────")
        yield Static("  (预留)")


class PartFactory:
    def __init__(self): self.parts = []; self._buf = ""
    def feed(self, text: str):
        self._buf += text
        if "\n" in self._buf:
            lines = self._buf.split("\n"); self._buf = lines.pop()
            for line in lines: self._process_line(line)
    def flush(self):
        if self._buf.strip(): self._process_line(self._buf); self._buf = ""
    def _process_line(self, line: str):
        line = line.strip()
        if not line: return
        if line.startswith("===") or line.startswith("──"): return
        if line.startswith("🎯"): self.parts.append(ToolPart(line, icon="🎯")); return
        if line.startswith("📝"): self.parts.append(TextPart(line)); return
        if re.match(r'📍\s*第\s*\d+', line): return
        if line.startswith("👁"):
            self.parts.append(ToolPart(re.sub(r'👁\s*\[感知\]\s*', '', line), icon="👁")); return
        if line.startswith("💭"):
            self.parts.append(ThinkingPart(re.sub(r'💭\s*', '', line))); return
        if line.startswith("🤔"):
            m = re.search(r'"thought"\s*:\s*"([^"]*)"', line)
            if m: self.parts.append(ThinkingPart(m.group(1))); return
        if any(line.startswith(p) for p in ["🚀", "📋", "📺", "🔑", "💡"]): return
        if "✅" in line and "任务" in line: self.parts.append(StatusPart()); return
        if "已达最大步数" in line or "已中断" in line:
            self.parts.append(ErrorPart(line)); return
        if line.startswith("已"): self.parts.append(ToolPart(line)); return
        self.parts.append(TextPart(line))


class _FactoryStream(io.TextIOBase):
    def __init__(self, f): self.f = f
    def write(self, s: str): self.f.feed(s)
    def flush(self): self.f.flush()


class BrowserAgentApp(App):
    CSS = APP_CSS
    BINDINGS = [
        Binding("tab", "toggle_focus", "焦点", show=False),
        Binding("ctrl+t", "switch_mode", "切换模式"),
        Binding("ctrl+b", "toggle_sidebar", "侧边栏"),
        Binding("ctrl+p", "command_palette", "命令面板"),
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

    def __init__(self):
        super().__init__()
        self.agent: BrowserAgent | None = None
        self.agent_thread: threading.Thread | None = None
        self._pending_factory: PartFactory | None = None
        self._esc_times: list = []

    def compose(self) -> ComposeResult:
        yield Label("", id="loading-bar")
        with Horizontal():
            with VerticalScroll(id="message-area"): pass
            yield Sidebar(id="sidebar")
        with Container(id="input-section"):
            yield Input(placeholder="输入任务... Enter 提交", id="user-input")
            with Horizontal(id="mode-row"):
                yield Static("  INFORM  ", id="mode-label", classes="mode-inform")
                yield Static("  Ctrl+T 切换模式  ", id="mode-hint")
        yield Static("", id="bottom-pad")

    def watch_mode(self, old, new):
        try:
            label = self.query_one("#mode-label", Static)
            label.update(f"  {new.value.upper()}  ")
            label.set_class(old == AgentMode.INFORM, "mode-inform")
            label.set_class(old == AgentMode.OPERATE, "mode-operate")
            label.set_class(new == AgentMode.INFORM, "mode-inform")
            label.set_class(new == AgentMode.OPERATE, "mode-operate")
        except NoMatches: pass
        self.notify(f"切换 → {new.value}", timeout=1.0)

    def watch_loading(self, loading: bool):
        try: self.query_one("#loading-bar", Label).update("  ⏳ Preparing..." if loading else "")
        except NoMatches: pass

    def watch_sidebar_visible(self, old, new):
        try: self.query_one("#sidebar", Sidebar).display = new
        except NoMatches: pass

    # ── 工具方法 ──

    def _msg_area(self) -> VerticalScroll:
        return self.query_one("#message-area", VerticalScroll)

    def _mount(self, w: Widget):
        if threading.current_thread() is threading.main_thread():
            self._msg_area().mount(w)
        else:
            self.call_from_thread(lambda: self._msg_area().mount(w))

    def _scroll_end(self):
        if not self.auto_scroll: return
        try: self._msg_area().scroll_end(animate=False)
        except NoMatches: pass

    # ── 滚动 ──

    def on_mouse_scroll_up(self, e): self.auto_scroll = False
    def on_mouse_scroll_down(self, e):
        try:
            if self._msg_area().is_vertical_scroll_end: self.auto_scroll = True
        except NoMatches: pass

    # ── 按键 ──

    def action_toggle_focus(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus: self._msg_area().focus()
            else: inp.focus()
        except NoMatches: pass

    def action_switch_mode(self):
        self.mode = AgentMode.OPERATE if self.mode == AgentMode.INFORM else AgentMode.INFORM

    def action_toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible

    def action_command_palette(self):
        self.notify("命令面板 (预留)", title="TODO", severity="information")

    def action_scroll_page_up(self):
        self.auto_scroll = False
        try: self._msg_area().scroll_page_up()
        except NoMatches: pass

    def action_scroll_page_down(self):
        try:
            a = self._msg_area(); a.scroll_page_down()
            if a.is_vertical_scroll_end: self.auto_scroll = True
        except NoMatches: pass

    def action_scroll_home(self):
        self.auto_scroll = False
        try: self._msg_area().scroll_home()
        except NoMatches: pass

    def action_scroll_end(self):
        self.auto_scroll = True
        try: self._msg_area().scroll_end()
        except NoMatches: pass

    def action_clear_messages(self):
        try:
            for c in list(self._msg_area().children):
                if not isinstance(c, (Input, Sidebar)): c.remove()
        except NoMatches: pass

    def action_esc_handler(self):
        try:
            inp = self.query_one("#user-input", Input)
            if inp.has_focus:
                if not self.loading:
                    self._msg_area().focus(); return
                now = time.time()
                self._esc_times.append(now)
                self._esc_times = [t for t in self._esc_times if now - t < 1.5]
                if len(self._esc_times) >= 3:
                    self._esc_times.clear(); self.loading = False
                    if self.agent: self.agent.abort = True
                    self._mount(Divider()); self._mount(ErrorPart("已中断")); self._scroll_end()
                    return
                self.notify(f"Esc x{3-len(self._esc_times)} 中断", timeout=1.0); return
            inp.focus()
        except NoMatches: pass

    # ── 模式标签点击 ──

    @on(Click, "#mode-label")
    def on_mode_click(self, event: Click):
        self.action_switch_mode()

    # ── 输入提交 ──

    @on(Input.Submitted, "#user-input")
    async def on_submit(self, event: Input.Submitted):
        text = event.value.strip()
        inp = self.query_one("#user-input", Input)
        inp.value = ""
        if not text: return

        self._mount(UserMessage(text))
        self._mount(Divider())

        if text.lower() == "home":
            self._mount(StatusPart("Agent 已退出"))
            self._mount(Divider())
            self._scroll_end(); return

        if self.agent_thread and self.agent_thread.is_alive():
            self._mount(TextPart("  ⏳ 上一个任务执行中")); self._scroll_end(); return

        auto_headless, clean_task = BrowserAgent.detect_mode(text)
        actual_task = clean_task if auto_headless else text
        if self.agent: self.agent.headless = auto_headless
        if auto_headless: self._mount(ThinkingPart("静默模式"))

        factory = PartFactory()
        self._pending_factory = factory
        self.loading = True
        self.agent_thread = threading.Thread(
            target=self._run_agent, args=(actual_task, factory), daemon=True)
        self.agent_thread.start()
        self._scroll_end()

    def _run_agent(self, task: str, factory: PartFactory):
        old = sys.stdout
        sys.stdout = _FactoryStream(factory)
        try: self.agent.run(task, mode=self.mode)
        except Exception as e: factory.feed(f"\n❌ {e}")
        finally: sys.stdout = old; factory.flush()

    def on_mount(self):
        self.set_interval(0.3, self._tick)
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        self.agent = BrowserAgent(api_key=api_key, headless=False) if api_key else None
        try:
            self.query_one("#sidebar", Sidebar).display = False
            self.query_one("#user-input", Input).focus()
        except NoMatches: pass

    def _tick(self):
        if not self._pending_factory: return
        parts = self._pending_factory.parts
        if parts:
            batch = parts[:]; parts.clear()
            for pw in batch: self._mount(pw)
            self._scroll_end()
        if self.agent_thread and not self.agent_thread.is_alive():
            self.agent_thread = None; self._pending_factory = None; self.loading = False
            self._mount(Divider())
            status = "完成 (浏览器已保留)" if self.mode == AgentMode.OPERATE else "完成"
            self._mount(StatusPart(status))
            self.auto_scroll = True; self._scroll_end()


if __name__ == "__main__":
    BrowserAgentApp().run()
