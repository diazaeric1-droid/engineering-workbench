# Vendoring Record

The four component repos are vendored as plain directories under `apps/` (copied
from their own repos, excluding `.git`, `.venv`, `__pycache__`, `.pytest_cache`,
`*.egg-info`, `htmlcov`) so the deploy is one self-contained clone. `core.py`
loads each app's `src/` as a top-level package under a distinct alias via
importlib (`_load_pkg`), the same pattern proven in pe-pipeline.

| Component | Version | Alias | Vendored state |
|---|---|---|---|
| well-performance-studio | 0.2.2 | `wps` | **1 file import-rewritten** (below); all other files byte-identical (`diff -r` verified) |
| production-engineer-copilot | 0.9.2 | `pec` | byte-identical (`diff -r` verified) |
| esp-failure-risk-agent | 0.7.3 | `esp` | byte-identical (`diff -r` verified) |
| well-gas-lift-advisor | 0.1.0 | `gla` | byte-identical (`diff -r` verified) |

## Import transformations

Every vendored `src/` was grepped for absolute self-imports
(`^from src`, `^import src`, `from src `). Findings:

- **well-performance-studio** — `src/lift.py` carried two absolute self-imports.
  Both were mechanically rewritten to package-relative form so the module
  resolves under the `wps` alias; **no other change**:
  - line 33: `from src.nodal import (` → `from .nodal import (`
  - line 248: `from src.nodal import VLPResult, vlp_curve` → `from .nodal import VLPResult, vlp_curve`

  `src/nodal.py` (the physics-validated core) is **byte-identical** — only
  `lift.py`'s import lines changed.
- **production-engineer-copilot** — all internal imports already
  package-relative (`from .analyzers...`); zero transformations. (Its CI's
  editable install serves its own `tests/`, which import `src.*` — those tests
  stay in the home repo; this product's `pytest.ini` excludes `apps/` from
  collection.)
- **esp-failure-risk-agent** — all internal imports package-relative; zero
  transformations. NOTE: `src/oracle.py` imports the data generator via the
  top-level name `data.synthetic.generate` (a namespace-package import that
  works in its home repo because the repo root is on `sys.path`). Since three
  vendored apps ship a `data/synthetic/generate*.py`, `core.py` pre-registers
  that exact module from the **ESP** app dir by file location
  (`_register_esp_generator`) so the import can never resolve to the wrong
  app's generator.
- **well-gas-lift-advisor** — `src/` has no internal cross-imports; zero
  transformations.

## Verification

```
diff -r -x .git -x .venv -x __pycache__ -x .pytest_cache -x htmlcov -x '*.egg-info' \
    <component-repo> apps/<component>
```

returns empty for `esp` and `gla`, exactly the two `lift.py` import lines for
`wps`, and one product-glue ADDITION (no modifications) for `pec` — see below.

Stronger check — **tracked-set parity**: for every component,
`git ls-files apps/<component>` in this repo equals `git ls-files` in the
component's home repo (so this repo commits exactly what upstream commits and
regenerates exactly what upstream regenerates), with one exception:

- `apps/production-engineer-copilot/evals/.gitignore` — a NEW product-glue file
  (not a component file). pec's own `.gitignore` says `evals/results/`, which
  works upstream only because the four scored eval summaries are already
  tracked there (gitignore never applies to tracked files). In this fresh repo
  that nested rule would silently drop the committed eval artifacts the
  honest-eval chip reads, and a root-level negation cannot override a deeper
  `.gitignore`. The added file re-selects exactly the four files upstream
  tracks (`summary.json`, `model_frontier.json`, `adversarial.txt`,
  `holdout/summary_holdout.json`).

## Presentation layer (repo root, byte-identical copies)

- `product_theme.py` ← `_shared/product_theme.py`
- `theme.py` ← `well-gas-lift-advisor/demo/theme.py`
- `fleet_registry.py` ← `well-gas-lift-advisor/demo/fleet_registry.py`
- `.streamlit/config.toml` ← `well-gas-lift-advisor/.streamlit/config.toml`

## Regenerated (gitignored) artifacts

Mirrored from each component's own `.gitignore`, re-rooted under `apps/`
(see this repo's `.gitignore`); `core.bootstrap()` rebuilds all of them
deterministically on first run:

- `apps/esp-failure-risk-agent/data/synthetic/*.csv` + `labels.csv` (seed 7)
- `apps/esp-failure-risk-agent/artifacts/` (trained model + training report)
- `apps/well-gas-lift-advisor/data/synthetic/fleet/` + `ground_truth.csv` (seed 42)

production-engineer-copilot's data (REAL Colorado ECMC extract + synthetic well
JSONs + committed eval artifacts) is committed upstream and stays committed here.
