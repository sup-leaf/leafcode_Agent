from __future__ import annotations

import hashlib
import json
import time
from typing import Callable

from playwright.sync_api import sync_playwright

from .models import InteractiveElement, PageSnapshot, ToolResult


class BrowserSession:
    """管理可复用的浏览器、上下文和当前页面生命周期。"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.playwright = self.browser = self.context = self.page = None
        self.current_snapshot: PageSnapshot | None = None

    def start(self, headless: bool | None = None):
        if headless is not None:
            self.headless = headless
        if self.page and not self.page.is_closed():
            return self.page
        self.playwright = sync_playwright().start()
        args = ["--disable-blink-features=AutomationControlled", "--disable-infobars", "--window-size=1280,800"]
        if self.headless:
            args.extend(["--disable-gpu", "--hide-scrollbars"])
        self.browser = self.playwright.chromium.launch(headless=self.headless, args=args)
        self.context = self.browser.new_context(viewport={"width": 1280, "height": 800})
        self.page = self.context.new_page()
        self.page.set_default_timeout(15_000)
        return self.page

    def set_page(self, page) -> None:
        self.page = page

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
        finally:
            if self.playwright:
                self.playwright.stop()
            self.playwright = self.browser = self.context = self.page = None
            self.current_snapshot = None


class BrowserTools:
    """基于页面快照执行操作；元素 ID 仅在当前快照内有效。"""

    def __init__(self, page, context=None, on_page_change: Callable | None = None):
        self.page = page
        self.context = context
        self.on_page_change = on_page_change
        self._snapshot_sequence = 0
        self._page_count_before = 0
        self._elements: dict[str, InteractiveElement] = {}
        self.current_snapshot: PageSnapshot | None = None

    def observe(self) -> PageSnapshot:
        self._snapshot_sequence += 1
        snapshot_id = f"s{self._snapshot_sequence}"
        raw = self.page.evaluate("""({snapshotId}) => {
            const selector = 'a[href], button, input, textarea, select, [role="button"], [role="link"]';
            const visible = (el) => { const s = getComputedStyle(el), r = el.getBoundingClientRect(); return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0; };
            const clean = (value, limit = 160) => (value || '').replace(/\\s+/g, ' ').trim().slice(0, limit);
            const items = Array.from(document.querySelectorAll(selector)).filter(visible).slice(0, 80).map((el, index) => {
                const id = `el-${snapshotId}-${index}`;
                el.setAttribute('data-leafcode-element', id);
                return { id, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', text: clean(el.innerText || el.value || el.getAttribute('aria-label') || el.title), href: el.href || '', type: el.type || '', name: el.name || '', placeholder: el.placeholder || '', value: clean(el.value), disabled: !!el.disabled };
            });
            return { title: document.title, url: location.href, text: clean(document.body?.innerText, 3000), scrollY: Math.round(scrollY), items };
        }""", {"snapshotId": snapshot_id})
        elements = tuple(
            InteractiveElement(item["id"], item["role"] or item["tag"], item["text"], f'[data-leafcode-element="{item["id"]}"]',
                               "type" if item["tag"] in ("input", "textarea") else "click",
                               {key: str(item.get(key, "")) for key in ("href", "type", "name", "placeholder", "value") if item.get(key)})
            for item in raw["items"] if not item["disabled"]
        )
        content = json.dumps({"url": raw["url"], "title": raw["title"], "text": raw["text"], "scrollY": raw["scrollY"], "elements": [(e.id, e.text, e.attributes.get("value", "")) for e in elements]}, ensure_ascii=False)
        snapshot = PageSnapshot(snapshot_id, time.time(), raw["url"], raw["title"], raw["text"], elements, hashlib.sha256(content.encode()).hexdigest())
        self.current_snapshot, self._elements = snapshot, {element.id: element for element in elements}
        return snapshot

    @staticmethod
    def format_snapshot(snapshot: PageSnapshot) -> str:
        lines = [f"【页面快照】{snapshot.id}", f"【标题】{snapshot.title}", f"【URL】{snapshot.url}", "【可交互元素】"]
        lines.extend(f"  [{e.id}] {e.role} {e.text[:60]} {e.attributes.get('href', '')[:60]}" for e in snapshot.elements)
        return "\n".join([*lines, "【页面文本】", snapshot.text_excerpt])

    def _begin(self) -> PageSnapshot:
        self._page_count_before = len(self.context.pages) if self.context else 0
        return self.current_snapshot or self.observe()

    def _finish(self, before: PageSnapshot, message: str, *, error: str | None = None, require_change: bool = True) -> ToolResult:
        self.page.wait_for_timeout(250)
        if self.context and len(self.context.pages) > self._page_count_before:
            self.page = self.context.pages[-1]
            self.page.wait_for_load_state("domcontentloaded", timeout=10_000)
            if self.on_page_change:
                self.on_page_change(self.page)
            message += "；已切换到新标签页"
        after = self.observe()
        changed = before.fingerprint != after.fingerprint
        success = error is None and (changed or not require_change)
        error = error or ("操作后页面没有可验证的变化" if require_change and not changed else None)
        return ToolResult(success, message if success else f"{message}；{error}", before, after, changed, error)

    def _element(self, element_id: str, operation: str) -> InteractiveElement:
        element = self._elements.get(element_id)
        if not element:
            raise ValueError("元素 ID 不属于当前页面快照；请先重新观察")
        if operation == "type" and element.operation != "type":
            raise ValueError("目标元素不可输入")
        return element

    def navigate(self, url: str) -> ToolResult:
        before = self._begin()
        try:
            self.page.goto(url if url.startswith("http") else f"https://{url}", wait_until="domcontentloaded", timeout=15_000)
            return self._finish(before, f"已导航到: {self.page.url}")
        except Exception as exc:
            return self._finish(before, "导航失败", error=str(exc))

    def click(self, element_id: str) -> ToolResult:
        before = self._begin()
        try:
            self.page.locator(self._element(element_id, "click").selector).click(timeout=10_000)
            return self._finish(before, f"已点击 {element_id}")
        except Exception as exc:
            return self._finish(before, f"点击 {element_id} 失败", error=str(exc))

    def type(self, element_id: str, text: str) -> ToolResult:
        before = self._begin()
        try:
            self.page.locator(self._element(element_id, "type").selector).fill(text, timeout=10_000)
            return self._finish(before, f"已输入到 {element_id}")
        except Exception as exc:
            return self._finish(before, f"输入 {element_id} 失败", error=str(exc))

    def press(self, key: str) -> ToolResult:
        before = self._begin()
        try:
            self.page.keyboard.press(key)
            return self._finish(before, f"已按下 {key}")
        except Exception as exc:
            return self._finish(before, f"按键 {key} 失败", error=str(exc))

    def scroll(self, direction: str, amount: int = 500) -> ToolResult:
        before = self._begin()
        try:
            if direction not in ("down", "up"):
                raise ValueError("滚动方向必须为 down 或 up")
            self.page.evaluate("delta => window.scrollBy(0, delta)", amount if direction == "down" else -amount)
            return self._finish(before, f"已向{direction}滚动 {amount}px")
        except Exception as exc:
            return self._finish(before, "滚动失败", error=str(exc))
