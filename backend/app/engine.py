"""CO attainment calculation: internal (CA) + terminal (TE).

Pure functions: no web or database code, so it is easy to test and reuse.

Per student, per CO k:
    pct[k]    = ROUND(marks under CO k / max under CO k * 100, decimals)
    te_pct[k] = same for terminal. A single terminal total counts for every CO.
Per CO k (class of N counted students):
    CA %  = students meeting EP in internals / N * 100
    TE %  = students meeting EP in terminal  / N * 100
    Total = CA % * internal weight + TE % * terminal weight
    Attained when ROUND(Total, 0) >= ELA
Students with NA placeholders were removed from the class and are never counted.

Class percentages are kept unrounded, as in the department's sheet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

from .parser import ParsedSheet

DEFAULT_PLAN = "Existing system to be retained"


class Settings(BaseModel):
    subject_code: str = ""
    subject_name: str = ""
    academic_year: str = ""
    semester: str = ""
    faculty: str = ""
    num_cos: int = Field(6, ge=1, le=12)
    ep: float = Field(70, ge=0, le=100)  # fallback when a CO has no EP of its own
    ep_by_co: list[float] = Field(default_factory=list)  # staff input: per-student bar per CO
    ela: list[float] = Field(default_factory=list)  # staff input: class target per CO
    internal_weight: float = Field(40, gt=0, le=100)  # % ; terminal = 100 - this
    operator: Literal[">=", ">"] = ">="  # internal
    terminal_operator: Literal[">=", ">"] = ">"  # department rule: CAT >= EP, terminal > EP
    decimals: int = Field(1, ge=0, le=3)
    absent_policy: Literal["zero", "exclude"] = "zero"
    terminal_absent_policy: Literal["zero", "exclude"] = "exclude"
    ela_compare: Literal["exact", "rounded"] = "rounded"
    # Columns without a CO tag (e.g. assignment A1): letter -> COs it is added to.
    untagged_mapping: dict[str, list[int]] = Field(default_factory=dict)
    # Question columns (letters) the staff chose to leave out.
    excluded_columns: list[str] = Field(default_factory=list)
    # CO number -> action plan text. Missing = default for attained COs, blank otherwise.
    action_plans: dict[int, str] = Field(default_factory=dict)

    @field_validator("ela", "ep_by_co")
    @classmethod
    def _target_range(cls, v: list[float]) -> list[float]:
        for x in v:
            if not 0 <= x <= 100:
                raise ValueError("EP and ELA values must be between 0 and 100")
        return v

    def ela_for(self, k: int) -> float | None:
        return self.ela[k - 1] if k - 1 < len(self.ela) else None

    def ep_for(self, k: int) -> float:
        return self.ep_by_co[k - 1] if k - 1 < len(self.ep_by_co) else self.ep


def round_half_up(x: np.ndarray | float, decimals: int):
    """Excel ROUND: halves go away from zero (72.5 -> 73), unlike Python's round()."""
    f = 10.0 ** decimals
    a = np.asarray(x, dtype=float)
    # round to 9 places first so 72.49999999 float noise rounds like Excel does
    scaled = np.round(np.abs(a) * f, 9)
    out = np.sign(a) * np.floor(scaled + 0.5) / f
    return out if isinstance(x, np.ndarray) else float(out)


def co_matrix(parsed: ParsedSheet, settings: Settings) -> np.ndarray:
    """questions x COs matrix of 0/1: which question counts under which CO."""
    k = settings.num_cos
    excluded = {c.upper() for c in settings.excluded_columns}
    m = np.zeros((len(parsed.questions), k), dtype=float)
    for i, q in enumerate(parsed.questions):
        if q.letter in excluded or q.max is None:
            continue
        if q.co is not None:
            if 1 <= q.co <= k:
                m[i, q.co - 1] = 1
        else:
            for co in settings.untagged_mapping.get(q.letter, []):
                if 1 <= co <= k:
                    m[i, co - 1] = 1
    return m


def terminal_matrix(parsed: ParsedSheet, settings: Settings) -> np.ndarray:
    """Terminal columns x COs. A total with no CO tags counts for every CO."""
    tq = parsed.terminal_questions
    m = np.zeros((len(tq), settings.num_cos), dtype=float)
    split = any(q.co is not None for q in tq)
    for i, q in enumerate(tq):
        if q.max is None:
            continue
        if not split:
            m[i, :] = 1
        elif q.co is not None and 1 <= q.co <= settings.num_cos:
            m[i, q.co - 1] = 1
    return m


def _meets(pct: np.ndarray, threshold: np.ndarray, op: str) -> np.ndarray:
    valid = ~np.isnan(pct)
    vals = np.nan_to_num(pct, nan=-1)
    return valid & (vals >= threshold if op == ">=" else vals > threshold)


@dataclass
class Result:
    cos: list[int]
    co_max: list[float]
    co_questions: list[list[str]]  # column letters counted under each CO
    raw: np.ndarray  # students x COs
    pct: np.ndarray  # students x COs (NaN = excluded / CO has no questions)
    included: np.ndarray  # bool per student
    meets: np.ndarray  # bool students x COs
    n: int
    count: list[int]
    ca_pct: list[float | None]
    weighted: list[float | None]
    warnings: list[str]
    has_terminal: bool = False
    terminal_mode: str = "none"  # "none" | "total" | "split"
    te_questions: list[list[str]] | None = None
    te_pct: np.ndarray | None = None
    te_meets: np.ndarray | None = None
    te_count: list[int] | None = None
    te_ca_pct: list[float | None] | None = None
    te_weighted: list[float | None] | None = None
    total: list[float | None] | None = None
    outcome: list[str | None] | None = None
    action_plans: list[str] | None = None


def compute(parsed: ParsedSheet, settings: Settings) -> Result:
    k = settings.num_cos
    students = len(parsed.regs)
    m = co_matrix(parsed, settings)
    maxes = np.array([q.max or 0.0 for q in parsed.questions])
    marks = np.nan_to_num(parsed.marks, nan=0.0)

    raw = marks @ m  # students x COs (vectorised sum per CO)
    co_max = maxes @ m
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = np.where(co_max > 0, raw * 100.0 / co_max, np.nan)
    pct = round_half_up(pct, settings.decimals)

    counted = m.sum(axis=1) > 0  # questions that count somewhere
    removed = parsed.removed if parsed.removed is not None else np.zeros(students, dtype=bool)
    included = ~removed
    left_internal = left_terminal = 0
    if settings.absent_policy == "exclude":
        has_blank = parsed.absent[:, counted].any(axis=1)
        left_internal = int((has_blank & included).sum())
        included &= ~has_blank

    # --- terminal ---------------------------------------------------------
    tq = parsed.terminal_questions
    tm = terminal_matrix(parsed, settings) if tq else np.zeros((0, k))
    t_max = np.array([q.max or 0.0 for q in tq]) @ tm if tq else np.zeros(k)
    has_terminal = bool(tq) and bool((t_max > 0).any())
    te_pct = np.full((students, k), np.nan)
    if has_terminal:
        t_raw = np.nan_to_num(parsed.terminal_marks, nan=0.0) @ tm
        with np.errstate(divide="ignore", invalid="ignore"):
            te_pct = np.where(t_max > 0, t_raw * 100.0 / t_max, np.nan)
        te_pct = round_half_up(te_pct, settings.decimals)
        if settings.terminal_absent_policy == "exclude":
            used = tm.sum(axis=1) > 0
            no_mark = parsed.terminal_absent[:, used].any(axis=1)
            left_terminal = int((no_mark & included).sum())
            included &= ~no_mark

    pct[~included, :] = np.nan
    te_pct[~included, :] = np.nan
    n = int(included.sum())

    eps = np.array([settings.ep_for(c) for c in range(1, k + 1)])
    meets = _meets(pct, eps, settings.operator)
    te_meets = _meets(te_pct, eps, settings.terminal_operator)
    count = meets.sum(axis=0).astype(int)
    te_count = te_meets.sum(axis=0).astype(int)

    w_in = settings.internal_weight / 100.0
    w_te = 1 - w_in
    warnings: list[str] = []
    ca_pct, weighted, te_ca, te_w, total, outcome, plans = [], [], [], [], [], [], []
    for i in range(k):
        co = i + 1
        ca = float(count[i]) * 100.0 / n if n and co_max[i] > 0 else None
        te = float(te_count[i]) * 100.0 / n if n and t_max[i] > 0 else None
        if co_max[i] == 0:
            warnings.append(f"CO{co} has no questions mapped to it.")
        if has_terminal and t_max[i] == 0:
            warnings.append(f"CO{co} has no terminal marks.")
        ca_pct.append(ca)
        weighted.append(None if ca is None else ca * w_in)
        te_ca.append(te)
        te_w.append(None if te is None else te * w_te)
        tot = None if ca is None or te is None else ca * w_in + te * w_te
        total.append(tot)

        ela = settings.ela_for(co)
        status = None
        if tot is not None and ela is not None:
            value = round_half_up(tot, 0) if settings.ela_compare == "rounded" else round(tot, 9)
            status = "Attained" if value >= ela else "Not Attained"
        outcome.append(status)
        plan = settings.action_plans.get(co)
        plans.append(plan if plan is not None else (DEFAULT_PLAN if status == "Attained" else ""))

    if not has_terminal:
        warnings.append("No terminal marks found, so CA + TE and outcomes cannot be calculated.")
    if removed.any():
        warnings.append(f"{int(removed.sum())} student(s) removed from the class (NA) and not counted.")
    if left_internal:
        warnings.append(f"{left_internal} student(s) left out because of blank/AB internal marks.")
    if left_terminal:
        warnings.append(f"{left_terminal} student(s) left out because they have no terminal mark.")

    excluded = {c.upper() for c in settings.excluded_columns}
    unmapped = [q.letter for q in parsed.questions
                if q.co is None and q.letter not in excluded
                and not settings.untagged_mapping.get(q.letter)]
    if unmapped:
        warnings.append("Not counted in any CO: " + ", ".join(unmapped))
    beyond = sorted({q.co for q in parsed.questions if q.co and q.co > k})
    if beyond:
        warnings.append("Questions tagged " + ", ".join(f"CO{c}" for c in beyond)
                        + f" are ignored (number of COs is {k}).")

    co_questions = [[q.letter for j, q in enumerate(parsed.questions) if m[j, i]] for i in range(k)]
    te_questions = [[q.letter for j, q in enumerate(tq) if tm[j, i]] for i in range(k)]
    mode = "none"
    if has_terminal:
        mode = "split" if any(q.co is not None for q in tq) else "total"
    return Result(
        cos=list(range(1, k + 1)), co_max=co_max.tolist(), co_questions=co_questions,
        raw=raw, pct=pct, included=included, meets=meets, n=n, count=count.tolist(),
        ca_pct=ca_pct, weighted=weighted, warnings=warnings, has_terminal=has_terminal,
        terminal_mode=mode, te_questions=te_questions, te_pct=te_pct, te_meets=te_meets,
        te_count=te_count.tolist(), te_ca_pct=te_ca, te_weighted=te_w, total=total,
        outcome=outcome, action_plans=plans,
    )
