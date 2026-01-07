# AI Driven Test Process Automation

## 基于 LLM 的测试资产端到端生成与 Human-in-the-loop 审核流水线

> **一句话总结：**
> 这是一个把“需求/史诗（Epic）”自动转化为 **Features → User Stories → Test Plan → Test Cases → Playwright 自动化测试代码** 的端到端流程系统。
> 系统通过 **步骤化生成 + 状态可恢复 + 人工审核确认（Human-in-the-loop）+ 产物版本化** 的方式，让 LLM 生成结果可控、可回放、可扩展。

---

## 🏢 业务背景与问题动机

在真实的软件交付中，“测试资产”往往是研发效率与质量的瓶颈之一：

- PR/迭代速度快，但测试计划/用例/自动化脚本经常滞后
- 需求文档表述非结构化，测试工程师需要大量时间做拆解与归纳
- 自动化测试编写成本高，且容易遗漏覆盖面（尤其跨多个 Story/Feature 时）
- 即使使用 Copilot/LLM，直接“一次性生成全部内容”也常出现：
  - 输出截断（只生成前半部分）
  - 只生成示例而非覆盖全部
  - 结果不可追溯，无法回放与对账

本项目的目标是把 LLM 从“单次生成器”升级为一个**可控的工程化流水线**：

- 按步骤生成可审核的中间产物（JSON-first）
- 每一步都可人工确认/重做
- 最终产物可版本化落盘，支持回放、扩展与评估

---

## 🎯 项目目标

| 目标                          | 说明                                                                      |
| ----------------------------- | ------------------------------------------------------------------------- |
| 流程端到端自动化              | Epic → Features → Stories → Test Plan → Test Cases → Automated Tests |
| 人工可控（Human-in-the-loop） | 每一步都可以 Review/Confirm/Redo                                          |
| 产物可追溯                    | 所有 confirmed 产物按 trace/version 落盘                                  |
| 支持断点恢复                  | 任何一步失败可从 state.json 继续                                          |
| 支持批处理防截断              | 对“输出量大”的步骤（如 Test Cases / Automated Tests）采用 batched 策略  |
| 可评估、可扩展                | evaluation 目录专门容纳评估逻辑，未来可加入 LLM Judge                     |

---

## 🧠 高层架构概览

```text
User Input (Epic/Meta)
   |
   v
AgentOrchestrator
   |
   +--> StepRouter      (决定下一步/校验依赖/支持 resume)
   |
   +--> StepGenerator   (按 step 生成草稿：JSON-first / batched)
   |
   +--> ReviewConsole   (交互式人工审核：confirm/redo/skip)
   |
   +--> StateStore      (保存当前进度、confirmed 产物、trace)
   |
   v
Output Artifacts (versioned)
```


## ⚙️ 端到端流程（Step 0 ~ Step 5）

本项目的核心思想是：

**把“不可控的一次性生成”拆成可验证的步骤链路，每一步输出结构化产物，并允许人工确认。**

### Step 0：EPIC（生成/整理史诗级需求）

* 输入：高层业务目标、meta 信息（trace_id、domain、constraints 等）
* 输出：`00_epic.confirmed.v1.json`

### Step 1：FEATURES（功能拆解）

* 输入：Epic
* 输出：`01_features.confirmed.v1.json`
* 特点：输出结构化 Features 列表，作为 Stories 的父级语义锚点

### Step 2：STORIES（用户故事）

* 输入：Epic + Features
* 输出：`02_stories.confirmed.v1.json`
* 特点：每个 story 具备 acceptance criteria（后续生成 test cases 的依据）

### Step 3：TEST_PLAN（测试计划）

* 输入：Epic + Features + Stories
* 输出：`03_test_plan.confirmed.v1.json`
* 特点：包含 scope / in_scope / out_of_scope / risks / entry/exit criteria 等

### Step 4：TEST_CASES（测试用例）

* 输入：Test Plan + Stories（必要时带 Feature 摘要）
* 输出：`04_test_cases.confirmed.v1.json`
* 特点： **按 story batched 生成并 merge（Scheme-B）** ，避免一次生成导致截断/遗漏

  结构一般为：

  * id, story_id, title, priority
  * preconditions, steps, expected
  * test_data（object）

### Step 5：AUTOMATED_TESTS（自动化测试代码）

* 输入：Test Cases
* 输出：`05_automated_tests.confirmed.v1.spec.ts`
* 特点：将结构化 test cases 映射为可执行的 Playwright 测试骨架

  常见策略：

  * 按 story 分块生成（减少 truncation 风险）
  * describe() 分组
  * 每个 test() 对应一个 test case id（用于覆盖率评估）

---

## ✨ 技术特点与设计亮点

### 1) JSON-first（结构化优先）

除 AUTOMATED_TESTS 外，每一步都使用 JSON 输出，方便：

* 稳定解析
* 后续评估/统计/对比
* 作为下游 prompt 的可靠输入

### 2) Human-in-the-loop 审核闭环

通过 `ReviewConsole`：

* 用户可以对每一步草稿进行确认
* 不满意可 redo，并传入 redo_hint
* 结果被“冻结”为 confirmed 版本（落盘）

### 3) 状态可恢复（Resumable）

通过 `StateStore` 保存：

* 当前 step
* 已 confirmed 的产物
* trace 元信息

  即使中途失败/退出，也可从 `state.json` 继续跑。

### 4) 批处理生成（Batched Generation）

针对“输出量大”的步骤（尤其 Step 4/5），采用 batched 生成以解决：

* max_tokens 不够导致截断
* 模型只生成“示例”而非覆盖全部
* 重试成本过高（一次失败要重跑全部）

### 5) Prompt 版本化（可追溯）

`backend/src/prompts/` 保存每一步的 system/user prompt：

* prompt 变更可版本追踪
* 输出质量变化可定位到 prompt diff

### 6) Evaluation 预留扩展点

`backend/src/evaluation/` 专门放评估类（例如：Step4 vs Step5 覆盖率检查）

未来可扩展：

* coverage check（数量/ID 对齐）
* mapping check（1:1 映射）
* LLM Judge（语义一致性：test case 与 test code 是否匹配）
* 质量评分（assertion、selector 稳定性、可维护性）

## 📁 项目结构（与你当前目录对齐）

<pre class="overflow-visible! px-0!" data-start="3719" data-end="5537"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>AIDRIVENTESTPROCESSAUTOMATION/
├── backend/
│   └── src/
│       ├── agent/
│       │   ├── orchestrator.py        # 流程编排：create/load trace + resume + review loop
│       │   ├── state_store.py         # 状态存储：current_step / confirmed / trace
│       │   ├── step_router.py         # 步骤路由：决定下一步 & 校验依赖
│       │   ├── step_generator.py      # 核心生成器：按 step 调用 LLM（含 batched）
│       │   └── review_console.py      # 交互式审核：confirm/redo/freeze
│       │
│       ├── config/
│       │   ├── github_models.example.json
│       │   └── github_models.local.json    # 本地模型配置（注意 gitignore）
│       │
│       ├── data_io/
│       │   ├── file_reader.py
│       │   └── file_writer.py
│       │
│       ├── evaluation/
│       │   └── automated_tests_evaluator.py  # 评估骨架（可扩展）
│       │
│       ├── llm/
│       │   ├── config_loader.py
│       │   └── copilot_client.py       # Copilot / GitHub Models API 封装
│       │
│       ├── output/
│       │   └── demo_auth_v4/
│       │       ├── 00_epic.confirmed.v1.json
│       │       ├── 01_features.confirmed.v1.json
│       │       ├── 02_stories.confirmed.v1.json
│       │       ├── 03_test_plan.confirmed.v1.json
│       │       ├── 04_test_cases.confirmed.v1.json
│       │       ├── 05_automated_tests.confirmed.v1.spec.ts
│       │       └── state.json
│       │
│       └── prompts/
│           ├── 01_features.system.txt
│           ├── 01_features.user.txt
│           ├── 02_stories.system.txt
│           ├── 02_stories.user.txt
│           ├── 03_test_plan.system.txt
│           ├── 03_test_plan.user.txt
│           ├── 04_test_cases.system.txt
│           ├── 04_test_cases.user.txt
│           ├── 05_automated_tests.system.txt
│           └── 05_automated_tests.user.txt
│
├── main.py
├── requirements.txt
├── README.md
├── README_cn.md
└── .gitignore</span></span></code></div></div></pre>


## 🚀 如何运行（本地 POC）

### 1) 安装依赖

<pre class="overflow-visible! px-0!" data-start="5576" data-end="5619"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>pip install -r requirements.txt
</span></span></code></div></div></pre>

### 2) 配置模型

* 复制示例配置：
  * `backend/src/config/github_models.example.json`
* 生成本地配置：
  * `backend/src/config/github_models.local.json`
* 本地配置应被 `.gitignore` 忽略（避免泄露 token）

### 3) 运行主流程

<pre class="overflow-visible! px-0!" data-start="5806" data-end="5832"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python main.py
</span></span></code></div></div></pre>

运行后你会看到：

* 每一步生成草稿
* 进入 review_console 进行确认/重做
* confirmed 产物落盘到 `backend/src/output/<trace>/...`

---

## 📦 输出产物说明（如何回放与对账）

每个 trace（例如 `demo_auth_v4`）下会生成一组版本化产物：

* `00_epic.confirmed.v1.json`
* `01_features.confirmed.v1.json`
* `02_stories.confirmed.v1.json`
* `03_test_plan.confirmed.v1.json`
* `04_test_cases.confirmed.v1.json`
* `05_automated_tests.confirmed.v1.spec.ts`
* `state.json`（用于断点恢复）

这种结构天然支持：

* 对比不同 prompt / 不同模型的输出质量
* 对账“同一个 Epic”在不同版本下的差异
* 构建 evaluation 评估数据集

---

## 🧪 Evaluation（扩展方向）

当前 `evaluation/automated_tests_evaluator.py` 是一个“可扩展骨架”，未来可逐步加入：

* Step4 vs Step5 覆盖率检查：

  `test_cases` 数量是否等于生成的 `test()` 数量
* ID 对齐检查：

  每个 test case id 是否在代码中出现
* LLM Judge：

  判断 test case 的 steps/expected 是否被代码覆盖
* 质量评分：

  selectors 是否稳定、assertions 是否合理、是否可维护

---

## 🗺️ Roadmap（建议的演进路线）

* Phase 1：稳定端到端生成 + batched 策略（当前已完成核心）
* Phase 2：加入 deterministic 的 coverage / mapping checks（evaluation）
* Phase 3：加入 LLM Judge 做语义一致性验证（更智能的评估）
* Phase 4：将输出产物对接 CI（自动生成测试资产并做质量门禁）
* Phase 5：扩展为“测试资产智能工厂”（多 Epic / 多域 / 多团队）

---

## 💬 一句话总结

> 这是一个将 LLM 能力工程化的测试资产生成流水线：
>
> **可拆解、可审查、可恢复、可追溯、可评估、可扩展** 。
