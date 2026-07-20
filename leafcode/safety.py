from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Iterable
from urllib.parse import urlparse

from .models import InteractiveElement, PageSnapshot


class SafetyPolicy:
    """在模型、日志和浏览器动作之间实施最小权限与敏感数据边界。"""

    KEYWORDS = (
        "submit",
        "send",
        "publish",
        "post",
        "delete",
        "remove",
        "pay",
        "purchase",
        "download",
        "upload",
        "login",
        "sign in",
        "登录",
        "提交",
        "发送",
        "发布",
        "删除",
        "支付",
        "下载",
        "上传",
    )
    SENSITIVE_MARKERS = (
        "password",
        "passwd",
        "token",
        "secret",
        "api_key",
        "credential",
        "email",
        "e-mail",
        "phone",
        "mobile",
        "idcard",
        "身份证",
    )
    SENSITIVE_VALUE_PATTERN = re.compile(
        r"(?i)\b(api[_ -]?key|token|secret|password|passwd|credential)\s*([=:])\s*[^\s,;]+"
    )
    EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
    ID_CARD_PATTERN = re.compile(r"\b\d{17}[\dXx]\b")
    INJECTION_PATTERNS = (
        re.compile(
            r"(?i)ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above).*?(?:instruction|rule)"
        ),
        re.compile(
            r"(?i)(?:reveal|expose|print|send).{0,40}(?:api[_ -]?key|token|secret|password)"
        ),
        re.compile(r"忽略.{0,20}(?:之前|以上|先前).{0,20}(?:指令|规则)"),
        re.compile(
            r"(?:泄露|输出|发送).{0,40}(?:密钥|令牌|密码|token|api[_ -]?key)", re.I
        ),
    )

    def __init__(
        self,
        allowed_domains: Iterable[str] | None = None,
        blocked_domains: Iterable[str] | None = None,
    ):
        self.allowed_domains = tuple(
            self._normalize_domain(item) for item in (allowed_domains or ()) if item
        )
        self.blocked_domains = tuple(
            self._normalize_domain(item) for item in (blocked_domains or ()) if item
        )

    @staticmethod
    def _normalize_domain(value: str) -> str:
        candidate = value.strip().lower()
        if "://" in candidate:
            candidate = urlparse(candidate).hostname or ""
        return candidate.strip(".")

    @staticmethod
    def _matches_domain(host: str, rule: str) -> bool:
        if rule.startswith("*."):
            root = rule[2:]
            return host == root or host.endswith(f".{root}")
        return host == rule or host.endswith(f".{rule}")

    @classmethod
    def _element(
        cls, params: dict[str, Any], snapshot: PageSnapshot
    ) -> InteractiveElement | None:
        return next(
            (item for item in snapshot.elements if item.id == params.get("element_id")),
            None,
        )

    @classmethod
    def _is_sensitive_element(cls, element: InteractiveElement | None) -> bool:
        if not element:
            return False
        details = " ".join([element.text, *element.attributes.values()]).lower()
        return any(marker in details for marker in cls.SENSITIVE_MARKERS)

    @classmethod
    def sanitize_text(cls, value: str) -> str:
        """移除会进入模型、事件或 UI 的常见敏感值与提示注入文本。"""
        cleaned = cls.SENSITIVE_VALUE_PATTERN.sub(r"\1\2[REDACTED]", value)
        cleaned = cls.EMAIL_PATTERN.sub("[REDACTED_EMAIL]", cleaned)
        cleaned = cls.ID_CARD_PATTERN.sub("[REDACTED_ID]", cleaned)
        for pattern in cls.INJECTION_PATTERNS:
            cleaned = pattern.sub("[UNTRUSTED_INSTRUCTION_REDACTED]", cleaned)
        return cleaned

    def sanitize_snapshot(self, snapshot: PageSnapshot) -> PageSnapshot:
        """生成给模型使用的页面副本，保留语义但不暴露敏感字段值。"""
        elements = []
        for element in snapshot.elements:
            attributes = {
                key: self.sanitize_text(value)
                for key, value in element.attributes.items()
            }
            text = self.sanitize_text(element.text)
            if self._is_sensitive_element(element):
                attributes["value"] = "[REDACTED]"
                text = "[SENSITIVE_FIELD]"
            elements.append(replace(element, text=text, attributes=attributes))
        return replace(
            snapshot,
            text_excerpt=self.sanitize_text(snapshot.text_excerpt),
            elements=tuple(elements),
        )

    def redact_action_params(
        self, action: str, params: dict[str, Any], snapshot: PageSnapshot
    ) -> dict[str, Any]:
        """为事件和日志生成参数副本；执行仍使用原始 params。"""

        def redact(value: Any, key: str = "") -> Any:
            lowered = key.lower()
            if any(marker in lowered for marker in self.SENSITIVE_MARKERS):
                return "[REDACTED]"
            if isinstance(value, dict):
                return {
                    str(item_key): redact(item_value, str(item_key))
                    for item_key, item_value in value.items()
                }
            if isinstance(value, list):
                return [redact(item) for item in value]
            return self.sanitize_text(value) if isinstance(value, str) else value

        redacted = redact(params)
        if action == "type" and self._is_sensitive_element(
            self._element(params, snapshot)
        ):
            redacted["text"] = "[REDACTED]"
        return redacted

    def injection_findings(self, snapshot: PageSnapshot) -> list[str]:
        """仅报告检测结果；命中的页面文本会在 sanitize_snapshot 中被隔离。"""
        content = "\n".join(
            [snapshot.text_excerpt, *(element.text for element in snapshot.elements)]
        )
        return [
            pattern.pattern
            for pattern in self.INJECTION_PATTERNS
            if pattern.search(content)
        ]

    def blocked_reason(
        self, action: str, params: dict[str, Any], snapshot: PageSnapshot
    ) -> str | None:
        """阻止不安全协议、禁止域名和不在允许清单内的导航。"""
        target = ""
        if action == "navigate":
            target = str(params.get("url", ""))
        elif action == "click":
            element = self._element(params, snapshot)
            target = element.attributes.get("href", "") if element else ""
        if not target:
            return None
        parsed = urlparse(target if "://" in target else f"https://{target}")
        if parsed.scheme not in {"http", "https"}:
            return f"已阻止不安全协议：{parsed.scheme or '未知协议'}"
        host = (parsed.hostname or "").lower()
        if not host:
            return "已阻止缺少有效域名的导航"
        if any(self._matches_domain(host, rule) for rule in self.blocked_domains):
            return f"目标域名已被禁止：{host}"
        if self.allowed_domains and not any(
            self._matches_domain(host, rule) for rule in self.allowed_domains
        ):
            return f"目标域名不在允许列表：{host}"
        return None

    def confirmation_reason(
        self, action: str, params: dict[str, Any], snapshot: PageSnapshot
    ) -> str | None:
        if action in {"submit", "download", "upload", "send"}:
            return f"{action} 会产生外部影响"
        if action == "press" and str(params.get("key", "")).lower() == "enter":
            return "按 Enter 可能提交表单"
        element = self._element(params, snapshot)
        if action == "type" and self._is_sensitive_element(element):
            return "正在填写敏感字段；输入内容不会显示在事件或日志中"
        if action == "click" and element:
            target = " ".join([element.text, *element.attributes.values()]).lower()
            if any(keyword in target for keyword in self.KEYWORDS):
                return f"将点击可能产生外部影响的元素：{element.text[:40]}"
        return None
