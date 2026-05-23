"""Claude reasoning layer.

Every agent reasons through here. With a valid ANTHROPIC_API_KEY the real
Claude API is driven via tool use. Without one (or on any API error) a
deterministic rule-based "mock brain" returns the identical dict shapes, so
the full agent choreography runs and is verifiable end-to-end for free.
"""

import json
import random
from datetime import datetime

from config import DATA_FILE, HEALTHY_ROW_COUNT, MODEL, SABOTAGE_TYPES

# Always boot in MOCK, even if a key is present in the environment / .env.
# Real Claude is strictly opt-in via the dashboard AI toggle (which sets this
# True at runtime). This prevents a saved key from silently forcing slow,
# paid API calls on every startup. The key itself is still used once AI is
# explicitly enabled — anthropic.Anthropic() reads it from the environment.
USE_REAL = False


# --------------------------------------------------------------------------- #
# Real-signal inspection (shared by mock brain AND the real diagnosis tools)
# --------------------------------------------------------------------------- #
def inspect_data_state():
    """Observable facts about the working data file. No sabotage-type peeking."""
    state = {
        "exists": DATA_FILE.exists(),
        "is_list": False,
        "row_count": 0,
        "sample_keys": [],
        "temp_is_string": False,
        "has_null_temp": False,
        "timestamp_iso": True,
        "all_rows_duplicated": False,
    }
    if not state["exists"]:
        return state
    try:
        raw = json.loads(DATA_FILE.read_text())
    except Exception:
        return state
    state["is_list"] = isinstance(raw, list)
    if not state["is_list"]:
        return state
    state["row_count"] = len(raw)
    if not raw:
        return state
    first = raw[0]
    if isinstance(first, dict):
        state["sample_keys"] = sorted(first.keys())
        t = first.get("temp")
        state["temp_is_string"] = isinstance(t, str)
        state["has_null_temp"] = any(
            isinstance(r, dict) and r.get("temp") is None for r in raw
        )
        ts = first.get("timestamp")
        if isinstance(ts, str):
            try:
                datetime.fromisoformat(ts)
            except ValueError:
                state["timestamp_iso"] = False
    if state["row_count"] > HEALTHY_ROW_COUNT:
        uniq = {json.dumps(r, sort_keys=True) for r in raw}
        state["all_rows_duplicated"] = len(uniq) * 2 <= state["row_count"]
    return state


def _classify(state):
    """Map observable signals -> (failure_type, confidence, reasoning)."""
    if not state["exists"]:
        return "MISSING_FILE", 0.97, "Data file does not exist on disk."
    if not state["is_list"]:
        return "EMPTY_DATA", 0.9, "Data file is not a JSON list."
    if state["row_count"] == 0:
        return "EMPTY_DATA", 0.97, "Data file is an empty list."
    keys = set(state["sample_keys"])
    if "temperature" in keys or "location" in keys:
        return "SCHEMA_RENAME", 0.96, f"Schema keys renamed: {sorted(keys)}."
    if state["temp_is_string"]:
        return "TYPE_CORRUPTION", 0.95, "temp values are strings, not numbers."
    if state["has_null_temp"]:
        return "NULL_INJECTION", 0.94, "Some records have temp=null."
    if not state["timestamp_iso"]:
        return "DATE_FORMAT", 0.93, "timestamp is not ISO-8601 parseable."
    if state["all_rows_duplicated"]:
        return ("DUPLICATE_ROWS", 0.9,
                f"Row count {state['row_count']} >> expected "
                f"{HEALTHY_ROW_COUNT}; rows duplicated.")
    return "UNKNOWN", 0.3, "No known sabotage signature matched."


_FIX_PLANS = {
    "SCHEMA_RENAME": "Rewrite pipeline field access to the renamed keys.",
    "TYPE_CORRUPTION": "Add numeric coercion/cleaning before transform.",
    "NULL_INJECTION": "Filter out null-temp records before transform.",
    "EMPTY_DATA": "Restore the data file from baseline.",
    "MISSING_FILE": "Restore the data file from baseline.",
    "DATE_FORMAT": "Add flexible timestamp parsing to the pipeline.",
    "DUPLICATE_ROWS": "Add a deduplication step to the pipeline.",
}


# --------------------------------------------------------------------------- #
# Real Claude tool-use loop
# --------------------------------------------------------------------------- #
def _make_client():
    import anthropic

    return anthropic.Anthropic()


def _anthropic_tool_loop(system, user, tools, tool_executor, final_tool, max_turns=8):
    client = _make_client()
    messages = [{"role": "user", "content": user}]
    for _ in range(max_turns):
        # 4096 because chaos/patch tools include whole-file rewrites as args.
        # 1024 was truncating tool inputs mid-emission, dropping required fields.
        resp = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )
        tool_results = []
        final = None
        for block in resp.content:
            if block.type == "tool_use":
                if block.name == final_tool:
                    final = block.input
                else:
                    result = tool_executor(block.name, block.input)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        }
                    )
        if final is not None:
            return final
        if not tool_results:
            raise RuntimeError(f"model stopped without calling {final_tool}")
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": tool_results})
    raise RuntimeError("tool loop exceeded max turns")


# --------------------------------------------------------------------------- #
# Generative agent helpers (AI mode only). Read tools return raw text only —
# never attribution/colors/baseline, so the model stays blind to the overlay.
# --------------------------------------------------------------------------- #
from config import PIPELINE_FILE  # noqa: E402
from tools.pipeline_tools import dry_run_pipeline, get_last_output  # noqa: E402
from tools.schemas import (  # noqa: E402
    CHAOS_TOOLS,
    DIAGNOSE_TOOLS,
    PATCH_TOOLS,
    VALIDATE_TOOLS,
)


def _read_tool(name):
    if name == "read_data":
        return DATA_FILE.read_text() if DATA_FILE.exists() else "<missing>"
    if name == "read_pipeline":
        return PIPELINE_FILE.read_text()
    return {"error": "unknown tool"}


def generate_sabotage(write_fn):
    """Drive Claude to invent ONE breaking change. `write_fn(path, content)`
    performs the (whitelisted, attributed) write and returns a plain string.
    Returns the model's free-text note."""
    captured = {"note": ""}

    def executor(name, inp):
        if name == "sabotage_file":
            if "content" not in inp or "path" not in inp:
                return "error: sabotage_file requires path and content fields"
            captured["note"] = inp.get("note", "")
            return write_fn(inp["path"], inp["content"])  # plain string only
        return _read_tool(name)

    _anthropic_tool_loop(
        "You are a chaos engineering agent attacking a weather ETL. Inspect the "
        "data and pipeline, then introduce ONE small, plausible breaking change "
        "to exactly ONE file via sabotage_file. Keep it subtle and realistic. "
        "Call done when finished.",
        "Investigate, then sabotage one file.",
        CHAOS_TOOLS,
        executor,
        final_tool="done",
    )
    return captured["note"]


# --------------------------------------------------------------------------- #
# Public reasoning API (real -> Claude tool use, else -> deterministic mock)
# --------------------------------------------------------------------------- #
def decide_sabotage(recent_types):
    """Pick a sabotage, weighted away from recently used ones."""
    pool = [s for s in SABOTAGE_TYPES if s not in recent_types[-2:]] or SABOTAGE_TYPES
    if not USE_REAL:
        return random.choice(pool)
    try:
        tools = [
            {
                "name": "choose_sabotage",
                "description": "Select which sabotage to apply.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "sabotage": {"type": "string", "enum": SABOTAGE_TYPES}
                    },
                    "required": ["sabotage"],
                },
            }
        ]
        out = _anthropic_tool_loop(
            "You are a chaos engineering agent. Pick ONE sabotage to apply to "
            "a data pipeline. Avoid repeating recent ones.",
            f"Recently used (avoid these): {recent_types[-3:]}. "
            f"Available: {SABOTAGE_TYPES}. Choose one via the tool.",
            tools,
            lambda n, i: {},
            "choose_sabotage",
        )
        choice = out.get("sabotage")
        return choice if choice in SABOTAGE_TYPES else random.choice(pool)
    except Exception:
        return random.choice(pool)


def diagnose(pipeline_error):
    """Return {failure_type, confidence, reasoning, suggested_fix}."""
    state = inspect_data_state()
    if not USE_REAL:
        ftype, conf, reason = _classify(state)
        return {
            "failure_type": ftype,
            "confidence": conf,
            "reasoning": reason,
            "suggested_fix": _FIX_PLANS.get(ftype, "Escalate to a human."),
        }
    try:
        return _anthropic_tool_loop(
            "You diagnose data-pipeline failures. Read the data and the "
            "pipeline source, reason about the root cause in your own words, "
            "then submit_diagnosis. `failure_type` is a short free-text label "
            "you choose (not from a fixed list). Base it on what you observe.",
            f"The pipeline failed with error:\n{pipeline_error}\n\n"
            "Investigate the files and submit your diagnosis.",
            DIAGNOSE_TOOLS,
            lambda name, _inp: _read_tool(name),
            "submit_diagnosis",
        )
    except Exception as e:
        ftype, conf, reason = _classify(state)
        return {
            "failure_type": ftype,
            "confidence": conf,
            "reasoning": f"[mock fallback after API error: {e}] {reason}",
            "suggested_fix": _FIX_PLANS.get(ftype, "Escalate to a human."),
        }


def generate_patch(diag, write_fn, feedback=None):
    """Drive Claude to read files and write a fix. `write_fn(path, content)`
    performs the attributed heal write and returns a plain string. Returns
    {"summary": str}."""

    def executor(name, inp):
        if name == "write_file":
            if "content" not in inp or "path" not in inp:
                return "error: write_file requires path and content fields"
            return write_fn(inp["path"], inp["content"])
        if name == "dry_run":
            return dry_run_pipeline()
        return _read_tool(name)

    extra = f"\nA previous attempt failed validation: {feedback}" if feedback else ""
    return _anthropic_tool_loop(
        "You repair a broken weather ETL. Read the data and pipeline, find the "
        "fault, and WRITE a fix (to the data and/or pipeline.py) so the pipeline "
        "produces clean, consistent rows. You may dry_run to check your fix. Do "
        "not assume any reference or baseline exists — reason from the files." + extra,
        f"Diagnosis: {diag.get('reasoning', '')}. Fix it, then submit_patch.",
        PATCH_TOOLS,
        executor,
        "submit_patch",
    )


def judge_output():
    """AI validator: run the pipeline, judge whether output is clean data.
    Returns {"passed": bool, "reasoning": str}."""

    def executor(name, _inp):
        if name == "run_output":
            return {"result": dry_run_pipeline(), "output": get_last_output()}
        return _read_tool(name)

    return _anthropic_tool_loop(
        "You validate a weather ETL's output. Run it via run_output, then judge "
        "whether the output is clean, internally-consistent data (uniform keys, "
        "consistent types, sane row count, no nulls). Submit your judgment.",
        "Validate the current pipeline output.",
        VALIDATE_TOOLS,
        executor,
        "submit_judgment",
    )


def plan_patch(failure_type):
    """Return a short human-readable description of the intended fix."""
    return _FIX_PLANS.get(failure_type, "Escalate: no known fix.")
