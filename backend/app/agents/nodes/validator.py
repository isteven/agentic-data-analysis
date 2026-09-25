import re

from app.agents.state import AgentState
from app.agents.trace import emit_trace

NODE_NAME = "validator"

# thousands-grouped numbers (10,430) match as one token first; otherwise a plain
# number matches without swallowing trailing sentence punctuation (a naive
# `\d[\d,]*\.?\d*` would grab the comma/period after a bare year like "2008,").
# The leading minus is only a sign when NOT immediately preceded by a word
# character, so "2024-2025" (range) and "post-2020" (hyphenated prefix) don't
# parse their second half as a negative number - only a true negative in prose
# (preceded by whitespace/punctuation/start-of-string) counts as signed.
_NUMBER_RE = re.compile(
    r"(?<!\w)-\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<!\w)-\d+(?:\.\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
)
_RELATIVE_TOLERANCE = 0.01
_YEAR_RANGE = range(1900, 2101)


def _extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.findall(text):
        cleaned = match.replace(",", "")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        # bare 4-digit numbers with no thousands separator in this range are
        # calendar years being cited alongside a value, not metric claims
        if "," not in match and value == int(value) and int(value) in _YEAR_RANGE:
            continue
        numbers.append(value)
    return numbers


def _is_grounded(value: float, known_values: list[float]) -> bool:
    for known in known_values:
        # a report may state a decrease/change as a positive magnitude even
        # though the underlying signed delta finding is negative
        for candidate in (known, abs(known)):
            if candidate == 0:
                if abs(value) < 1e-6:
                    return True
                continue
            if abs(value - candidate) / abs(candidate) <= _RELATIVE_TOLERANCE:
                return True
    return False


def _context_numbers(state: AgentState) -> list[float]:
    """Numbers that describe what was asked rather than claim a value: those in the
    question itself and inside the result's text labels (e.g. "60 Hours & Over") - in
    cells, or in column names when the query pivoted the labels into columns."""
    numbers = _extract_numbers(state["query"])
    analysis = state.get("analysis") or {}
    for column in analysis.get("columns", []):
        numbers += _extract_numbers(column)
    for row in analysis.get("rows", []):
        for cell in row:
            if isinstance(cell, str):
                numbers += _extract_numbers(cell)
    return numbers


async def validator_node(state: AgentState) -> AgentState:
    report = state.get("report_markdown") or ""
    known_values = [f["value"] for f in state["findings"] if f["value"] is not None]
    context = _context_numbers(state)

    claimed_numbers = _extract_numbers(report)
    # small integers are usually list/section numbering, not data claims - skip them
    substantive = [n for n in claimed_numbers if abs(n) >= 10]

    ungrounded = [n for n in substantive if not _is_grounded(n, known_values) and n not in context]

    if not known_values:
        state["grounded"] = None
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            "No findings were available to check the report against.",
        )
        return state

    state["grounded"] = len(ungrounded) == 0

    if state["grounded"]:
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            "All numeric claims in the report match computed findings.",
        )
    else:
        caveat = (
            "\n\n---\n*Note: this report contains figures that could not be automatically "
            "verified against the underlying data and should be double-checked.*"
        )
        state["report_markdown"] = report + caveat
        emit_trace(
            state,
            NODE_NAME,
            "observation",
            f"Found {len(ungrounded)} numeric claim(s) not matching any computed finding: {ungrounded}",
        )

    return state
