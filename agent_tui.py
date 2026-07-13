# -*- coding: utf-8 -*-
"""
Browser Agent TUI —— opencode 风格终端聊天界面

用法：python agent_tui.py
输入 ilovemonsterhunter 进入 Agent 模式，输入 home 退出
Tab 切换焦点（浏览历史 / 输入），鼠标滚轮翻页
"""

import sys
import io
import os
import re
import asyncio
import threading
import queue
from pathlib import Path

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea, Frame, Box
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.styles import Style
from prompt_toolkit.mouse_events import MouseEventType

sys.path.insert(0, str(Path(__file__).parent))
from agent import BrowserAgent

NORMAL = "normal"
AGENT = "agent"

STYLE = Style.from_dict({
    "status-bar":      "bg:#2c5f8a #ffffff bold",
    "output-area":     "bg:#0d1117 #c9d1d9",
    "input-area":      "bg:#161b22 #58a6ff",
    "input-area-agent": "bg:#161b22 #3fb950",
    "output-scroll":   "bg:#0d1117 #484f58",
})


class AgentTUI:
    ACTIVATE_PHRASE = "helloworld"
    QUIT_PHRASE = "home"

    def __init__(self):
        self.mode = NORMAL
        self.agent = None
        self.output_queue = queue.Queue()
        self.agent_thread = None
        self.running = False
        self.focus_output = False  # True = 焦点在输出区（可滚动），False = 输入区

    # ── 界面构建 ───────────────────────────────────

    def build(self) -> Application:
        # 输出区域（可获取焦点以支持键盘滚动 + 鼠标滚轮）
        self.output_area = TextArea(
            text="", read_only=True, scrollbar=True,
            focusable=True, wrap_lines=True,
            style="class:output-area",
        )

        self.input_area = TextArea(
            height=1, prompt="> ", multiline=False,
            wrap_lines=False, focusable=True,
            style="class:input-area",
        )

        self._welcome()

        kb = KeyBindings()

        # ── 全局按键 ──
        @kb.add("c-c")
        def _(event):
            self.running = False
            event.app.exit()

        @kb.add("tab")
        def toggle_focus(event):
            self.focus_output = not self.focus_output
            if self.focus_output:
                event.app.layout.focus(self.output_area)
                self.input_area.style = "class:input-area"
            else:
                event.app.layout.focus(self.input_area)
                self.input_area.style = "class:input-area-agent" if self.mode == AGENT else "class:input-area"

        # ── 输入区按键 ──
        input_kb = KeyBindings()

        @input_kb.add("enter")
        def handle_enter(event):
            text = self.input_area.text.strip()
            self.input_area.text = ""
            if not text:
                return
            self._user_msg(text)
            if self.mode == NORMAL:
                self._handle_normal(text)
            elif self.mode == AGENT:
                self._handle_agent(text)

        @input_kb.add("escape")
        def esc_to_output(event):
            self.focus_output = True
            event.app.layout.focus(self.output_area)

        # ── 输出区按键（滚动）──
        output_kb = KeyBindings()

        @output_kb.add("up")
        def scroll_up(event):
            self.output_area.buffer.cursor_up(3)
        @output_kb.add("down")
        def scroll_down(event):
            self.output_area.buffer.cursor_down(3)
        @output_kb.add("pageup")
        def page_up(event):
            self.output_area.buffer.cursor_up(15)
        @output_kb.add("pagedown")
        def page_down(event):
            self.output_area.buffer.cursor_down(15)
        @output_kb.add("home")
        def go_top(event):
            self.output_area.buffer.cursor_position = 0
        @output_kb.add("end")
        def go_bottom(event):
            self.output_area.buffer.cursor_position = len(self.output_area.text)
        @output_kb.add("escape")
        def back_to_input(event):
            self.focus_output = False
            event.app.layout.focus(self.input_area)

        root_container = HSplit([
            Window(FormattedTextControl(self._status_text), height=1,
                   style="class:status-bar"),
            self.output_area,
            self.input_area,
        ])

        layout = Layout(root_container, focused_element=self.input_area)

        self.app = Application(
            layout=layout,
            key_bindings=merge_key_bindings([kb, input_kb, output_kb]),
            style=STYLE,
            full_screen=True,
            mouse_support=True,
        )
        self.running = True
        return self.app

    # ── 消息输出 ───────────────────────────────────

    def _welcome(self):
        self._push("""╔══════════════════════════════════════════════╗
║        Browser-Use Agent                      ║
║   输入 helloworld 唤醒 Agent                   ║
║   Tab 切换焦点  │  ↑↓/PgUp/PgDn 滚动历史       ║
╚══════════════════════════════════════════════╝
""")

    def _user_msg(self, text: str):
        w = 50
        lines = [text[i:i+w] for i in range(0, len(text), w)]
        indent = " " * 4
        box = "╭─ You ─" + "─" * (w - 6) + "╮\n"
        for line in lines:
            box += f"│ {line:<{w-2}} │\n"
        box += "╰" + "─" * (w + 1) + "╯\n"
        self._push(box)

    def _status_text(self):
        if self.mode == AGENT:
            return "  🤖 Agent  │  Tab 切换  │  ↑↓ 滚动  │  Esc 回输入  │  home 退出  "
        else:
            return "  💤 待机  │  输入 helloworld 唤醒 Agent  │  Tab 切换焦点  "

    def _push(self, text: str):
        self.output_queue.put(text)

    def _flush_output(self):
        if not hasattr(self, 'output_area') or not self.output_area:
            return
        new_text = ""
        while not self.output_queue.empty():
            try:
                new_text += self.output_queue.get_nowait()
            except queue.Empty:
                break
        if new_text:
            self.output_area.text += new_text
            # 如果焦点在输入区，自动滚到底部
            if not self.focus_output:
                self.output_area.buffer.cursor_position = len(self.output_area.text)

    # ── 模式处理 ───────────────────────────────────

    def _handle_normal(self, text: str):
        if text.strip().lower() == self.ACTIVATE_PHRASE.lower():
            self.mode = AGENT
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                self._push("⚠️  未设置 DEEPSEEK_API_KEY，请检查 .env 文件\n")
                self.mode = NORMAL
                return
            self.agent = BrowserAgent(api_key=api_key, headless=True)
            self.input_area.style = "class:input-area-agent"
            self._push("✅ Agent 已就绪。输入自然语言任务开始执行。\n")
            self._push('   💡 任务前加 "后台" 可不弹出浏览器窗口\n\n')
        else:
            self._push(f"未知指令\n")

    def _handle_agent(self, text: str):
        if text.strip().lower() == self.QUIT_PHRASE:
            self.mode = NORMAL
            self.input_area.style = "class:input-area"
            self._push("━" * 46 + "\n🔒 Agent 已退出\n\n")
            return

        if self.agent_thread and self.agent_thread.is_alive():
            self._push("⏳ 上一个任务还在执行中...\n")
            return

        auto_headless, clean_task = BrowserAgent.detect_mode(text)
        actual_task = clean_task if auto_headless else text
        headless = auto_headless

        if headless:
            self._push("🫥 静默模式\n")

        self.agent.headless = headless
        self.agent_thread = threading.Thread(
            target=self._run_agent_task,
            args=(actual_task,), daemon=True,
        )
        self.agent_thread.start()

    def _run_agent_task(self, task: str):
        old_stdout = sys.stdout
        sys.stdout = _AgentFormatter(self.output_queue)
        try:
            self.agent.run(task)
        except Exception as e:
            self._push(f"\n❌ 执行出错: {e}\n")
        finally:
            sys.stdout = old_stdout
            self._push("━" * 46 + "\n✅ 完成\n\n")


# ── Agent 输出格式化 ──────────────────────────────

class _AgentFormatter(io.TextIOBase):
    """拦截 agent print，精简为 opencode 风格"""

    def __init__(self, q: queue.Queue):
        self.q = q
        self._buf = ""

    def write(self, s: str):
        self._buf += s
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            self._buf = lines.pop()
            for line in lines:
                self._process_line(line)

    def flush(self):
        if self._buf:
            self._process_line(self._buf)
            self._buf = ""

    def _process_line(self, line: str):
        line = line.strip()
        if not line:
            return
        # 跳过大标题
        if line.startswith("==="):
            return
        if line.startswith("──") or line.startswith("——"):
            return
        # 步骤
        if re.match(r'📍\s*第\s*\d+', line):
            return
        # 观察
        if line.startswith("👁"):
            title = re.sub(r'👁\s*\[观察\]\s*', '', line)
            self.q.put(f"  {title}\n")
            return
        # 思考
        if line.startswith("🤔"):
            thought_match = re.search(r'"thought"\s*:\s*"([^"]*)"', line)
            if thought_match:
                self.q.put(f"  💭 {thought_match.group(1)}\n")
            return
        # 动作 → 精简
        if line.startswith("🎯"):
            inner = re.sub(r'🎯\s*\[动作\]\s*', '', line)
            inner_simple = re.sub(r'\{[^}]*\}', '', inner).strip().rstrip(':').rstrip(',')
            if inner_simple:
                self.q.put(f"  ▸ {inner_simple}\n")
            return
        # 启动/元信息跳过
        if any(line.startswith(p) for p in ["🚀", "📋", "📺", "🔑", "💡"]):
            return
        # 完成
        if "✅" in line:
            self.q.put(f"\n  ✅ 任务完成\n")
            return
        # 结论
        if "📝" in line:
            return
        # 超时
        if "已达最大步数" in line:
            self.q.put(f"\n  ⏰ {line}\n")
            return
        # 默认
        self.q.put(f"  {line}\n")


# ── 启动 ──────────────────────────────────────────

async def _periodic_flush(tui: AgentTUI):
    while tui.running:
        tui._flush_output()
        await asyncio.sleep(0.25)


async def _main():
    tui = AgentTUI()
    app = tui.build()
    app.create_background_task(_periodic_flush(tui))
    await app.run_async()


if __name__ == "__main__":
    print("\n" * 2)
    try:
        asyncio.run(_main())
    except (SystemExit, KeyboardInterrupt):
        pass
    print("\n再见！")
