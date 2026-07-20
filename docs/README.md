# LeafCode 文档索引

文档按**产品版本**归档。一个版本文件夹应包含该版本的目标、设计、实施计划、验收标准和复盘；跨版本的历史资料也应放在其对应版本目录中。

| 目录 | 内容 |
| --- | --- |
| [v0.2](v0.2/) | 历史架构与路线图 |
| [v0.3](v0.3/) | 当前开发阶段的设计、实施、重构与验收资料 |
| [v0.4](v0.4/) | 下一阶段的代码质量与迭代资料 |

v0.3 文档入口：[实施计划](v0.3/IMPLEMENTATION_PLAN.md)、[架构](v0.3/ARCHITECTURE.md)、[重构记录](v0.3/REFACTORING.md)、[测试用例](v0.3/TEST_CASES.md)、[设计背景](v0.3/AGENT_DEVELOPMENT_AND_PLAN.md)、[源码导读](v0.3/CODE_WALKTHROUGH.md) 和 [功能审查与 v0.4 研究](v0.3/FUNCTIONAL_REVIEW_AND_V04_RESEARCH.md)。

全项目编写要求见：[编写规范](CODING_CONVENTIONS.md)。

## 约定

- 目录名使用小写版本号，例如 `v0.3`。
- 计划文档使用 `IMPLEMENTATION_PLAN.md`；设计或调研使用能说明内容的英文大写文件名。
- 新功能先在目标版本目录写清范围、验收标准和风险，再进入代码实现。
- 已发布版本的文档尽量不重写历史；修订应在下一版本文档中说明。
