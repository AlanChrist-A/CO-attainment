"""Read a department marks sheet into a structured, numeric form.

Expected layout (same as the department's existing Excel):
    row N-1 : component labels   (CAT1 / CAT2 / A1 ... ; merged cells are fine)
    row N   : CO label per question (CO1, CO2 ...; blank for assignments)
    row N+1 : max marks per question
    rows    : one student per row (Reg No, Name, marks ...)

The CO row is found by looking for cells like "CO1", so extra title rows
above, or a different number of questions, do not matter.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
from python_calamine import CalamineWorkbook

# Accepts the common typo C04 (zero instead of the letter O).
CO_RE = re.compile(r"^\s*C\s*[O0]\s*[-_.]?\s*(\d{1,2})\s*$", re.IGNORECASE)
ABSENT_RE = re.compile(r"^\s*(AB|A|ABS|ABSENT|NA|N/A|N\.A\.?|-)\s*$", re.IGNORECASE)
# NA is a placeholder for a student removed from the class (not an absence).
REMOVED_RE = re.compile(r"^\s*(NA|N/A|N\.A\.?)\s*$", re.IGNORECASE)
# Columns to the right of the marks that hold totals / computed blocks.
STOP_RE = re.compile(r"INTERNAL|TOTAL|ATTAIN|RESULT|%|PERCENT", re.IGNORECASE)
TERMINAL_RE = re.compile(r"TERMINAL|END\s*SEM|EXTERNAL|\bESE\b|SEMESTER", re.IGNORECASE)

MAX_LISTED_ISSUES = 40


def col_letter(idx: int) -> str:
    """0-based column index -> Excel letters (0 -> A)."""
    s = ""
    idx += 1
    while idx:
        idx, r = divmod(idx - 1, 26)
        s = chr(65 + r) + s
    return s


def cell_ref(row: int, col: int) -> str:
    return f"{col_letter(col)}{row + 1}"


@dataclass
class Question:
    col: int  # 0-based column index
    letter: str
    component: str
    co: int | None  # None = not tagged to a CO (e.g. assignment)
    max: float | None


@dataclass
class Issue:
    level: str  # "error" | "warning" | "info"
    message: str
    cell: str | None = None


@dataclass
class ParsedSheet:
    sheet: str
    sheet_names: list[str]
    component_row: int | None  # 0-based
    co_row: int
    max_row: int
    reg_col: int | None
    name_col: int | None
    questions: list[Question]
    regs: list[str]
    names: list[str]
    rows: list[int]  # 0-based sheet row of each student
    marks: np.ndarray  # students x questions, NaN where blank/absent/invalid
    absent: np.ndarray  # bool, True where the cell is blank or marked absent
    issues: list[Issue] = field(default_factory=list)
    ignored: list[dict] = field(default_factory=list)
    terminal_questions: list[Question] = field(default_factory=list)
    terminal_marks: np.ndarray | None = None  # students x terminal columns
    terminal_absent: np.ndarray | None = None
    sheet_ep: dict[int, float] = field(default_factory=dict)  # EP/ELA table in the sheet
    sheet_ela: dict[int, float] = field(default_factory=dict)
    removed: np.ndarray | None = None  # bool per student: has NA placeholders

    @property
    def detected_cos(self) -> list[int]:
        return sorted({q.co for q in self.questions if q.co is not None})


class SheetFormatError(ValueError):
    pass


def _to_float(v) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _find_co_row(grid: list[list], limit: int = 40) -> int | None:
    best, best_count = None, 1
    for r, row in enumerate(grid[:limit]):
        count = sum(1 for v in row if isinstance(v, str) and CO_RE.match(v))
        if count > best_count:
            best, best_count = r, count
    return best


def _terminal_columns(grid, comp_row, co_row, max_row, width) -> list[Question]:
    """Terminal block: one total column, or one column per CO."""
    if comp_row is None:
        return []
    start = next((c for c in range(width)
                  if TERMINAL_RE.search(_text(grid[comp_row][c]))), None)
    if start is None:
        return []
    label = _text(grid[comp_row][start])
    out: list[Question] = []
    for c in range(start, width):
        if c > start and _text(grid[comp_row][c]):
            break
        mx = _to_float(grid[max_row][c])
        co_m = CO_RE.match(_text(grid[co_row][c]))
        if mx is None and not co_m:
            break
        out.append(Question(c, col_letter(c), label, int(co_m.group(1)) if co_m else None,
                            mx if mx and mx > 0 else None))
    return out


def _find_targets(grid, start: int) -> tuple[dict[int, float], dict[int, float]]:
    """Read the small EP / ELA table below the student rows, if the sheet has one."""
    for r in range(start, len(grid)):
        labels = {_text(v).upper(): c for c, v in enumerate(grid[r])}
        if "EP" not in labels or "ELA" not in labels:
            continue
        ep_c, ela_c = labels["EP"], labels["ELA"]
        ep, ela = {}, {}
        for row in grid[r + 1:r + 13]:
            m = next((CO_RE.match(_text(v)) for v in row[:ep_c] if CO_RE.match(_text(v))), None)
            if not m:
                continue
            k = int(m.group(1))
            if (x := _to_float(row[ep_c])) is not None:
                ep[k] = x
            if (x := _to_float(row[ela_c])) is not None:
                ela[k] = x
        return ep, ela
    return {}, {}


def load_workbook_grids(data: bytes) -> tuple[list[str], dict[str, list[list]]]:
    try:
        wb = CalamineWorkbook.from_filelike(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - calamine raises several types
        raise SheetFormatError(f"Could not open the file as an Excel workbook ({exc}).") from exc
    grids = {}
    for name in wb.sheet_names:
        try:
            grids[name] = wb.get_sheet_by_name(name).to_python(skip_empty_area=False)
        except Exception:  # noqa: BLE001 - chart sheets etc.
            continue
    return wb.sheet_names, grids


def pick_sheet(grids: dict[str, list[list]]) -> str:
    for name, grid in grids.items():
        if _find_co_row(grid) is not None:
            return name
    raise SheetFormatError(
        "No sheet with a CO header row was found. The sheet needs a row with "
        "labels like CO1, CO2 ... above the max-marks row."
    )


def parse_workbook(data: bytes, sheet: str | None = None) -> ParsedSheet:
    sheet_names, grids = load_workbook_grids(data)
    if not grids:
        raise SheetFormatError("The workbook has no readable sheets.")
    if sheet is None:
        sheet = pick_sheet(grids)
    if sheet not in grids:
        raise SheetFormatError(f"Sheet '{sheet}' not found.")
    return parse_grid(grids[sheet], sheet, sheet_names)


def parse_grid(grid: list[list], sheet: str, sheet_names: list[str]) -> ParsedSheet:
    width = max((len(r) for r in grid), default=0)
    grid = [list(r) + [""] * (width - len(r)) for r in grid]

    co_row = _find_co_row(grid)
    if co_row is None:
        raise SheetFormatError(
            f"Sheet '{sheet}' has no CO header row (cells like CO1, CO2 ...)."
        )
    max_row = co_row + 1
    if max_row >= len(grid):
        raise SheetFormatError("The max-marks row below the CO row is missing.")
    comp_row = co_row - 1 if co_row > 0 else None

    issues: list[Issue] = []
    ignored: list[dict] = []
    questions: list[Question] = []

    # --- question columns -------------------------------------------------
    def comp_label(c: int) -> str:
        return _text(grid[comp_row][c]) if comp_row is not None else ""

    def is_question_like(c: int) -> bool:
        co_txt = _text(grid[co_row][c])
        return bool(CO_RE.match(co_txt)) or (
            _to_float(grid[max_row][c]) is not None and comp_label(c) != ""
        )

    start = next((c for c in range(width) if is_question_like(c)), None)
    if start is None:
        raise SheetFormatError("No question columns were found next to the CO row.")

    seen_components: list[str] = []
    current = ""
    empty_run = 0
    for c in range(start, width):
        raw_comp = comp_label(c)
        co_txt = _text(grid[co_row][c])
        mx = _to_float(grid[max_row][c])
        co_m = CO_RE.match(co_txt)

        if raw_comp:
            if STOP_RE.search(raw_comp):
                ignored.append({"from": col_letter(c), "label": raw_comp,
                                "reason": "Computed block - not read as marks"})
                break
            if TERMINAL_RE.search(raw_comp):
                current = raw_comp  # read separately below
                continue
            if raw_comp.upper() in (s.upper() for s in seen_components):
                # Same component label again => a per-CO summary block starts.
                ignored.append({"from": col_letter(c), "label": raw_comp,
                                "reason": "Repeated block (likely per-CO sums) - not read as marks"})
                break
            seen_components.append(raw_comp)
            current = raw_comp

        if TERMINAL_RE.search(current):
            continue

        if not co_m and mx is None:
            empty_run += 1
            if empty_run >= 2:
                break
            continue
        empty_run = 0

        co = int(co_m.group(1)) if co_m else None
        if co_m and "0" == co_txt.replace(" ", "").upper()[1]:
            issues.append(Issue("info", f"Read '{co_txt}' as CO{co}", cell_ref(co_row, c)))
        if co_txt and not co_m:
            issues.append(Issue("warning", f"Unrecognised CO label '{co_txt}'", cell_ref(co_row, c)))
        if mx is None:
            issues.append(Issue("error", "Max marks missing for this question", cell_ref(max_row, c)))
        elif mx <= 0:
            issues.append(Issue("error", "Max marks must be greater than 0", cell_ref(max_row, c)))
            mx = None
        questions.append(Question(c, col_letter(c), current or "Marks", co, mx))

    if not questions:
        raise SheetFormatError("No question columns were found.")

    # --- Reg No / Name columns ----------------------------------------------
    first_q = questions[0].col
    data_start = max_row + 1
    sample_rows = grid[data_start:data_start + 10]
    left_cols = [c for c in range(first_q)
                 if any(_text(r[c]) for r in sample_rows)]
    reg_col = left_cols[0] if left_cols else None
    name_col = None
    for c in left_cols[1:]:
        if any(_text(r[c]) and _to_float(r[c]) is None for r in sample_rows):
            name_col = c
            break

    # --- student rows ---------------------------------------------------------
    regs, names, rows = [], [], []
    mark_rows, absent_rows, term_rows, term_absent_rows, removed_rows = [], [], [], [], []
    qcols = [q.col for q in questions]
    terminal = _terminal_columns(grid, comp_row, co_row, max_row, width)
    for q in terminal:
        if q.max is None:
            issues.append(Issue("error", "Terminal max marks missing", cell_ref(max_row, q.col)))
    over_max = invalid = 0

    def read(q: Question, v, r: int) -> tuple[float, bool]:
        nonlocal over_max, invalid
        t = _text(v)
        if t == "" or ABSENT_RE.match(t):
            return np.nan, True
        f = _to_float(v)
        if f is None:
            invalid += 1
            if invalid <= MAX_LISTED_ISSUES:
                issues.append(Issue("error", f"Not a number: '{t}'", cell_ref(r, q.col)))
            return np.nan, False
        if f < 0:
            issues.append(Issue("error", f"Negative mark {f:g}", cell_ref(r, q.col)))
        elif q.max is not None and f > q.max:
            over_max += 1
            if over_max <= MAX_LISTED_ISSUES:
                issues.append(Issue("error", f"Mark {f:g} is above max {q.max:g}", cell_ref(r, q.col)))
        return f, False

    for r in range(data_start, len(grid)):
        row = grid[r]
        reg = _text(row[reg_col]) if reg_col is not None else ""
        name = _text(row[name_col]) if name_col is not None else ""
        cells = [row[c] for c in qcols]
        if not reg and not name and all(_text(v) == "" for v in cells):
            break  # first empty row ends the student list
        pairs = [read(q, v, r) for q, v in zip(questions, cells)]
        term_pairs = [read(q, row[q.col], r) for q in terminal]
        regs.append(reg or str(len(regs) + 1))
        names.append(name)
        rows.append(r)
        mark_rows.append([p[0] for p in pairs])
        absent_rows.append([p[1] for p in pairs])
        term_rows.append([p[0] for p in term_pairs])
        term_absent_rows.append([p[1] for p in term_pairs])
        removed_rows.append(any(REMOVED_RE.match(_text(v))
                                for v in cells + [row[q.col] for q in terminal]))

    if not rows:
        raise SheetFormatError("No student rows were found below the max-marks row.")
    if over_max > MAX_LISTED_ISSUES:
        issues.append(Issue("error", f"{over_max - MAX_LISTED_ISSUES} more marks above max not listed"))
    if invalid > MAX_LISTED_ISSUES:
        issues.append(Issue("error", f"{invalid - MAX_LISTED_ISSUES} more non-numeric cells not listed"))

    marks = np.array(mark_rows, dtype=float)
    absent_arr = np.array(absent_rows, dtype=bool)
    removed = np.array(removed_rows, dtype=bool)
    if removed.any():
        who = ", ".join(f"{names[i] or regs[i]} (row {rows[i] + 1})" for i in np.flatnonzero(removed))
        issues.append(Issue("info", f"Removed from class (NA), not counted: {who}"))

    blank_count = int(absent_arr[~removed].sum())
    if blank_count:
        affected = int(absent_arr[~removed].any(axis=1).sum())
        issues.append(Issue("warning", f"{blank_count} blank or absent (AB) cells across "
                                       f"{affected} student(s)"))

    term_marks = term_absent = None
    if terminal:
        term_marks = np.array(term_rows, dtype=float)
        term_absent = np.array(term_absent_rows, dtype=bool)
        missing = np.flatnonzero(term_absent.any(axis=1) & ~removed)
        if len(missing):
            shown = ", ".join(f"{names[i] or regs[i]} (row {rows[i] + 1})" for i in missing[:5])
            more = f" and {len(missing) - 5} more" if len(missing) > 5 else ""
            issues.append(Issue("warning", f"No terminal mark for {len(missing)} student(s): {shown}{more}"))

    seen: dict[str, int] = {}
    for reg, r in zip(regs, rows):
        if reg in seen:
            issues.append(Issue("warning", f"Duplicate Reg No {reg} (rows {seen[reg] + 1} and {r + 1})",
                                cell_ref(r, reg_col or 0)))
        else:
            seen[reg] = r

    untagged = [q.letter for q in questions if q.co is None]
    if untagged:
        issues.append(Issue("info", "Columns without a CO tag (choose how they count): "
                                    + ", ".join(untagged)))

    sheet_ep, sheet_ela = _find_targets(grid, rows[-1] + 1)

    return ParsedSheet(
        sheet=sheet, sheet_names=sheet_names, component_row=comp_row, co_row=co_row,
        max_row=max_row, reg_col=reg_col, name_col=name_col, questions=questions,
        regs=regs, names=names, rows=rows, marks=marks, absent=absent_arr,
        issues=issues, ignored=ignored, terminal_questions=terminal,
        terminal_marks=term_marks, terminal_absent=term_absent,
        sheet_ep=sheet_ep, sheet_ela=sheet_ela, removed=removed,
    )
