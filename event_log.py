"""本地 JSONL 事件日志：用于调试和回归，不记录已知密钥值。"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any


class EventLogger:
    """为一次 Agent 运行写入独立的结构化日志文件。"""

    def __init__(self, base_dir: Path | None = None):
        root = base_dir or Path(__file__).parent
        self.log_dir = root / "logs"
        self.log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        self.path = self.log_dir / f"agent-{timestamp}.jsonl"
        self._secret_values = [
            value for key, value in os.environ.items()
            if value and any(marker in key.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASS"))
        ]

    def _redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            sensitive = ("KEY", "TOKEN", "SECRET", "PASS", "PASSWORD", "CREDENTIAL", "AUTH")
            return {
                str(key): "[REDACTED]" if any(marker in str(key).upper() for marker in sensitive) else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if not isinstance(value, str):
            return value

        cleaned = value
        for secret in self._secret_values:
            cleaned = cleaned.replace(secret, "[REDACTED]")
        cleaned = re.sub(
            r"(?i)\b(api[_ -]?key|token|password|passwd)\s*([=:])\s*[^\s,;]+",
            r"\1\2[REDACTED]",
            cleaned,
        )
        return cleaned

    def write(self, event: str, **data: Any) -> None:
        record = {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "event": event,
            "data": self._redact(data),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
