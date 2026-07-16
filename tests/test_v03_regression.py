"""v0.3 运行时契约的离线回归测试。

测试刻意使用本地 HTML 和假的模型边界，不计入
docs/v0.3/TEST_CASES.md 中真实站点 T01–T10 的验收记录。
"""

import tempfile
import re
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_tui_v4 import ActivityPart
from event_log import EventLogger
from leafcode.browser import BrowserSession, BrowserTools
from leafcode.models import AgentMode, TaskContext, TaskState
from leafcode.runtime import BrowserAgent, ModelResponseError
from leafcode.safety import SafetyPolicy


class BrowserRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = BrowserSession(headless=True)
        cls.page = cls.session.start()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def setUp(self):
        self.page.set_content("""
            <input id='query'>
            <button id='change' onclick="document.title='changed'">Change</button>
            <button id='open' onclick="window.open('about:blank', '_blank')">Open tab</button>
            <button id='submit'>Submit order</button>
        """)
        self.tools = BrowserTools(self.page, self.session.context, self.session.set_page)

    def test_01_snapshot_has_stable_ids(self):
        snapshot = self.tools.observe()
        self.assertTrue(snapshot.id)
        self.assertEqual(len(snapshot.elements), len({element.id for element in snapshot.elements}))

    def test_02_stale_element_id_is_rejected(self):
        old = self.tools.observe().elements[0].id
        self.tools.observe()
        result = self.tools.click(old)
        self.assertFalse(result.success)
        self.assertIn("不属于当前页面快照", result.error)

    def test_03_type_requires_visible_input_id(self):
        snapshot = self.tools.observe()
        input_id = next(item.id for item in snapshot.elements if item.operation == "type")
        result = self.tools.type(input_id, "leafcode")
        self.assertTrue(result.success)
        self.assertTrue(result.changed)

    def test_04_click_requires_observable_change(self):
        snapshot = self.tools.observe()
        button_id = next(item.id for item in snapshot.elements if item.text == "Change")
        result = self.tools.click(button_id)
        self.assertTrue(result.success)
        self.assertEqual(result.after.title, "changed")

    def test_05_new_tab_becomes_active_session_page(self):
        snapshot = self.tools.observe()
        open_id = next(item.id for item in snapshot.elements if item.text == "Open tab")
        result = self.tools.click(open_id)
        self.assertTrue(result.success)
        self.assertEqual(len(self.session.context.pages), 2)

    def test_06_session_reuses_browser_page(self):
        self.assertIsNotNone(self.session.start())
        self.assertIsNotNone(self.session.browser)


class PolicyAndRuntimeTests(unittest.TestCase):
    def _snapshot(self):
        session = BrowserSession(headless=True)
        page = session.start()
        page.set_content("<button onclick=\"document.title='confirmed'\">Submit order</button>")
        tools = BrowserTools(page, session.context, session.set_page)
        return session, tools, tools.observe()

    def test_07_submit_click_requires_confirmation(self):
        session, tools, snapshot = self._snapshot()
        try:
            element = snapshot.elements[0]
            self.assertIsNotNone(SafetyPolicy().confirmation_reason("click", {"element_id": element.id}, snapshot))
        finally:
            session.close()

    def test_08_enter_requires_confirmation(self):
        session, tools, snapshot = self._snapshot()
        try:
            self.assertIsNotNone(SafetyPolicy().confirmation_reason("press", {"key": "Enter"}, snapshot))
        finally:
            session.close()

    def test_09_logger_redacts_sensitive_dictionary_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            logger = EventLogger(Path(directory))
            self.assertEqual(logger._redact({"password": "plain", "nested": {"token": "secret"}}),
                             {"password": "[REDACTED]", "nested": {"token": "[REDACTED]"}})

    def test_10_confirmation_executes_only_after_approval(self):
        events = []
        session, tools, snapshot = self._snapshot()
        try:
            agent = BrowserAgent("test-key", headless=True, on_output=lambda _text: None, on_event=events.append)
            agent.session, agent._tools = session, tools
            agent.task_context = TaskContext(goal="local", state=TaskState.AWAITING_CONFIRMATION,
                                             current_step=1, latest_snapshot=snapshot)
            agent.pending_confirmation = {
                "action": "click", "params": {"element_id": snapshot.elements[0].id},
                "reason": "submit", "snapshot_id": snapshot.id, "url": snapshot.url,
            }
            agent.resolve_confirmation(True)
            self.assertEqual(agent.task_context.state, TaskState.RUNNING)
            self.assertEqual(events[-1].kind, "result")
        finally:
            session.close()

    def test_11_plan_steps_objects_are_normalized(self):
        plan = BrowserAgent._validate_plan({
            "intent": "测试", "steps": [{"description": "打开页面"}, {"step": "读取内容"}],
            "first_url": "https://example.com",
        })
        self.assertEqual(plan["steps"], ["打开页面", "读取内容"])

    def test_12_invalid_plan_steps_raise_contract_error(self):
        with self.assertRaises(ModelResponseError):
            BrowserAgent._validate_plan({"steps": "不是列表"})

    def test_13_unknown_step_object_is_preserved_for_display(self):
        plan = BrowserAgent._validate_plan({"steps": [{"操作": "搜索", "参数": {"关键词": "宇智波佐助"}}]})
        self.assertEqual(plan["steps"], ['{"操作":"搜索","参数":{"关键词":"宇智波佐助"}}'])

    def test_14_confirmation_signal_stays_on_browser_thread(self):
        waiting = threading.Event()

        class ConfirmingAgent(BrowserAgent):
            def _plan(self, task):
                return {"intent": task, "steps": ["点击测试按钮"], "first_url": "https://unused.example"}

            def _decide(self, snapshot, task):
                match = re.search(r"\[(el-[^\]]+)\]", snapshot)
                if not getattr(self, "asked", False):
                    self.asked = True
                    return {"thought": "请求确认", "action": "click", "params": {"element_id": match.group(1)}}
                return {"thought": "结束", "action": "done", "params": {"summary": "完成"}}

        def on_event(event):
            if event.kind == "confirmation":
                waiting.set()

        agent = ConfirmingAgent("test-key", headless=True, on_output=lambda _text: None, on_event=on_event)

        def run_in_browser_thread():
            agent.session = BrowserSession(headless=True)
            page = agent.session.start()
            page.set_content("<button onclick=\"document.title='confirmed'\">Submit order</button>")
            try:
                return agent.run("本地确认")
            finally:
                agent.close()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_in_browser_thread)
            self.assertTrue(waiting.wait(10), "任务未进入确认状态")
            self.assertEqual(agent.submit_confirmation(True), "确认结果已提交，正在由浏览器任务处理。")
            self.assertEqual(future.result(timeout=10), "完成")

    def test_15_action_json_is_rendered_as_plain_text(self):
        """动作参数含方括号时，不应触发 Textual 的富文本解析。"""
        part = ActivityPart('ACTION: click {"element_id": "el-s5-4", "targets": ["el-s5-4"]}')
        self.assertIn('"element_id": "el-s5-4"', part.render().plain)

    def test_16_inform_task_closes_browser_after_completion(self):
        """inform 是一次性浏览；完成后不应保留 Playwright 会话。"""
        class ImmediateDoneAgent(BrowserAgent):
            def _plan(self, task):
                return {"intent": task, "steps": ["读取页面"], "first_url": "data:text/html,<title>test</title>"}

            def _decide(self, snapshot, task):
                return {"thought": "信息已读取", "action": "done", "params": {"summary": "完成"}}

        agent = ImmediateDoneAgent("test-key", headless=True, on_output=lambda _text: None)
        try:
            self.assertEqual(agent.run("本地信息任务", mode=AgentMode.INFORM), "完成")
            self.assertIsNone(agent.session)
        finally:
            agent.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
