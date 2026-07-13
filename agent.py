# Browser-Use Agent Demo —— 基于 DeepSeek + Playwright 的自主浏览器智能体
# 核心概念：Agent = LLM 推理 + 工具调用 + 观察-思考-行动循环

import os
import json
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from openai import OpenAI
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# 自动加载 .env 文件（如果存在）
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


class AgentMode(str, Enum):
    INFORM = "inform"    # 搜索 → 提取信息 → 总结 → 关闭浏览器
    OPERATE = "operate"  # 理解意图 → 导航/登录 → 操作 → 保留浏览器给用户


def _get_credentials(site: str) -> dict:
    """从环境变量读取网站凭证"""
    site_upper = site.upper()
    return {
        "user": os.environ.get(f"{site_upper}_USER", ""),
        "pass": os.environ.get(f"{site_upper}_PASS", ""),
    }


# ═══════════════════════════════════════════
#  工具层 —— Agent 可调用的浏览器操作
# ═══════════════════════════════════════════

class BrowserTools:
    """封装浏览器操作，每个方法都是一个 Agent 可调用的工具"""

    def __init__(self, page):
        self.page = page
        self._last_clickable_selector = self.CLICKABLE_SELECTOR

    def navigate(self, url: str) -> str:
        """导航到指定URL"""
        if not url.startswith('http'):
            url = 'https://' + url
        self.page.goto(url, timeout=15000)
        return f"已导航到: {url}"

    def get_state(self) -> str:
        """获取页面状态，使用 locator API（不依赖 page.evaluate）"""
        try:
            title = self.page.title()
            url = self.page.url

            # 页面类型检测（用 locator 替代 evaluate）
            is_result = self.page.locator('h3 a, .result a, .c-container a').count() > 0
            has_search_input = self.page.locator(self.INPUT_SELECTOR).locator("visible=true").count() > 0
            if is_result:
                page_type = '搜索结果页'
            elif has_search_input:
                page_type = '搜索首页'
            else:
                page_type = '普通网页'

            # 搜索框状态
            input_lines = []
            inputs = self.page.locator(self.INPUT_SELECTOR).locator("visible=true")
            for i in range(min(inputs.count(), 6)):
                el = inputs.nth(i)
                try:
                    val = el.input_value() or ''
                    ph = el.get_attribute('placeholder') or ''
                    name = el.get_attribute('name') or el.get_attribute('id') or ''
                    input_lines.append(f'  [{i}] name="{name}" 当前值="{val[:30]}" 提示="{ph}"')
                except Exception:
                    pass
            input_values = '\n'.join(input_lines)

            # 可交互元素
            is_search_result = (page_type == '搜索结果页')
            if is_search_result:
                clickable_selector = 'a[href]'
                nav_filter = True
            else:
                clickable_selector = self.CLICKABLE_SELECTOR
                nav_filter = False
            self._last_clickable_selector = clickable_selector

            element_lines = []
            els = self.page.locator(clickable_selector).locator("visible=true")
            count = els.count()
            for i in range(min(count, 60)):
                el = els.nth(i)
                try:
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                    raw = (el.text_content() or '').strip()
                    text = raw[:60]
                    href = el.get_attribute('href') or ''
                    if nav_filter and tag == 'a':
                        if len(raw) < 10 and 'item' not in href and 'article' not in href:
                            continue
                        if raw in ('新闻','图片','视频','地图','贴吧','文库','知道','百科','更多','首页','登录','注册'):
                            continue
                    if tag == 'a' and href:
                        label = '【链接】'
                    elif tag == 'button':
                        label = '【按钮】'
                    elif tag in ('input', 'textarea'):
                        label = '【输入框】'
                    else:
                        label = f'<{tag}>'
                    if text or href:
                        element_lines.append(f'  [{i}] {label} {text}' +
                            (f' → {href[:40]}' if (tag == 'a' and href) else ''))
                except Exception:
                    continue
            interactives = '\n'.join(element_lines)

            # 页面文本
            try:
                body_text = self.page.locator('body').inner_text()[:3000]
            except Exception:
                body_text = '(无)'

            hint = "\n⚠️ 搜索结果页！点击链接查看详情！\n" if is_search_result else ""

            state = f"""【页面类型】{page_type}{hint}
【标题】{title}
【URL】{url}
【搜索框状态】
{input_values if input_values else '(无)'}
【可交互元素】
{interactives if interactives else '(无)'}
【页面文本】
{body_text}
"""
            return state
        except Exception as e:
            return f"获取页面状态失败: {e}"

    # 统一选择器
    INPUT_SELECTOR = 'input[type="text"], input[type="search"], input:not([type]):not([hidden]), textarea'
    CLICKABLE_SELECTOR = 'a[href], button, input[type="text"], input[type="search"], input:not([type]):not([hidden]), textarea, select'

    def click_element(self, index: int) -> str:
        """点击/导航到指定索引的元素"""
        try:
            selector = self._last_clickable_selector
            nav_filter = (selector == 'a[href]')
            loc = self.page.locator(selector).locator("visible=true")
            count = loc.count()
            vi = 0
            for i in range(count):
                el = loc.nth(i)
                try:
                    tag = el.evaluate("el => el.tagName.toLowerCase()")
                    href = el.get_attribute('href') or ''
                    if nav_filter and tag == 'a':
                        raw = (el.text_content() or '').strip()
                        if len(raw) < 10 and 'item' not in href and 'article' not in href:
                            continue
                        if raw in ('新闻','图片','视频','地图','贴吧','文库','知道','百科','更多','首页','登录','注册'):
                            continue
                except Exception:
                    continue
                if vi == index:
                    el.scroll_into_view_if_needed()
                    # 搜索结果页上的链接：直接用 href 导航（百度会拦截点击事件）
                    if nav_filter and tag == 'a' and href and href.startswith('http'):
                        self.page.goto(href, timeout=15000)
                        self.page.wait_for_timeout(1500)
                        return f"已打开链接 [{index}]: {href[:50]}"
                    el.click()
                    self.page.wait_for_timeout(1500)
                    return f"已点击元素 [{index}]"
                vi += 1
            return f"索引 {index} 超出可见元素范围"
        except Exception as e:
            return f"点击失败: {e}"

    def type_text(self, index: int, text: str) -> str:
        """在可见输入框中输入：fill 清空+填入 → Enter 提交"""
        try:
            selector = self.INPUT_SELECTOR
            locator = self.page.locator(selector).locator("visible=true")
            count = locator.count()
            if index >= count:
                return f"输入元素索引 {index} 无效（共 {count} 个可见输入框）"

            target = locator.nth(index)
            target.scroll_into_view_if_needed()
            target.click()
            self.page.wait_for_timeout(300)

            target.fill("")
            target.fill(text)
            self.page.wait_for_timeout(200)

            target.press("Enter")
            self.page.wait_for_timeout(1500)

            return f"已输入: {text} → 已提交搜索"
        except Exception as e:
            return f"输入失败: {e}"

    def press_key(self, key: str) -> str:
        """按下按键（如 Enter、Escape、ArrowDown）"""
        self.page.keyboard.press(key)
        self.page.wait_for_timeout(1000)
        return f"已按下: {key}"

    def scroll(self, direction: str, amount: int = 500) -> str:
        """滚动页面"""
        if direction == 'down':
            self.page.evaluate(f'window.scrollBy(0, {amount})')
        elif direction == 'up':
            self.page.evaluate(f'window.scrollBy(0, -{amount})')
        self.page.wait_for_timeout(500)
        return f"已向{direction}滚动 {amount}px"


# ═══════════════════════════════════════════
#  Agent 核心 —— ReAct 循环
# ═══════════════════════════════════════════

class BrowserAgent:
    """
    浏览器智能体
    循环：观察 → 思考 → 行动 → 观察 → ...
    终止条件：Agent 选择 done 动作，或达到最大步数
    """

    SYSTEM_PROMPT = """你是一个浏览器智能体，能理解用户意图并自主操作浏览器完成任务。

## 你的能力
你可以使用以下工具，每次选择一个执行：
- navigate(url)      — 打开网页
- click(index)        — 点击可交互元素（按页面状态中的编号）
- type(index, text)   — 在输入框输入文字（会自动清空旧内容 + 搜索框自动提交）
- press(key)          — 按键（Enter / Escape / ArrowDown 等）
- scroll(direction)   — 滚屏 (down / up)
- done(summary)       — 任务完成

## 回复格式
严格返回 JSON：
```json
{
  "thought": "我对当前页面的理解和下一步计划",
  "action": "navigate | click | type | press | scroll | done",
  "params": { ... }
}
```

## 核心原则

### 1. 先理解意图
- 用户说"搜索五条悟"→ 意图是搜索并了解信息
- 用户说"打开知乎"→ 意图是访问特定网站

### 2. 感知页面状态
- 看页面标题和URL判断"我在哪"
- 如果已经在正确的搜索结果页 → 直接点击结果链接，不要 navigate 回去！

### 3. 自纠正
- 如果操作后页面没变化 → 刚才操作没生效，换方法
- 连续2次同样操作 → 必定有问题，立刻换策略

### 4. 深入探索（重要！）
- 搜索结果页不是终点！必须点击1-2个最相关的链接进入具体页面
- 优先点击百科类链接（百度百科、维基百科等）
- 阅读页面内容后再用 done 总结，summary 必须包含从页面中提取的具体信息
- 千万不要只汇报"找到了搜索结果"就结束

### 5. 操作模式（operate mode）
当以 operate 模式运行时：
- 你的目标不是提取信息，而是帮用户完成操作（如打开B站视频、登录账号）
- 如果有账号密码（由系统提供），先登录再操作
- 完成操作后 done，summary 说明已完成的操作
- done 后浏览器保留，不关闭窗口——用户继续使用"""

    HEADLESS_KEYWORDS = ["后台", "静默", "不显示", "隐藏", "headless", "无头", "安静", "无窗口", "静默运行"]

    def __init__(self, api_key: str, headless: bool = False, on_output=None):
        self.llm = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1"
        )
        self.headless = headless
        self.history = []  # 对话历史
        self.on_output = on_output  # 输出回调
        self.abort = False          # 中断标志

    @classmethod
    def detect_mode(cls, task: str) -> tuple[bool, str]:
        """从任务描述中检测用户意图的浏览器模式，返回 (是否为headless, 清理后的任务)"""
        task_lower = task.lower()
        for kw in cls.HEADLESS_KEYWORDS:
            if kw in task:
                # 移除关键词，保留任务主体
                clean = task.replace(kw, "").strip().rstrip("，,。.")
                return True, clean
        return False, task

    def _get_llm_response(self, page_state: str, task: str) -> dict:
        """调用 DeepSeek，返回解析后的 JSON"""
        messages = [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": f"我的目标是：{task}\n\n当前页面状态：\n{page_state}"}
        ]

        # 保留最近 4 轮历史，防止 context 过长
        for h in self.history[-8:]:
            messages.insert(1, h)

        response = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.1,
            max_tokens=800
        )

        content = response.choices[0].message.content
        return self._extract_json(content)

    def _extract_json(self, content: str) -> dict:
        """从 LLM 回复中提取 JSON"""
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)
        elif '{' in content:
            content = content[content.index('{'):content.rindex('}')+1]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}

    def run(self, task: str, mode: AgentMode = AgentMode.INFORM, force_headless: bool = None):
        """主循环：启动浏览器 → ReAct 循环 → 返回结果
        mode: inform=提取信息后关闭, operate=操作完成后保留浏览器"""
        # 模式判断
        auto_headless, clean_task = self.detect_mode(task)
        if force_headless is not None:
            self.headless = force_headless
        elif auto_headless:
            self.headless = True
            task = clean_task

        mode_icon = "🫥 静默" if self.headless else "🖥️ 显式"
        print("=" * 60)
        print(f"🚀 Agent 启动")
        print(f"🎯 模式: {mode.value}  {mode_icon}")
        print(f"📋 任务: {task}")
        print("=" * 60)

        # ── 第0步：意图理解 ──
        plan_prompt = f"""用户任务：「{task}」
运行模式：{mode.value}

请先理解用户意图，规划执行步骤。返回 JSON：
```json
{{
  "intent": "用户想要做什么（1句话）",
  "steps": ["步骤1", "步骤2", "步骤3"],
  "first_action": "navigate | click | type | press | scroll | done",
  "first_params": {{}}
}}
```
如果用户要求搜索，first_action 应该是 navigate 到搜索引擎首页。
如果用户要求打开特定网站，first_action 应该 navigate 到该网站。
如果用户要求登录，系统会提供凭证信息。"""
        plan_resp = self.llm.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": plan_prompt}],
            temperature=0.1,
            max_tokens=500
        )
        plan_content = plan_resp.choices[0].message.content
        plan_json = self._extract_json(plan_content)
        intent = plan_json.get("intent", task)
        steps = plan_json.get("steps", [])
        first_action = plan_json.get("first_action", "navigate")
        first_params = plan_json.get("first_params", {"url": "https://www.bing.com"})
        print(f"🎯 意图: {intent}")
        if steps:
            print(f"📝 计划: {' → '.join(steps[:5])}")

        p = sync_playwright().start()
        try:
            # 反爬配置：headless 模式需要额外伪装，否则搜索引擎会拦截
            launch_args = [
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-infobars',
                '--window-size=1280,800',
            ]
            if self.headless:
                launch_args.extend([
                    '--disable-gpu',
                    '--hide-scrollbars',
                ])

            browser = p.chromium.launch(headless=self.headless, args=launch_args)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            )
            page = context.new_page()

            # 隐藏 webdriver 标记（headless 关键反爬）
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
                window.chrome = {runtime: {}};
            """)

            tools = BrowserTools(page)

            # 执行计划的第一步（初始导航），兜底用百度
            fallback_url = "https://www.bing.com"
            if first_action == "navigate":
                url = first_params.get("url", fallback_url)
                if not url.startswith("http"):
                    url = "https://" + url
                tools.navigate(url)
            else:
                tools.navigate(fallback_url)
            page.wait_for_timeout(1500)

            max_steps = 10
            last_actions = []
            stuck_count = 0
            for step in range(1, max_steps + 1):
                if self.abort:
                    print("\n⏹ 用户中断")
                    return "用户中断"

                print(f"\n{'─' * 40}")
                print(f"📍 第 {step}/{max_steps} 步")

                # 1. 感知：获取页面语义状态
                state = tools.get_state()
                print(f"👁 [感知] {page.title()}")

                # 2. 决策：LLM 理解当前状态后选择下一步
                stuck_hint = ""
                if stuck_count >= 2:
                    stuck_hint = (
                        f"\n⚠️ 你已经连续{stuck_count}次操作没有进展！"
                        "请尝试完全不同的策略："
                        "- 如果一直停留在结果页，先 navigate 回搜索引擎首页再搜索"
                        "- 如果输入没反应，检查搜索框索引是否正确"
                        "- 也可以尝试 navigate 到另一个搜索引擎"
                    )

                result = self._get_llm_response(state + stuck_hint, task)
                action = result.get("action", "done")
                thought = result.get("thought", "")
                params = result.get("params", {})

                print(f"💭 {thought}")
                print(f"🎯 {action}: {json.dumps(params, ensure_ascii=False)}")

                # 重复检测
                action_key = f"{action}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
                last_actions.append(action_key)
                if len(last_actions) > 4:
                    last_actions.pop(0)
                if len(last_actions) >= 2 and last_actions[-1] == last_actions[-2]:
                    stuck_count += 1
                else:
                    stuck_count = 0

                self.history.append({"role": "user", "content": f"状态: {state[:400]}"})
                self.history.append({"role": "assistant", "content": json.dumps(result, ensure_ascii=False)})

                # 3. 执行
                if action == "done":
                    summary = params.get("summary", "任务完成")
                    print(f"\n✅ Agent 已完成")
                    print(f"📝 结论：{summary}")
                    if mode == AgentMode.OPERATE:
                        print("🔓 操作模式：浏览器窗口保留")
                    return summary

                elif action == "navigate":
                    url = params.get("url", "")
                    if url and not url.startswith("http"):
                        url = "https://" + url
                    print(tools.navigate(url or "https://www.bing.com"))
                    page.wait_for_timeout(1200)

                elif action == "click":
                    print(tools.click_element(params.get("index", 0)))

                elif action == "type":
                    print(tools.type_text(params.get("index", 0), params.get("text", "")))

                elif action == "press":
                    print(tools.press_key(params.get("key", "Enter")))

                elif action == "scroll":
                    print(tools.scroll(params.get("direction", "down"), params.get("amount", 500)))

                else:
                    print(f"未知动作: {action}")

                page.wait_for_timeout(500)

            print(f"\n⏰ 已达最大步数 {max_steps}，Agent 终止")
            if mode != AgentMode.OPERATE:
                browser.close()
            else:
                print("🔓 操作模式：浏览器窗口保留")
            return "达到最大步数，任务可能未完成"

        except Exception as e:
            print(f"\n❌ 异常: {e}")
            if mode != AgentMode.OPERATE:
                browser.close()
            raise
        finally:
            if mode != AgentMode.OPERATE:
                p.stop()


# ═══════════════════════════════════════════
#  运行入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        api_key = input("请输入 DeepSeek API Key: ").strip()

    print("\n" + "=" * 60)
    print("  Browser-Use Agent Demo")
    print("  基于 DeepSeek + Playwright 的浏览器智能体")
    print("=" * 60)
    print("\n📺 模式说明:")
    print("  显式模式：浏览器窗口可见（默认），适合观察 Agent 操作过程")
    print("  静默模式：在任务中加入 '后台/静默/headless' 自动切换为后台运行")
    print("\n示例任务:")
    print("  1. 帮我查一下今天北京天气")
    print("  2. 打开百度百科，查找'人工智能'的定义")
    print("  3. 后台搜索 Python asyncio 教程，总结前3个结果  ← 含'后台'自动静默")
    print()

    task = input("请输入任务（回车使用默认）: ").strip()
    if not task:
        task = "用百度搜索'大语言模型 Agent 原理'，点开第一个搜索结果，告诉我文章的核心内容是什么"

    # 自动检测任务中的模式关键词
    auto_headless, clean_task = BrowserAgent.detect_mode(task)
    if auto_headless:
        headless = True
        task = clean_task
        print("\n🔍 检测到静默关键词，将使用后台模式运行...\n")
    else:
        headless = False

    agent = BrowserAgent(api_key=api_key, headless=headless)
    agent.run(task)
