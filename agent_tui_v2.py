# -*- coding: utf-8 -*-
"""
Browser Agent TUI v2 —— 沿袭 opencode TUI 架构

架构设计（port from opencode packages/tui）：
  ThemeTokens     → 颜色/排版令牌（替代硬编码）
  Part            → 结构化输出单元（TextPart / ThinkingPart / ToolPart）
  MessageBox      → UserMessageBox / AgentMessageBox 渲染组件
  CommandRegistry → 键位 → 命令 → 动作 三层解耦
  ScrollState     → sticky-bottom：底部自动滚，翻阅暂停
  Sidebar / Dialog → 预留接口

用法：python agent_tui_v2.py
"""

import sys
import os
import re
import asyncio
import threading
import queue
import time
import io
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Optional, Dict, List, Any
from enum import Enum, auto

from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit, Window, VSplit, ConditionalContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.styles import Style, merge_styles
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.formatted_text import ANSI, HTML
from prompt_toolkit.keys import Keys
from prompt_toolkit.filters import Condition

sys.path.insert(0, str(Path(__file__).parent))
from agent import BrowserAgent


# ═══════════════════════════════════════════════════════════════
#  1. 主题令牌系统（对标 opencode src/theme/）
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class ThemeTokens:
    """颜色/排版令牌，全局唯一实例，不硬编码色值"""
    # 背景
    background: str = "#0d1117"
    background_panel: str = "#161b22"
    background_element: str = "#21262d"
    background_selected: str = "#30363d"
    # 文字
    text: str = "#c9d1d9"
    text_muted: str = "#8b949e"
    text_link: str = "#58a6ff"
    text_success: str = "#3fb950"
    text_warning: str = "#d29922"
    text_error: str = "#f85149"
    # 边框
    border: str = "#30363d"
    border_active: str = "#58a6ff"
    # Agent 颜色（多角色时区分）
    agent_colors: tuple = ("#58a6ff", "#3fb950", "#d29922", "#f85149", "#bc8cff")
    # 排版
    padding_x: int = 2
    message_padding: int = 2

    def agent_color(self, idx: int = 0) -> str:
        return self.agent_colors[idx % len(self.agent_colors)]

    def to_prompt_style(self) -> Style:
        return Style.from_dict({
            "status-bar": f"bg:{self.background_element} {self.text} bold",
            "output-area": f"bg:{self.background} {self.text}",
            "input-area": f"bg:{self.background_panel} {self.text_link}",
            "sidebar": f"bg:{self.background_element} {self.text_muted}",
        })


theme = ThemeTokens()


# ═══════════════════════════════════════════════════════════════
#  2. Part 架构（对标 opencode Part 类型）
# ═══════════════════════════════════════════════════════════════

class PartType(Enum):
    TEXT = auto()
    THINKING = auto()
    TOOL = auto()
    ERROR = auto()
    DIVIDER = auto()
    STATUS = auto()


@dataclass
class Part:
    """消息中的最小渲染单元"""
    type: PartType
    content: str = ""
    meta: dict = field(default_factory=dict)

    def render(self) -> str:
        """每个 Part 自己知道怎么渲染成带样式的字符串"""
        raise NotImplementedError


@dataclass
class TextPart(Part):
    type: PartType = PartType.TEXT
    def render(self) -> str:
        return self.content


@dataclass
class ThinkingPart(Part):
    type: PartType = PartType.THINKING
    def render(self) -> str:
        return f"  \x1b[90m💭 {self.content}\x1b[0m"


@dataclass
class ToolPart(Part):
    type: PartType = PartType.TOOL
    def render(self) -> str:
        icon = self.meta.get("icon", "▸")
        return f"  \x1b[36m{icon}\x1b[0m {self.content}"


@dataclass
class ErrorPart(Part):
    type: PartType = PartType.ERROR
    def render(self) -> str:
        return f"  \x1b[31m❌ {self.content}\x1b[0m"


@dataclass
class DividerPart(Part):
    type: PartType = PartType.DIVIDER
    def render(self) -> str:
        return "\x1b[90m" + "─" * 46 + "\x1b[0m"


@dataclass
class StatusPart(Part):
    type: PartType = PartType.STATUS
    def render(self) -> str:
        return f"\x1b[32m  ✅ {self.content}\x1b[0m"


# ═══════════════════════════════════════════════════════════════
#  3. 消息盒子（对标 opencode UserMessage / AssistantMessage）
# ═══════════════════════════════════════════════════════════════

@dataclass
class MessageBox:
    """消息容器，包含标题 + 多个 Part + 元数据"""
    agent_color: str = theme.agent_color(0)
    title: str = ""
    parts: List[Part] = field(default_factory=list)
    timestamp: str = ""

    def render(self) -> str:
        raise NotImplementedError


class UserMessageBox(MessageBox):
    """用户消息框：左边框 + agent 颜色编码"""
    def render(self) -> str:
        color = self.agent_color
        # opencode 的 border-left 效果：左边用 ANSI 画竖线模拟
        lines = [f"\x1b[{color.replace('#', '').upper()}m│\x1b[0m \x1b[1m{self.title}\x1b[0m"]
        for p in self.parts:
            for line in p.render().split("\n"):
                lines.append(f"\x1b[{self._ansi_color(color)}m│\x1b[0m {line}")
        return "\n".join(lines)

    @staticmethod
    def _ansi_color(hex_color: str) -> str:
        # 近似：把 #rrggbb 转成 256 色近似（简化）
        r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
        if r == 0x58 and g == 0xa6 and b == 0xff:
            return "38;5;75"  # blue
        if r == 0x3f and g == 0xb9 and b == 0x50:
            return "38;5;78"  # green
        return "38;5;33"


class AgentMessageBox(MessageBox):
    """Agent 回复框：不需要边框，直接渲染 Parts"""
    def render(self) -> str:
        lines = []
        for p in self.parts:
            lines.append(p.render())
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  4. Part 工厂 —— 将 Agent stdout 转为 Part 列表
# ═══════════════════════════════════════════════════════════════

class PartFactory:
    """拦截 agent.py 的 print 输出，转换为结构化 Part 列表"""

    def __init__(self):
        self.parts: List[Part] = []
        self._buf = ""

    def feed(self, text: str) -> None:
        self._buf += text
        if "\n" in self._buf:
            lines = self._buf.split("\n")
            self._buf = lines.pop()
            for line in lines:
                self._process_line(line)

    def flush(self) -> None:
        if self._buf:
            self._process_line(self._buf)
            self._buf = ""

    def _process_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        # 跳过大标题
        if line.startswith("===") or line.startswith("──"):
            return
        # 观察
        if line.startswith("👁"):
            title = re.sub(r'👁\s*\[观察\]\s*', '', line)
            self.parts.append(ToolPart(content=title, meta={"icon": "👁"}))
            return
        # 思考
        if line.startswith("🤔"):
            thought_match = re.search(r'"thought"\s*:\s*"([^"]*)"', line)
            if thought_match:
                self.parts.append(ThinkingPart(content=thought_match.group(1)))
            return
        # 动作
        if line.startswith("🎯"):
            inner = re.sub(r'🎯\s*\[动作\]\s*', '', line)
            inner_simple = re.sub(r'\{[^}]*\}', '', inner).strip().rstrip(':').rstrip(',')
            if inner_simple:
                self.parts.append(ToolPart(content=inner_simple))
            return
        # 启动元信息跳过
        if any(line.startswith(p) for p in ["🚀", "📋", "📺", "🔑", "💡"]):
            return
        # 完成
        if "✅" in line:
            self.parts.append(StatusPart(content="完成"))
            return
        # 结论
        if "📝" in line:
            return
        # 完成分隔线
        if "完成" in line and len(line) < 20:
            return
        # 默认：文本
        self.parts.append(TextPart(content=line))


# ═══════════════════════════════════════════════════════════════
#  5. 命令系统（对标 opencode keymap + command）
# ═══════════════════════════════════════════════════════════════

@dataclass
class Command:
    value: str
    title: str
    category: str = ""
    hidden: bool = False
    run: Optional[Callable[[], None]] = None


class CommandRegistry:
    """全局命令注册表，keybinding → command 解耦"""

    def __init__(self):
        self._commands: Dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        self._commands[cmd.value] = cmd

    def get(self, value: str) -> Optional[Command]:
        return self._commands.get(value)

    def dispatch(self, value: str) -> bool:
        cmd = self.get(value)
        if cmd and cmd.run:
            cmd.run()
            return True
        return False

    def gather(self, *values: str) -> list:
        return [self._commands[v] for v in values if v in self._commands]


# ═══════════════════════════════════════════════════════════════
#  6. 滚动状态（对标 opencode stickyStart="bottom"）
# ═══════════════════════════════════════════════════════════════

class ScrollState:
    """
    核心行为：
    - 用户在底部 → 新内容自动滚到底（sticky）
    - 用户手动翻上去了 → 暂停自动滚动
    - 用户回到最底部 → 恢复自动滚动
    """

    def __init__(self):
        self.at_bottom = True
        self.manual_scroll = False

    def on_scroll_up(self) -> None:
        self.manual_scroll = True
        self.at_bottom = False

    def on_scroll_down(self, is_at_absolute_bottom: bool) -> None:
        if is_at_absolute_bottom:
            self.at_bottom = True
            self.manual_scroll = False

    def should_auto_scroll(self) -> bool:
        return self.at_bottom and not self.manual_scroll


# ═══════════════════════════════════════════════════════════════
#  7. 侧边栏（预留接口，对标 opencode Sidebar）
# ═══════════════════════════════════════════════════════════════

class SidebarState:
    """侧边栏状态机，当前空实现"""
    visible: bool = False
    width: int = 30

    def toggle(self) -> None:
        self.visible = not self.visible

    def render(self) -> str:
        """预留：未来输出会话列表/文件树/TODO 列表"""
        return "\x1b[90m  (sidebar placeholder)\x1b[0m"


# ═══════════════════════════════════════════════════════════════
#  8. 对话框系统（预留接口，对标 opencode Dialog）
# ═══════════════════════════════════════════════════════════════

class DialogStack:
    """模态对话框栈，当前空实现"""
    stack: list = []

    @property
    def is_open(self) -> bool:
        return len(self.stack) > 0

    def push(self, title: str, content: str) -> None:
        self.stack.append({"title": title, "content": content})

    def pop(self) -> None:
        if self.stack:
            self.stack.pop()

    def clear(self) -> None:
        self.stack.clear()

    def render(self) -> str:
        """预留：渲染最顶层的模态对话框"""
        if not self.stack:
            return ""
        top = self.stack[-1]
        return f"\n┌─ {top['title']} ─┐\n│ {top['content']} │\n└───────────┘\n"


# ═══════════════════════════════════════════════════════════════
#  9. 主 TUI 控制器（对标 opencode Session 组件）
# ═══════════════════════════════════════════════════════════════

class AppTUI:
    ACTIVATE_PHRASE = "leafcode"
    QUIT_PHRASE = "home"

    def __init__(self):
        self.mode = "normal"  # "normal" | "agent"
        self.agent: Optional[BrowserAgent] = None
        self.agent_thread: Optional[threading.Thread] = None
        self.running = False
        self.focus_output = False

        # 消息历史
        self.messages: List[MessageBox] = []

        # 子系统
        self.commands = CommandRegistry()
        self.scroll = ScrollState()
        self.sidebar = SidebarState()
        self.dialog = DialogStack()

        # 输出队列（线程安全）
        self.output_queue = queue.Queue()
        self._pending_parts: Optional[PartFactory] = None

    # ── 构建界面 ───────────────────────────────────

    def build(self) -> Application:
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

        self._setup_commands()
        self._welcome()

        kb = merge_key_bindings([
            self._global_keybindings(),
            self._input_keybindings(),
            self._output_keybindings(),
        ])

        # 侧边栏（条件渲染）
        sidebar_window = ConditionalContainer(
            content=Window(
                FormattedTextControl(self._sidebar_content),
                width=30,
                style="class:sidebar",
            ),
            filter=Condition(lambda: self.sidebar.visible),
        )

        root_container = HSplit([
            Window(FormattedTextControl(self._status_text), height=1,
                   style="class:status-bar"),
            VSplit([
                self.output_area,
                sidebar_window,
            ]),
            Window(
                FormattedTextControl(self._dialog_content),
                height=3,
                style="class:status-bar",
            ),
            self.input_area,
        ])

        layout = Layout(root_container, focused_element=self.input_area)
        self.app = Application(
            layout=layout, key_bindings=kb,
            style=theme.to_prompt_style(),
            full_screen=True, mouse_support=True,
        )
        self.running = True
        return self.app

    # ── 欢迎 ───────────────────────────────────────

    def _welcome(self):
        self._push((
            "╔══════════════════════════════════════════════╗\n"
            "║     Browser-Use Agent v2 (opencode-style)     ║\n"
            "║  输入 leafcode 唤醒  │  Tab 切换焦点        ║\n"
            "║  ↑↓/PgUp/PgDn 滚动    │  Ctrl+B 切换侧边栏    ║\n"
            "╚══════════════════════════════════════════════╝\n"
        ))

    # ── 状态栏 ─────────────────────────────────────

    def _status_text(self):
        scroll_status = "▼ 底部" if self.scroll.at_bottom else "▲ 翻阅中"
        sidebar_indicator = "◫" if self.sidebar.visible else "□"
        if self.mode == "agent":
            return (
                f"  🤖 Agent  │  Tab 切换  │  {scroll_status}  "
                f"│  {sidebar_indicator} 侧边栏  │  home 退出  "
            )
            return "  💤 待机  │  输入 leafcode 唤醒  │  Tab 切换焦点  "

    def _sidebar_content(self):
        return self.sidebar.render()

    def _dialog_content(self):
        return self.dialog.render()

    # ── 输出队列（线程安全） ───────────────────────

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
        if not new_text:
            return

        auto_scroll = self.scroll.should_auto_scroll()
        self.output_area.text += new_text

        if auto_scroll:
            self.output_area.buffer.cursor_position = len(self.output_area.text)
            self.scroll.at_bottom = True
        else:
            # 保持在当前位置，不自动滚动
            pass

    # ── 命令注册 ───────────────────────────────────

    def _setup_commands(self):
        reg = self.commands

        reg.register(Command("session.first", "跳到顶部", "Session",
            run=lambda: self._scroll_to(0)))
        reg.register(Command("session.last", "跳到底部", "Session",
            run=lambda: self._scroll_to_end()))
        reg.register(Command("session.page.up", "向上翻页", "Session",
            run=lambda: self._scroll_by(-15)))
        reg.register(Command("session.page.down", "向下翻页", "Session",
            run=lambda: self._scroll_by(15)))
        reg.register(Command("session.line.up", "向上一行", "Session",
            run=lambda: self._scroll_by(-3)))
        reg.register(Command("session.line.down", "向下一行", "Session",
            run=lambda: self._scroll_by(3)))
        reg.register(Command("session.toggle.sidebar", "切换侧边栏", "Session",
            run=lambda: self.sidebar.toggle()))

    def _scroll_to(self, pos: int):
        self.output_area.buffer.cursor_position = pos
        if pos == 0:
            self.scroll.on_scroll_up()

    def _scroll_to_end(self):
        pos = len(self.output_area.text)
        self.output_area.buffer.cursor_position = pos
        self.scroll.on_scroll_down(True)

    def _scroll_by(self, amount: int):
        cur = self.output_area.buffer.cursor_position
        new = max(0, min(len(self.output_area.text), cur + amount))
        self.output_area.buffer.cursor_position = new
        if amount < 0 and cur > new:
            self.scroll.on_scroll_up()
        if amount > 0 and new >= len(self.output_area.text) - 5:
            self.scroll.on_scroll_down(True)

    # ── 按键绑定 ───────────────────────────────────

    def _global_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("c-c")
        def _(event):
            self.running = False
            event.app.exit()

        @kb.add("tab")
        def _(event):
            self.focus_output = not self.focus_output
            if self.focus_output:
                event.app.layout.focus(self.output_area)
            else:
                event.app.layout.focus(self.input_area)

        @kb.add("c-b")
        def _(event):
            self.commands.dispatch("session.toggle.sidebar")

        return kb

    def _input_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("enter")
        def _(event):
            text = self.input_area.text.strip()
            self.input_area.text = ""
            if not text:
                return
            self._on_user_input(text)

        @kb.add("escape")
        def _(event):
            self.focus_output = True
            event.app.layout.focus(self.output_area)

        return kb

    def _output_keybindings(self) -> KeyBindings:
        kb = KeyBindings()

        @kb.add("up")
        def _(event):
            self.commands.dispatch("session.line.up")
        @kb.add("down")
        def _(event):
            self.commands.dispatch("session.line.down")
        @kb.add("pageup")
        def _(event):
            self.commands.dispatch("session.page.up")
        @kb.add("pagedown")
        def _(event):
            self.commands.dispatch("session.page.down")
        @kb.add("home")
        def _(event):
            self.commands.dispatch("session.first")
        @kb.add("end")
        def _(event):
            self.commands.dispatch("session.last")
        @kb.add("escape")
        def _(event):
            self.focus_output = False
            event.app.layout.focus(self.input_area)

        return kb

    # ── 用户输入处理 ───────────────────────────────

    def _on_user_input(self, text: str):
        # 渲染用户消息盒
        user_box = UserMessageBox(
            agent_color=theme.agent_color(0),
            title=text,
            parts=[TextPart(content=text)],
            timestamp=time.strftime("%H:%M"),
        )
        self._push("\n" + user_box.render() + "\n\n")

        if self.mode == "normal":
            self._handle_normal(text)
        elif self.mode == "agent":
            self._handle_agent(text)

    def _handle_normal(self, text: str):
        if text.strip().lower() == self.ACTIVATE_PHRASE.lower():
            self.mode = "agent"
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                self._push("⚠️  未设置 DEEPSEEK_API_KEY\n")
                self.mode = "normal"
                return
            self.agent = BrowserAgent(api_key=api_key, headless=True, on_output=None)
            self._push("✅ Agent 就绪。输入任务开始执行。\n")
            self._push('   💡 加 "后台" 可静默运行\n\n')
        else:
            self._push("未知指令\n")

    def _handle_agent(self, text: str):
        if text.strip().lower() == self.QUIT_PHRASE:
            self.mode = "normal"
            box = DividerPart()
            self._push(box.render() + "\n🔒 Agent 已退出\n\n")
            return

        if self.agent_thread and self.agent_thread.is_alive():
            self._push("⏳ 上一个任务还在执行中...\n")
            return

        auto_headless, clean_task = BrowserAgent.detect_mode(text)
        actual_task = clean_task if auto_headless else text
        self.agent.headless = auto_headless

        if auto_headless:
            self._push("🫥 静默模式\n")

        self._pending_parts = PartFactory()
        self.agent_thread = threading.Thread(
            target=self._run_agent_task,
            args=(actual_task,), daemon=True,
        )
        self.agent_thread.start()

    def _run_agent_task(self, task: str):
        """在线程中运行 Agent，输出转为结构化 Part"""
        factory = PartFactory()
        old_stdout = sys.stdout
        sys.stdout = _FactoryStream(factory)
        try:
            self.agent.run(task)
        except Exception as e:
            factory.feed(f"\n❌ 执行出错: {e}\n")
        finally:
            sys.stdout = old_stdout
            factory.flush()
            # 构建 AgentMessageBox
            agent_box = AgentMessageBox(parts=factory.parts)
            self._push(agent_box.render() + "\n")
            self._push(DividerPart().render() + "\n✅ 完成\n\n")


class _FactoryStream(io.TextIOBase):
    """将 agent print 输出定向到 PartFactory"""
    def __init__(self, factory: PartFactory):
        self.factory = factory

    def write(self, s: str):
        self.factory.feed(s)

    def flush(self):
        self.factory.flush()


# ═══════════════════════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════════════════════

async def _periodic_flush(tui: AppTUI):
    while tui.running:
        tui._flush_output()
        await asyncio.sleep(0.25)


async def _main():
    tui = AppTUI()
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
