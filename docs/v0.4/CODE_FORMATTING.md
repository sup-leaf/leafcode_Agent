# LeafCode v0.4 代码格式整理记录

**日期：** 2026-07-17  
**类型：** style（仅调整表现形式，不改变业务行为）  
**范围：** Python 源码、内嵌页面 JavaScript 与 Textual CSS 的可读性整理。

## 1. 目标

本次整理不改变 Agent 的功能、接口、变量语义、执行顺序、异常处理策略或依赖版本，只将过度压缩的代码拆分为更容易阅读和维护的形式。

重点解决以下问题：

- 多条 Python 语句使用分号写在同一行。
- 单行函数、单行条件与单行 return 难以断点调试。
- 多层条件表达式、函数调用、字典和列表字面量过长。
- observe() 内嵌 JavaScript 同时承担页面选择、可见性判断、文本清洗和元素序列化，但原先集中在数个长行中。
- Textual CSS 的多个选择器与属性写在同一行，难以查看或修改视觉规则。

## 2. 整理原则

1. **一条语句一行。** 初始化、赋值、调用、返回、continue 和 return 不与其他语句混写。
2. **一个逻辑层级一组缩进。** 条件、循环、try/except、字典、列表和函数参数按层级展开。
3. **长布尔条件垂直书写。** 每个判断项占一行，使读者能逐项检查。
4. **长调用按参数换行。** 每个位置参数或关键字参数独占一行，保留末尾逗号以便后续增删。
5. **数据对象按字段换行。** 页面元素、快照、事件和 CSS 规则应让字段名称与值清晰对应。
6. **内嵌语言同样遵循可读性规则。** Python 字符串中的 JavaScript 与 CSS 不因“嵌在字符串里”而保留压缩写法。
7. **不改变语义。** 不改名、不增删条件、不改变字符串内容、不调整超时与参数值、不引入新依赖。

## 3. 重点示例

### 3.1 可见性判断

整理前，JavaScript 在一行内同时读取样式、读取元素尺寸并返回四项判断：

~~~javascript
const visible = (el) => { /* 多项逻辑被压缩 */ };
~~~

整理后按“读取数据 → 空行分隔 → 返回条件”呈现：

~~~javascript
const visible = (el) => {
    const styles = getComputedStyle(el);
    const rectangle = el.getBoundingClientRect();

    return (
        styles.visibility !== 'hidden'
        && styles.display !== 'none'
        && rectangle.width > 0
        && rectangle.height > 0
    );
};
~~~

这使“元素必须可见、显示且有尺寸”的四项条件一目了然；判断结果和原来完全相同。

### 3.2 页面元素序列化

元素返回对象改为每个字段独占一行：

~~~javascript
return {
    id,
    tag: el.tagName.toLowerCase(),
    role: el.getAttribute('role') || '',
    text: clean(
        el.innerText
        || el.value
        || el.getAttribute('aria-label')
        || el.title
    ),
    href: el.href || '',
    type: el.type || '',
    name: el.name || '',
    placeholder: el.placeholder || '',
    value: clean(el.value),
    disabled: !!el.disabled,
};
~~~

这便于检查 Agent 实际交给模型的字段，也使后续添加 aria-label、checked 等字段时不容易破坏原有结构。

### 3.3 Python 运行时代码

以下形式被统一展开：

~~~python
# 整理前的表现形式
if condition: do_work(); return

# 整理后的表现形式
if condition:
    do_work()
    return
~~~

同样适用于：

- try 与 except 的单行块；
- 多个连续赋值；
- 复杂的三元表达式；
- PageSnapshot、ToolResult、RuntimeEvent 等构造调用；
- 嵌套字典、列表推导式与模型消息列表。

## 4. 受影响文件

| 文件 | 整理内容 | 行为影响 |
| --- | --- | --- |
| agent_tui_v4.py | 组件构造、事件处理、命令分支、线程收尾、内嵌 Textual CSS。 | 无 |
| leafcode/browser.py | observe() 的内嵌 JavaScript、快照构造、工具返回值与长调用。 | 无 |
| leafcode/runtime.py | 计划解析、事件发布、确认流程、主循环与工具分派的排版。 | 无 |
| leafcode/safety.py | 规则、正则、敏感数据处理和条件判断的排版。 | 无 |
| tests/test_v03_regression.py | 测试夹具、断言和局部测试 Agent 的排版。 | 无 |
| event_log.py | 原计划整理脱敏列表、字典推导和长条件；本次因本地文件锁定未写入，待锁释放后单独完成。 | 无 |

## 5. 验证方式

格式整理后的验证分为两层：

~~~powershell
# 语法检查
python -m py_compile agent.py agent_tui_v4.py event_log.py leafcode\*.py tests\test_v03_regression.py

# 行为回归
python -m unittest tests.test_v03_regression -v
~~~

由于本次不改逻辑，预期回归结果与整理前一致。若出现测试失败，应优先检查是否在拆分过程中误删了逗号、缩进、短路条件或字符串转义。

2026-07-17 已验证：语法检查通过；完整离线回归通过 21/21。

## 6. 后续约定

- 新增 Python 代码遵循 Black 的默认排版风格。
- 新增页面内嵌 JavaScript 时，函数体、数组、对象和返回值均使用多行结构。
- 新增 Textual CSS 时，一个选择器一个代码块，一个属性一行。
- 代码评审时，格式变化与功能变化应尽量拆分为不同提交，便于定位行为差异。
