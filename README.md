# AI-Driven Test Process Automation

## An End-to-End LLM-Based Pipeline for Test Asset Generation with Human-in-the-Loop Review

> **One-sentence summary:**
>
> This project turns a high-level **Epic** into a complete and reviewable testing asset chain —
>
> **Features → User Stories → Test Plan → Test Cases → Playwright Automated Tests** —
>
> using a  **step-wise, resumable, human-reviewable, and versioned LLM pipeline** .

---

## 🏢 Business Background & Motivation

In real-world software delivery, **test assets** are often a major bottleneck for both velocity and quality:

* Development iterations move fast, but test plans, test cases, and automation scripts lag behind
* Requirements are usually written in unstructured natural language and require manual decomposition
* Writing automated tests is expensive and error-prone, especially across multiple stories/features
* Even with Copilot/LLMs, naïve “one-shot generation” frequently leads to:
  * Truncated outputs
  * Partial coverage (examples only)
  * Non-reproducible results with no audit trail

This project aims to  **upgrade LLM usage from a one-off generator to a controllable engineering pipeline** :

* Break generation into **verifiable, structured steps**
* Introduce **human review and confirmation at every stage**
* Persist **versioned artifacts** for replay, comparison, and evaluation

---

## 🎯 Project Goals

| Goal                       | Description                                                               |
| -------------------------- | ------------------------------------------------------------------------- |
| End-to-end automation      | Epic → Features → Stories → Test Plan → Test Cases → Automated Tests |
| Human-in-the-loop control  | Every step can be reviewed, confirmed, or redone                          |
| Artifact traceability      | All confirmed outputs are versioned and persisted                         |
| Resume support             | Any interruption can resume from `state.json`                           |
| Truncation-safe generation | Batched generation for large outputs                                      |
| Evaluatable & extensible   | Dedicated evaluation layer for future checks                              |

---

## 🧠 High-Level Architecture

<pre class="overflow-visible! px-0!" data-start="2145" data-end="2587"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>User Input (Epic / Meta)
   |
   v
AgentOrchestrator
   |
   +--> StepRouter      (decides next step, validates dependencies, supports resume)
   |
   +--> StepGenerator   (LLM-based generation, JSON-first, batched where needed)
   |
   +--> ReviewConsole   (interactive human review: confirm / redo / skip)
   |
   +--> StateStore      (persists progress, confirmed artifacts, trace metadata)
   |
   v
Versioned Output Artifacts
</span></span></code></div></div></pre>

---

## ⚙️ End-to-End Flow (Step 0 ~ Step 5)

The core philosophy of this system is:

> **Replace “uncontrolled one-shot generation” with a stepwise, reviewable, and resumable pipeline.**

---

### Step 0: EPIC

* **Input:** High-level business goal and meta information (trace_id, domain, constraints)
* **Output:** `00_epic.confirmed.v1.json`

---

### Step 1: FEATURES

* **Input:** Epic
* **Output:** `01_features.confirmed.v1.json`
* **Purpose:** Decompose the epic into structured functional units that anchor downstream stories

---

### Step 2: STORIES

* **Input:** Epic + Features
* **Output:** `02_stories.confirmed.v1.json`
* **Purpose:** Generate user stories with explicit acceptance criteria (used later for test cases)

---

### Step 3: TEST_PLAN

* **Input:** Epic + Features + Stories
* **Output:** `03_test_plan.confirmed.v1.json`
* **Content includes:** scope, in/out-of-scope, risks, environments, entry/exit criteria

---

### Step 4: TEST_CASES

* **Input:** Test Plan + Stories (optionally summarized Features)
* **Output:** `04_test_cases.confirmed.v1.json`
* **Key design:**

  **Batched per-story generation (Scheme-B)** to avoid truncation and missing coverage

Typical structure:

* id, story_id, title, priority
* preconditions, steps, expected
* test_data (object)

---

### Step 5: AUTOMATED_TESTS

* **Input:** Structured test cases
* **Output:** `05_automated_tests.confirmed.v1.spec.ts`
* **Purpose:** Map each test case into executable Playwright test skeletons

Common strategies:

* Group by story using `describe()`
* One `test()` per test case id
* Comments linking code back to test case ids (for evaluation)

> Note: Batched generation is recommended for this step as well to avoid truncation and improve coverage.

---

## ✨ Technical Highlights

### 1) JSON-First Design

All steps except automated test code output JSON:

* Stable parsing
* Easy comparison and evaluation
* Reliable downstream prompt inputs

---

### 2) Human-in-the-Loop Review

Via `ReviewConsole`, users can:

* Inspect drafts
* Confirm and freeze outputs
* Redo steps with explicit feedback (`redo_hint`)

Only confirmed artifacts are persisted as versioned outputs.

---

### 3) Resumable Execution

`StateStore` persists:

* Current step
* Confirmed artifacts
* Trace metadata

The pipeline can safely resume after interruption or failure.

---

### 4) Batched Generation for Large Outputs

Large-volume steps (especially Step 4 and Step 5) are designed to support batching to avoid:

* Token limit truncation
* “Example-only” outputs
* Expensive full-pipeline retries

---

### 5) Versioned Prompts

All prompts are stored under `backend/src/prompts/`:

* Prompt changes are tracked in Git
* Output quality regressions can be traced back to prompt diffs

---

### 6) Evaluation-Ready Architecture

The `evaluation/` directory is a reserved extension point for:

* Coverage checks (Step 4 vs Step 5)
* ID mapping validation
* LLM-based semantic judges
* Quality scoring (assertions, selectors, maintainability)

---

## 📁 Project Structure (Aligned with Current Repo)

<pre class="overflow-visible! px-0!" data-start="5678" data-end="7450"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-text"><span><span>AIDRIVENTESTPROCESSAUTOMATION/
├── backend/
│   └── src/
│       ├── agent/
│       │   ├── orchestrator.py        # Flow orchestration & resume logic
│       │   ├── state_store.py         # State persistence
│       │   ├── step_router.py         # Step routing & dependency validation
│       │   ├── step_generator.py      # Core LLM generation (batched where needed)
│       │   └── review_console.py      # Interactive human review
│       │
│       ├── config/
│       │   ├── github_models.example.json
│       │   └── github_models.local.json   # Local model config (gitignored)
│       │
│       ├── data_io/
│       │   ├── file_reader.py
│       │   └── file_writer.py
│       │
│       ├── evaluation/
│       │   └── automated_tests_evaluator.py
│       │
│       ├── llm/
│       │   ├── config_loader.py
│       │   └── copilot_client.py
│       │
│       ├── output/
│       │   └── <trace_id>/
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
└── .gitignore
</span></span></code></div></div></pre>

---

## 🚀 How to Run (Local POC)

### 1) Install Dependencies

<pre class="overflow-visible! px-0!" data-start="7516" data-end="7559"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>pip install -r requirements.txt
</span></span></code></div></div></pre>

---

### 2) Configure LLM Models

1. Copy the example config:
   * `backend/src/config/github_models.example.json`
2. Create local config:
   * `backend/src/config/github_models.local.json`
3. Ensure local config is ignored by Git

---

### 3) Run the Pipeline

<pre class="overflow-visible! px-0!" data-start="7823" data-end="7849"><div class="contain-inline-size rounded-2xl corner-superellipse/1.1 relative bg-token-sidebar-surface-primary"><div class="sticky top-[calc(--spacing(9)+var(--header-height))] @w-xl/main:top-9"><div class="absolute end-0 bottom-0 flex h-9 items-center pe-2"><div class="bg-token-bg-elevated-secondary text-token-text-secondary flex items-center gap-4 rounded-sm px-2 font-sans text-xs"></div></div></div><div class="overflow-y-auto p-4" dir="ltr"><code class="whitespace-pre! language-bash"><span><span>python main.py
</span></span></code></div></div></pre>

You will see:

* Draft generation at each step
* Interactive review via `ReviewConsole`
* Confirmed artifacts written to `backend/src/output/<trace_id>/`

---

## 📦 Output Artifacts & Replay

Each trace directory contains a complete, versioned artifact chain:

* Epic
* Features
* Stories
* Test Plan
* Test Cases
* Automated Tests
* State snapshot

This enables:

* Comparing outputs across models or prompt versions
* Auditing coverage and consistency
* Building evaluation datasets

---

## 🧪 Evaluation (Future Extensions)

Planned evaluation capabilities include:

* Step 4 vs Step 5 coverage checks
* Test case ID presence validation
* LLM-based semantic alignment checks
* Automated test quality scoring

---

## 🗺️ Roadmap

* **Phase 1:** Stable end-to-end generation with batching (current)
* **Phase 2:** Deterministic coverage and mapping checks
* **Phase 3:** LLM-based semantic judges
* **Phase 4:** CI integration as a quality gate
* **Phase 5:** Multi-domain, multi-epic test asset factory

---

## 💬 One-Sentence Takeaway

> This project turns LLM-powered test generation into an  **engineering-grade pipeline** :
>
> **decomposable, reviewable, resumable, traceable, evaluable, and extensible.**
