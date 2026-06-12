"""Main agent loop. Claude does the reasoning; deterministic tools do the math."""
from __future__ import annotations

import argparse
import os
from datetime import date
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

from .data_loader import WellFile
from .tools import TOOL_SCHEMAS, ToolExecutor


SYSTEM_PROMPT = """You are a Senior Production Engineer assistant. Given a well's data package, perform a complete well review and return a one-page markdown report.

Today's date: {today}

Follow this process:
1. Call `fit_decline_curve` to understand current performance vs. type curve.
2. Call `analyze_water_gas_trends` on every well — a rising water cut or GOR drives interventions the oil-rate curve hides (economic-limit shifts, gas interference, liquid loading).
3. If the well is on ESP, call `evaluate_esp_health`. **If the well is on a Beam Pump (or any rod lift) and dyno cards are available, you MUST call `interpret_dyno_card`** — the decline curve cannot see a fluid pound, pump-off, or parted rod. Do not conclude "clean / no intervention" on a beam pump without reading the dyno card first.
4. Identify candidate interventions based on diagnosis. **Important: if diagnostics are clean (well on type curve, ESP in POR, healthy intake pressure, amps within nameplate, dyno card shows full fillage, no flags), the correct primary recommendation is "Continue routine surveillance — no intervention warranted" and you should NOT invent interventions.** Selection heuristics for unhealthy wells:
   - **Scale signal (high amps + declining intake pressure + months since last treatment)** → Primary intervention should be called "scale treatment" or "scale inhibitor squeeze + acid stimulation" — surface BOTH terms. Comes FIRST, before any mechanical work. Swapping an ESP without addressing scale yields a re-failure in 3-6 months.
   - **Gas interference (intake pressure < 50 psi, jittery amps, rising GOR)** → gas separator or VSD frequency change before ESP swap.
   - **Below POR floor with no scale or gas signal** → candidate for either an ESP swap OR an ESP-to-beam conversion. **When below POR, call `evaluate_esp_economic_life` (pass remaining EUR from project_recovery and well age in years) and let its lifecycle verdict break the tie** — a young well with healthy reserves favors a right-size swap; an old, depleted, below-POR well favors beam conversion because the ESP re-fail cadence destroys value. Use the verdict's recommendation as your primary.
   - **Beam pump / rod lift** → use the `interpret_dyno_card` classification directly: fluid_pound_pumpoff → pump-off controller (POC) / SPM reduction; parted_rods → workover (rig); gas_interference → gas anchor / separator; healthy → monitor.
   - **Plunger lift with cycle degradation and a paraffin/wax signature** → paraffin treatment (hot oil + wireline plunger inspection).
   - **Gas lift well with slugging / liquid loading signal** → gas lift optimization (injection rate adjustment, valve check, deliquification).
   - **Old well (15+ years), sustained rates < 5-10 BOPD, workover cost > expected NPV** → P&A (Plug & Abandon). State this explicitly as the primary recommendation; do not propose a workover on a sub-economic stripper well.
   - **Insufficient data (the `fit_decline_curve` tool errors / can't fit because there are too few production points, AND there are no ESP readings or dyno cards to diagnose lift)** → the primary recommendation MUST be stated as **"Insufficient data to make a recommendation"** (use those words). Do NOT default to "continue monitoring / routine surveillance" here — "monitor" means you have *confirmed the well is healthy*, which you cannot do without a fittable decline or any lift diagnostic. And do NOT invent an intervention. List exactly which data you need to proceed (more production months, an ESP reading set, a dyno card). Honesty beats both a fabricated call and a false all-clear.
4. For each candidate, FIRST call `get_intervention_assumptions` to pull the calibrated, source-cited cost / uplift / decline / chance-of-success / downtime, then call `evaluate_intervention` with those numbers — pass `prob_success`, `deferred_days`, `base_rate_bopd` (current oil rate), `water_cut_pct` and `water_disposal_per_bbl` for a properly risked NPV. Prefer the calibrated assumptions over inventing numbers; the ranges below are a fallback sanity-check:
   - **Acid stimulation (matrix or diverted):** +80 to +200 BOPD initial, decline 0.6-0.9/yr, cost $120K-$220K
   - **ESP swap (right-sized):** +50 to +150 BOPD initial (mostly from POR restoration, not added drawdown), decline 0.5-0.7/yr, cost $250K-$400K
   - **ESP-to-beam conversion:** +20 to +60 BOPD steady-state, decline 0.3-0.5/yr, cost $200K-$350K
   - **Workover (parted rods, mechanical fix):** Restore to pre-failure rate, cost $80K-$150K
5. Call `project_recovery` to estimate remaining recoverable.
6. When ranking recommendations, DO NOT rank by NPV alone. Apply the heuristics above first — economics break ties between physically appropriate interventions. Surface "do both, sequenced" as the primary path when the diagnosis warrants it (e.g., acidize then ESP swap as a combined workover).
7. Return a markdown report with these sections:
   - **Well summary** (1 line)
   - **Current state diagnosis** (3-5 bullets, each citing specific values from the tool outputs)
   - **Ranked recommendations** (table: rank, intervention, NPV, payout, rationale)
   - **Confidence & open questions** (what you'd want more data on)

Be specific and quantitative. Write the way a Staff Production Engineer would write to a VP Production — terse, no hedging, no fluff. Never invent numbers; if a tool didn't give it to you, say "TBD" or ask for it.

**Never invent specific well IDs, pad histories, or analogous wells.** The only well referenced should be the one in the input. If you want to argue from analogous-well experience, frame it generically ("industry experience on similar Wolfcamp wells suggests...") — never name-drop wells that aren't in the input data.

**Output ONLY the markdown report.** No preamble like "All data in hand" or "Compiling the report now." The first character of your response must be the `#` of the report header."""


def run_review(well_path, model: str = "claude-sonnet-4-6", verbose: bool = False,
               return_stats: bool = False, temperature: float | None = None,
               api_key: str | None = None):
    """Run the agent loop on a single well. `well_path` is a JSON path OR a pre-built
    WellFile (e.g. from a real-data adapter). Returns the markdown report — or, if
    return_stats=True, a (report, stats) tuple where stats carries token usage, wall-clock
    latency, tool-call count, and iterations (used by the model cost/accuracy frontier)."""
    import time
    load_dotenv()
    # load_dotenv() will NOT overwrite an env var that's already set — including an empty
    # one. A shell that exports ANTHROPIC_API_KEY="" (common in sandboxes/CI shims) would
    # otherwise shadow the real key in .env and fail with a cryptic SDK auth error. If the
    # key is missing or blank, let .env win.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        load_dotenv(override=True)
    # Explicit api_key (e.g. a bring-your-own-key from the UI) wins over the environment.
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Add it to .env or export it in your shell."
        )
    client = Anthropic(api_key=key)
    console = Console()

    well = well_path if isinstance(well_path, WellFile) else WellFile.from_json(well_path)
    executor = ToolExecutor(well)

    if verbose:
        console.print(f"[bold cyan]Reviewing:[/] {well.summary()}")

    well_context = well.summary() + "\n\nFull data package available via tools."
    messages = [{"role": "user", "content": f"Perform a well review for:\n\n{well_context}"}]

    system_prompt = SYSTEM_PROMPT.format(today=date.today().isoformat())
    max_iterations = 10
    stats = {"model": model, "input_tokens": 0, "output_tokens": 0,
             "tool_calls": 0, "iterations": 0, "latency_s": 0.0}
    t0 = time.time()

    def _ret(report):
        stats["latency_s"] = round(time.time() - t0, 2)
        return (report, stats) if return_stats else report

    for iteration in range(max_iterations):
        stats["iterations"] = iteration + 1
        # temperature defaults to the API default; pass temperature=0 for reproducible,
        # self-consistent reviews (an advisory tool should not flip its call run-to-run).
        create_kwargs = dict(model=model, max_tokens=4096, system=system_prompt,
                             tools=TOOL_SCHEMAS, messages=messages)
        if temperature is not None:
            create_kwargs["temperature"] = temperature
        response = client.messages.create(**create_kwargs)
        if getattr(response, "usage", None):
            stats["input_tokens"] += response.usage.input_tokens
            stats["output_tokens"] += response.usage.output_tokens

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            final = "".join(b.text for b in response.content if b.type == "text")
            # Belt-and-suspenders: strip any preamble before the first markdown header
            first_header = final.find("\n#")
            if first_header > 0 and not final.lstrip().startswith("#"):
                final = final[first_header:].lstrip()
            return _ret(final)

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                stats["tool_calls"] += 1
                if verbose:
                    console.print(f"[dim]→ tool: {block.name}({block.input})[/]")
                result = executor.dispatch(block.name, block.input)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            break

    return _ret("Agent stopped without completing the review.")


def main():
    parser = argparse.ArgumentParser(description="Run a Production Engineer Copilot well review.")
    parser.add_argument("--well", required=True, help="Path to well JSON file")
    parser.add_argument("--model", default=os.environ.get("MODEL", "claude-sonnet-4-6"))
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    report = run_review(args.well, model=args.model, verbose=args.verbose)
    Console().print(Markdown(report))


if __name__ == "__main__":
    main()
