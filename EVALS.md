# Shoppr Evaluation (Evals) Harness Plan

This document outlines the design and implementation plan for Shoppr's automated Evaluation (Evals) Harness. The framework leverages historical production inputs (`raw_input` and `input_type` stored in SQLite) to measure, benchmark, and optimize list generation, categorization accuracy, and OCR performance.

---

## 1. Objectives

- **Accuracy & Precision:** Measure how reliably items are parsed, normalized, and categorized into correct store areas.
- **Prompt Engineering & A/B Testing:** Evaluate prompt iterations ([prompts/](file:///Users/tom/Documents/code/python/shoppr/prompts)) against standard benchmarks before deploying.
- **Model Cost & Speed Optimization:** Test smaller, faster, and cheaper models (e.g., `gemini-2.5-flash-lite`) against golden benchmarks to maximize performance while minimizing LiteLLM proxy costs.
- **Zero-Regression CI/CD:** Prevent functional regressions when updating system prompts or store layout definitions.

---

## 2. Benchmark Dataset Generation (Teacher-Student Pattern)

Instead of manually annotating hundreds of shopping lists, we use a frontier "Teacher" model to bootstrap the golden benchmark dataset.

```
+-----------------------------+
| SQLite (shopping.db)        |
| - raw_input                 |
| - input_type (text/image)   |
| - supermarket               |
+--------------+--------------+
               |
               v
+-----------------------------+
| evals/generate_dataset.py   |
| Frontier Model:             |
| gemini-2.5-pro / gpt-4o     |
| (Temperature = 0.0)         |
+--------------+--------------+
               |
               v
+-----------------------------+
| Human Spot-Check (10-20%)   |
| Verify edge cases & OCR     |
+--------------+--------------+
               |
               v
+-----------------------------+
| evals/dataset.json          |
| (Locked Ground-Truth Target)|
+-----------------------------+
```

### Dataset Entry Format (`evals/dataset.json`)

```json
[
  {
    "id": "a3x9k",
    "input_type": "text",
    "supermarket": "tesco",
    "raw_input": "2L semi skimmed milk\n1 loaf hovis white bread\n6 eggs\nfrozen peas 500g",
    "golden_output": [
      {
        "name": "Semi-skimmed milk",
        "quantity": "2L",
        "area": "dairy",
        "area_order": 3
      },
      {
        "name": "White bread",
        "quantity": "1 loaf",
        "area": "bakery",
        "area_order": 2
      },
      {
        "name": "Eggs",
        "quantity": "6",
        "area": "dairy",
        "area_order": 3
      },
      {
        "name": "Peas",
        "quantity": "500g",
        "area": "frozen",
        "area_order": 14
      }
    ]
  }
]
```

---

## 3. Core Evaluation Metrics

| Metric | Target | Description |
| :--- | :--- | :--- |
| **Categorization Accuracy** | > 95% | Percentage of items assigned to the correct store `area` based on store layout. |
| **Item Recall** | 100% | Percentage of valid items in `raw_input` successfully extracted (zero missing items). |
| **Quantity Extraction Accuracy** | > 90% | Precision of quantity and unit parsing (e.g., `"2L"`, `"500g"`). |
| **Aisle Sequence Order Score** | 100% | Strict adherence of `area_order` to the store's layout prompt map. |
| **Schema Strictness** | 100% | Percentage of LLM responses passing valid JSON schema validation without syntax errors. |
| **Cost & Latency Benchmark** | Metric | Average execution time (ms) and LiteLLM token cost ($) per processed list. |

---

## 4. Proposed Evals Architecture & File Structure

```
shoppr/
├── EVALS.md                     # This architectural document
├── evals/
│   ├── dataset.json             # Locked golden benchmark dataset
│   ├── generate_dataset.py      # Script to generate ground-truth using frontier model
│   ├── scorers.py               # Deterministic and semantic scoring functions
│   └── run_evals.py             # Main CLI runner for testing candidate models/prompts
```

### Module Responsibilities

1. **`evals/generate_dataset.py`**:
   - Queries `shopping.db` for distinct `raw_input` records.
   - Invokes `gemini-2.5-pro` (or equivalent frontier model) with zero temperature and detailed annotator instructions.
   - Outputs initial `evals/dataset.json`.

2. **`evals/scorers.py`**:
   - `score_schema()`: Validates JSON format and required keys.
   - `score_categorization()`: Compares output `area` and `area_order` against golden dataset.
   - `score_recall()`: Verifies all input items are accounted for.
   - `score_quantity()`: Evaluates precision of quantity/unit strings.

3. **`evals/run_evals.py`**:
   - Runs test suites against candidate models (e.g., `gemini-2.5-flash-lite`, custom prompts).
   - Generates comparative markdown summary tables.

---

## 5. Development Command Integration

Add an `eval` command to the project's `justfile` for quick CLI execution:

```just
# Run LLM evals harness against dataset
eval:
    .venv/bin/python evals/run_evals.py --model gemini/gemini-2.5-flash-lite
```

---

## 6. Execution Roadmap

1. **Phase 1: Dataset Collection & Generation**
   - Collect 50-100 diverse `raw_input` entries from production (covering text lists, OCR text, various supermarkets).
   - Generate ground-truth targets using `gemini-2.5-pro`.
   - Perform human spot-check on flagged edge cases.

2. **Phase 2: Scorer & Runner Implementation**
   - Implement `evals/scorers.py` and `evals/run_evals.py`.
   - Benchmark the current production setup (`gemini-2.5-flash-lite`).

3. **Phase 3: Prompt Optimization Iterations**
   - Test prompt enhancements (JSON mode, deduplication, temperature-state rules) and quantify accuracy improvements against baseline scores.
