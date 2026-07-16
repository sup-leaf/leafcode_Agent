"""LeafCode 的兼容 CLI 入口。

业务实现位于 ``leafcode`` 包；本模块仅保留 ``python agent.py``
和 TUI 既有导入方式的兼容性。
"""

import os

from leafcode.models import AgentMode
from leafcode.runtime import BrowserAgent, load_dotenv

__all__ = ["AgentMode", "BrowserAgent"]


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        api_key = input("请输入 DeepSeek API Key: ").strip()
    task = input("请输入任务: ").strip()
    if not task:
        return
    agent = BrowserAgent(api_key=api_key)
    try:
        result = agent.run(task)
        print(f"\n{'=' * 60}")
        print(f"RESULT: {result}")
        print("=" * 60)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
