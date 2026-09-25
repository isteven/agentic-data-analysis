"""Infers how a dimension's values relate to each other, from the numbers alone.

Sources mix totals, parents and their sub-categories, overlapping buckets and parallel
classification schemes in one column, so summing every row double-counts. Nothing here
knows any dataset: each relation is found by checking that one value equals the sum of
others in every cell (time x other dimensions), within rounding.

- Hierarchy: `wholesale and retail trade` = `wholesale trade` + `retail trade`
- Grand total: a value that is the sum of its parts and >= every other value everywhere
  (MOM `Total`); values outside its tree overlap it (`More Than 48 Hours`)
- Parallel schemes: two disjoint groups with equal sums (3-group vs PME occupations);
  the group covering more cells is kept
- Classification eras: a new era starts when the set of values changes. An era whose
  relations don't form a clean tree is almost certainly coincidental sums in short or
  coarse data, so its years are reported as unverified and kept out of summable views.
"""

import itertools
import logging
import time

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TOLERANCE_UNITS = 3  # published parts and parents are rounded independently
MIN_SUPPORT = 5  # nonzero cells a relation must hold in, so it isn't luck
SEARCH_SECONDS = 2.0  # per parent; subset search is exponential in the worst case
DIMENSION_SECONDS = 20.0
MAX_SCHEME_VALUES = 12  # scheme search enumerates pairs of subsets
MAX_DIMENSION_VALUES = 100  # beyond this a column is an identifier-like list, not a tree


def rounding_unit(values: np.ndarray) -> float:
    """The coarsest power of ten every value is a multiple of (100 for vacancies, 0.1 for
    MOM thousands) - the size of one rounding step in the published figures."""
    v = values[np.isfinite(values) & (values != 0)]
    if v.size == 0:
        return 1.0
    for unit in (1000, 100, 10, 1, 0.1, 0.01):
        if np.allclose(v / unit, np.round(v / unit)):
            return unit
    return 0.001


def _wide(df: pd.DataFrame, dim: str, measure: str) -> pd.DataFrame:
    """One row per dimension value, one column per cell of every other column."""
    cells = [c for c in df.columns if c not in (dim, measure)]
    grouped = df.groupby([dim, *cells], dropna=False)[measure].sum(min_count=1)
    return grouped.unstack(cells) if cells else grouped.to_frame()


def _eras(df: pd.DataFrame, dim: str, time_col: str | None) -> list[tuple]:
    if time_col is None:
        return [(None, None)]
    value_sets = df.groupby(time_col)[dim].agg(lambda s: frozenset(s.dropna()))
    eras: list[list] = []
    for period, values in value_sets.items():
        if eras and eras[-1][2] == values:
            eras[-1][1] = period
        else:
            eras.append([period, period, values])
    return [(lo, hi) for lo, hi, _ in eras]


def _find_parts(target: np.ndarray, candidates: dict[str, np.ndarray], tol: float):
    """Smallest set of candidates whose sum matches `target` in every known nonzero cell."""
    known = np.isfinite(target) & (target != 0)
    if known.sum() < MIN_SUPPORT:
        return None
    goal = target[known]
    names = sorted(candidates, key=lambda n: -np.nansum(candidates[n][known]))
    vecs = [np.nan_to_num(candidates[n][known]) for n in names]
    suffix = np.zeros((len(vecs) + 1, goal.size))
    for k in range(len(vecs) - 1, -1, -1):
        suffix[k] = suffix[k + 1] + vecs[k]
    best: list[str] | None = None
    started = time.monotonic()

    def search(k: int, remaining: np.ndarray, chosen: list[str]) -> None:
        nonlocal best
        if time.monotonic() - started > SEARCH_SECONDS:
            return
        if best is not None and len(chosen) >= len(best):
            return
        if np.all(np.abs(remaining) <= tol):
            if len(chosen) >= 2:
                best = list(chosen)
            return
        if k == len(vecs) or np.any(remaining - suffix[k] > tol):
            return
        if np.all(remaining - vecs[k] >= -tol):
            chosen.append(names[k])
            search(k + 1, remaining - vecs[k], chosen)
            chosen.pop()
        search(k + 1, remaining, chosen)

    search(0, goal, [])
    return best


def _relations(wide: pd.DataFrame, tol: float) -> dict[str, list[str]]:
    rows = {str(v): wide.loc[v].to_numpy(dtype=float) for v in wide.index}
    relations: dict[str, list[str]] = {}
    started = time.monotonic()
    for parent, target in rows.items():
        if time.monotonic() - started > DIMENSION_SECONDS:
            logger.warning("structure inference stopped early: time budget spent")
            break
        # a part never exceeds its parent and only exists where the parent does
        candidates = {}
        for name, vec in rows.items():
            if name == parent:
                continue
            both = np.isfinite(target) & np.isfinite(vec)
            if not both.any() or np.any(np.isfinite(vec) & ~np.isfinite(target)):
                continue
            if np.all(vec[both] <= target[both] + tol):
                candidates[name] = vec
        if len(candidates) >= 2:
            parts = _find_parts(target, candidates, tol)
            if parts:
                relations[parent] = parts
    return relations


def _is_tree(relations: dict[str, list[str]]) -> bool:
    """Real hierarchies give each value one parent and no cycles; coincidental sums in
    thin data produce values claimed by several parents, or A = B and B = A."""
    parent_of: dict[str, str] = {}
    for parent, parts in relations.items():
        for part in parts:
            if part in parent_of:
                return False
            parent_of[part] = parent
    for start in parent_of:
        seen, node = {start}, start
        while node in parent_of:
            node = parent_of[node]
            if node in seen:
                return False
            seen.add(node)
    return True


def _grand_total(wide: pd.DataFrame, parent_of: dict[str, str], tol: float) -> str | None:
    roots_with_parts = set(parent_of.values()) - set(parent_of)
    for candidate in roots_with_parts:
        g = wide.loc[candidate].to_numpy(dtype=float)
        dominates = True
        for other in wide.index:
            if str(other) == candidate:
                continue
            x = wide.loc[other].to_numpy(dtype=float)
            both = np.isfinite(g) & np.isfinite(x)
            if not both.any() or np.any(x[both] > g[both] + tol):
                dominates = False
                break
        if dominates:
            return candidate
    return None


def _scheme_to_drop(wide: pd.DataFrame, tol: float) -> list[str]:
    """Two disjoint groups with equal sums are the same whole classified twice; keep the
    group covering more cells (usually the one that spans every year)."""
    values = [str(v) for v in wide.index]
    if not 3 <= len(values) <= MAX_SCHEME_VALUES:
        return []
    rows = {str(v): wide.loc[v] for v in wide.index}
    for size_a in range(1, len(values)):
        for group_a in itertools.combinations(values, size_a):
            rest = [v for v in values if v not in group_a]
            for size_b in range(1, len(rest) + 1):
                for group_b in itertools.combinations(rest, size_b):
                    if size_a + size_b < 3 or group_a > group_b:
                        continue
                    sum_a = pd.concat([rows[v] for v in group_a], axis=1).sum(
                        axis=1, min_count=size_a
                    )
                    sum_b = pd.concat([rows[v] for v in group_b], axis=1).sum(
                        axis=1, min_count=size_b
                    )
                    diff = (sum_a - sum_b).dropna()
                    diff = diff[sum_a.reindex(diff.index) != 0]
                    if len(diff) >= MIN_SUPPORT and diff.abs().max() <= tol:
                        cover_a = sum(rows[v].notna().sum() for v in group_a)
                        cover_b = sum(rows[v].notna().sum() for v in group_b)
                        return list(group_b if cover_a >= cover_b else group_a)
    return []


def infer_structure(df: pd.DataFrame, dim: str, measure: str, time_col: str | None) -> dict | None:
    """Structure of `dim` measured by `measure`, or None when nothing could be verified
    (then the measure isn't shown to be additive across this column either)."""
    # cells are time x the other dimensions; other measures would split them needlessly
    keep = [
        c
        for c in df.columns
        if c in (dim, measure, time_col) or not pd.api.types.is_numeric_dtype(df[c])
    ]
    data = df[keep].dropna(subset=[dim])
    if data[dim].nunique() > MAX_DIMENSION_VALUES:
        return None
    tol = TOLERANCE_UNITS * rounding_unit(data[measure].to_numpy(dtype=float))

    parent_of: dict[str, str] = {}
    unverified: list[list] = []
    for lo, hi in _eras(data, dim, time_col):
        era = data if lo is None else data[data[time_col].between(lo, hi)]
        relations = _relations(_wide(era, dim, measure), tol)
        if not _is_tree(relations):
            unverified.append([_native(lo), _native(hi)])
            continue
        for parent, parts in relations.items():
            for part in parts:
                parent_of.setdefault(part, parent)

    verified = data
    for lo, hi in unverified:
        verified = verified[~verified[time_col].between(lo, hi)]
    wide = _wide(verified, dim, measure) if len(verified) else None

    exclude: list[str] = []
    if wide is not None and parent_of:
        total = _grand_total(wide, parent_of, tol)
        if total is not None:
            in_tree = {total} | set(parent_of)
            exclude = [total] + sorted(str(v) for v in wide.index if str(v) not in in_tree)
            # children of the grand total are the top level; a constant level adds nothing
            parent_of = {c: p for c, p in parent_of.items() if p != total}
    elif wide is not None:
        exclude = _scheme_to_drop(wide, tol)

    if not parent_of and not exclude and not unverified:
        return None
    return {"parents": parent_of, "exclude_values": exclude, "unverified_periods": unverified}


def proves_additive(structure: dict | None) -> bool:
    """Parents equal to the sum of their parts (or a total equal to its breakdown) is
    direct evidence the measure adds up across this column."""
    return bool(structure and (structure["parents"] or structure["exclude_values"]))


def ancestor_chain(value: str, parent_of: dict[str, str]) -> list[str]:
    """[top, ..., value]"""
    chain = [value]
    while chain[-1] in parent_of:
        chain.append(parent_of[chain[-1]])
    return chain[::-1]


def _native(value):
    return value.item() if hasattr(value, "item") else value
