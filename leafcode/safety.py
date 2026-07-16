from typing import Any

from .models import PageSnapshot


class SafetyPolicy:
    """识别执行前必须由用户明确确认的高风险操作。"""

    KEYWORDS = (
        "submit", "send", "publish", "post", "delete", "remove", "pay", "purchase",
        "download", "upload", "login", "sign in", "登录", "提交", "发送", "发布",
        "删除", "支付", "下载", "上传",
    )

    def confirmation_reason(self, action: str, params: dict[str, Any], snapshot: PageSnapshot) -> str | None:
        if action in {"submit", "download", "upload", "send"}:
            return f"{action} 会产生外部影响"
        if action == "press" and str(params.get("key", "")).lower() == "enter":
            return "按 Enter 可能提交表单"
        element = next((item for item in snapshot.elements if item.id == params.get("element_id")), None)
        if action == "type" and element:
            details = " ".join(element.attributes.values()).lower()
            if any(word in details for word in ("password", "passwd", "token", "email", "user")):
                return "正在填写登录或凭证相关字段"
        if action == "click" and element:
            target = " ".join([element.text, *element.attributes.values()]).lower()
            if any(keyword in target for keyword in self.KEYWORDS):
                return f"将点击可能产生外部影响的元素：{element.text[:40]}"
        return None
