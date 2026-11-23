"""Write results back into the uploaded workbook as live Excel formulas.

The original sheets are left untouched. Three sheets are added:
  - "CO Calculation": per-student CO marks, CO % and terminal %
  - "CO Attainment":  per-CO class working (COUNTIF, CA, TE, CA + TE, outcome)
  - "CO Report":      the one-page form staff print and sign
Settings (EP, weights, ELA) live in cells, so staff can change them in Excel
and everything recalculates.
"""

from __future__ import annotations

import io

from openpyxl import load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter as L
from openpyxl.worksheet.properties import PageSetupProperties

from .engine import Result, Settings
from .parser import ParsedSheet

CALC = "CO Calculation"
SUMMARY = "CO Attainment"
REPORT = "CO Report"

BOLD = Font(bold=True)
TITLE = Font(bold=True, size=13)
MUTED = Font(color="666666", italic=True)
HEAD_FILL = PatternFill("solid", fgColor="EEF1F3")
INPUT_FILL = PatternFill("solid", fgColor="FFF8E1")
THIN = Side(style="thin", color="C9CED3")
DARK = Side(style="thin", color="000000")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FORM_BOX = Border(left=DARK, right=DARK, top=DARK, bottom=DARK)
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)


def _q(sheet: str) -> str:
    return "'" + sheet.replace("'", "''") + "'!"


def _fmt(decimals: int) -> str:
    return "0" if decimals == 0 else "0." + "0" * decimals


def _unique(wb, name: str) -> str:
    base, i = name, 2
    while name in wb.sheetnames:
        name = f"{base} ({i})"
        i += 1
    return name


def _is_text_number(v) -> bool:
    if not isinstance(v, str) or v.startswith("="):
        return False
    try:
        float(v.strip())
    except ValueError:
        return False
    return True


def build_output(data: bytes, parsed: ParsedSheet, settings: Settings, result: Result) -> bytes:
    try:
        wb = load_workbook(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Only .xlsx files can be written back. Save the file as .xlsx and retry.") from exc

    src_ws = wb[parsed.sheet]
    src = _q(parsed.sheet)

    def arg(letter: str, row: int, absolute: bool = False) -> str:
        """Cell reference for SUM. Numbers stored as text are converted, since SUM skips them."""
        ref = f"{src}${letter}${row}" if absolute else f"{src}{letter}{row}"
        return f"VALUE({ref})" if _is_text_number(src_ws[f"{letter}{row}"].value) else ref

    k = settings.num_cos
    dp = settings.decimals
    num_fmt = _fmt(dp)
    has_te = result.has_terminal
    src_max_row = parsed.max_row + 1

    # ---------------- CO Calculation ----------------
    ws = wb.create_sheet(_unique(wb, CALC))
    calc_name = ws.title
    ws["A1"] = f"CO calculation - {settings.subject_code} {settings.subject_name}".strip()
    ws["A1"].font = TITLE
    ws["A2"] = (f"Marks read from sheet '{parsed.sheet}'. CO marks = sum of questions tagged to "
                f"that CO; CO % = ROUND(marks / max x 100, {dp}).")
    ws["A2"].font = MUTED

    hr = 4
    mark_c, pct_c = 3, 3 + k
    te_c = 3 + 2 * k
    inc_c = te_c + k if has_te else te_c
    ws.cell(hr, 1, "Reg. No")
    ws.cell(hr, 2, "Name")
    groups = [(mark_c, "CO marks"), (pct_c, "Internal CO %")] + ([(te_c, "Terminal %")] if has_te else [])
    for start, label in groups:
        ws.cell(hr - 1, start, label)
        ws.merge_cells(start_row=hr - 1, start_column=start, end_row=hr - 1, end_column=start + k - 1)
        for i in range(k):
            ws.cell(hr, start + i, f"CO{i + 1}")
    ws.cell(hr, inc_c, "Counted")
    for c in range(1, inc_c + 1):
        for r in (hr - 1, hr):
            cell = ws.cell(r, c)
            cell.font = BOLD
            cell.fill = HEAD_FILL
            cell.alignment = CENTER
            cell.border = BOX

    mr = hr + 1
    ws.cell(mr, 2, "Max marks").font = BOLD
    for i, cols in enumerate(result.co_questions):
        cell = ws.cell(mr, mark_c + i)
        cell.value = (f"=SUM({','.join(arg(c, src_max_row, True) for c in cols)})" if cols else 0)
        cell.font = BOLD
        cell.border = BOX
        pc = ws.cell(mr, pct_c + i, 100 if cols else None)
        pc.font = BOLD
        pc.border = BOX
        if has_te:
            tc = ws.cell(mr, te_c + i, 100 if result.te_questions[i] else None)
            tc.font = BOLD
            tc.border = BOX

    first = mr + 1
    for s, src_row0 in enumerate(parsed.rows):
        r = first + s
        sr = src_row0 + 1
        ws.cell(r, 1, f"={src}{L(parsed.reg_col + 1)}{sr}" if parsed.reg_col is not None
                else parsed.regs[s])
        ws.cell(r, 2, f"={src}{L(parsed.name_col + 1)}{sr}" if parsed.name_col is not None
                else parsed.names[s])
        ws.cell(r, inc_c, "Yes" if result.included[s] else "No").alignment = CENTER
        inc_ref = f"${L(inc_c)}{r}"
        for i, cols in enumerate(result.co_questions):
            if cols:
                ws.cell(r, mark_c + i).value = f"=SUM({','.join(arg(c, sr) for c in cols)})"
                mref, maxref = f"{L(mark_c + i)}{r}", f"{L(mark_c + i)}${mr}"
                p = ws.cell(r, pct_c + i)
                p.value = f'=IF({inc_ref}="Yes",ROUND({mref}/{maxref}*100,{dp}),"")'
                p.number_format = num_fmt
            if has_te and result.te_questions[i]:
                tcols = result.te_questions[i]
                got = ",".join(arg(c, sr) for c in tcols)
                out_of = ",".join(arg(c, src_max_row, True) for c in tcols)
                t = ws.cell(r, te_c + i)
                t.value = f'=IF({inc_ref}="Yes",ROUND(SUM({got})/SUM({out_of})*100,{dp}),"")'
                t.number_format = num_fmt
    last = first + len(parsed.rows) - 1

    ws.column_dimensions["A"].width = 19
    ws.column_dimensions["B"].width = 24
    for c in range(3, inc_c + 1):
        ws.column_dimensions[L(c)].width = 8
    ws.column_dimensions[L(inc_c)].width = 9
    ws.freeze_panes = ws.cell(first, 3)

    # ---------------- CO Attainment ----------------
    ss = wb.create_sheet(_unique(wb, SUMMARY))
    summary_name = ss.title
    calc = _q(calc_name)
    ss["A1"] = f"CO attainment ({settings.subject_code} {settings.subject_name})".strip()
    ss["A1"].font = TITLE
    ss["A2"] = "Yellow cells are settings - change them here and the sheet recalculates."
    ss["A2"].font = MUTED

    inc_col = L(inc_c)
    labels = [
        ("Internal: student meets EP when", settings.operator, True),
        ("Terminal: student meets EP when", settings.terminal_operator, True),
        ("Internal weight %", settings.internal_weight, True),
        ("Terminal weight %", "=100-$B$6", False),
        ("Students counted (N)", f'=COUNTIF({calc}${inc_col}${first}:${inc_col}${last},"Yes")', False),
        ("Compare with ELA (Exact / Rounded)", settings.ela_compare.capitalize(), True),
    ]
    for i, (lab, val, editable) in enumerate(labels):
        r = 4 + i
        ss.cell(r, 1, lab).font = BOLD
        c = ss.cell(r, 2, val)
        c.border = BOX
        c.alignment = CENTER
        if editable:
            c.fill = INPUT_FILL
    op, te_op, w_in, w_te, n, cmp_mode = (f"$B${r}" for r in range(4, 10))

    th = 12
    heads = ["CO", "Max marks", "EP %", "ELA %", "Students meeting EP (CA)", "CA %",
             "CA weighted", "Students meeting EP (TE)", "TE %", "TE weighted",
             "CA + TE", "Outcome", "Action plan"]
    for j, h in enumerate(heads, start=1):
        c = ss.cell(th, j, h)
        c.font = BOLD
        c.fill = HEAD_FILL
        c.alignment = CENTER
        c.border = BOX
    ss.row_dimensions[th].height = 48

    for i in range(k):
        r = th + 1 + i
        has = bool(result.co_questions[i])
        has_t = has_te and bool(result.te_questions[i])
        pc, tc = L(pct_c + i), L(te_c + i)
        vals = [
            f"CO{i + 1}",
            f"={calc}{L(mark_c + i)}{mr}",
            settings.ep_for(i + 1),
            settings.ela_for(i + 1),
            f"=COUNTIF({calc}${pc}${first}:${pc}${last},{op}&$C{r})" if has else "-",
            f'=IF({n}=0,"",E{r}/{n}*100)' if has else "-",
            f'=IF(F{r}="","",F{r}*{w_in}/100)' if has else "-",
            f"=COUNTIF({calc}${tc}${first}:${tc}${last},{te_op}&$C{r})" if has_t else "-",
            f'=IF({n}=0,"",H{r}/{n}*100)' if has_t else "-",
            f'=IF(I{r}="","",I{r}*{w_te}/100)' if has_t else "-",
            f'=IF(AND(ISNUMBER(G{r}),ISNUMBER(J{r})),G{r}+J{r},"")',
            f'=IF(OR(K{r}="",D{r}=""),"",IF(IF({cmp_mode}="Rounded",ROUND(K{r},0),ROUND(K{r},9))>=D{r},'
            '"Attained","Not Attained"))',
            result.action_plans[i],
        ]
        for j, v in enumerate(vals, start=1):
            c = ss.cell(r, j, v)
            c.border = BOX
            c.alignment = LEFT if j == 13 else CENTER
            if j in (6, 7, 9, 10, 11):
                c.number_format = "0.00"
            if j in (3, 4, 13):
                c.fill = INPUT_FILL
        ss.cell(r, 1).font = BOLD
        ss.cell(r, 11).font = BOLD

    note_r = th + k + 2
    notes = [
        "CA + TE = CA % x internal weight + TE % x terminal weight. A CO is attained when CA + TE "
        + ("rounded to a whole number " if settings.ela_compare == "rounded" else "") + "reaches ELA.",
        "Questions counted per CO: " + "; ".join(
            f"CO{i + 1}: {', '.join(cols) or 'none'}" for i, cols in enumerate(result.co_questions)),
    ]
    for i, t in enumerate(notes):
        ss.cell(note_r + i, 1, t).font = MUTED

    ss.column_dimensions["A"].width = 34
    for c, w in zip("BCDEFGHIJKLM", (10, 7, 7, 12, 9, 10, 12, 9, 10, 9, 14, 36)):
        ss.column_dimensions[c].width = w

    # ---------------- CO Report (print and sign) ----------------
    rp = wb.create_sheet(_unique(wb, REPORT))
    sm = _q(summary_name)
    span = max(k, 6)
    last_col = span + 1
    course = f"{settings.subject_code} {settings.subject_name}".strip()
    year_sem = " / ".join(x for x in (settings.academic_year, settings.semester) if x)
    for r, (lab, val) in enumerate([("Course Code & Name", course), ("Academic Year / Semester", year_sem),
                                    ("Course Faculty", settings.faculty)], start=1):
        rp.cell(r, 1, f"{lab}  :").font = BOLD
        rp.cell(r, 2, val)
        rp.merge_cells(start_row=r, start_column=2, end_row=r, end_column=last_col)
        rp.row_dimensions[r].height = 20

    rp.cell(5, 1, "CO Attainment").font = BOLD
    t = 6
    rp.cell(t, 1, None)
    for i in range(k):
        rp.cell(t, 2 + i, f"CO{i + 1}").font = BOLD
    total_fmt = "0" if settings.ela_compare == "rounded" else "0.00"
    for row_i, (lab, col, fmt) in enumerate([("Expected Proficiency (EP)", "C", "0.##"),
                                             ("Expected level of attainment (ELA)", "D", "0.##"),
                                             ("Total CO Attainment (CA+TE)", "K", total_fmt)], start=1):
        rp.cell(t + row_i, 1, lab)
        for i in range(k):
            ref = f"{sm}{col}{th + 1 + i}"
            c = rp.cell(t + row_i, 2 + i, f'=IF({ref}="","",{ref})')
            c.number_format = "General" if fmt == "0.##" else fmt
    for r in range(t, t + 4):
        for c in range(1, k + 2):
            cell = rp.cell(r, c)
            cell.border = FORM_BOX
            cell.alignment = LEFT if c == 1 else CENTER
        rp.row_dimensions[r].height = 22

    t2 = t + 5
    rp.cell(t2, 1, "COs")
    rp.cell(t2, 2, "Outcome\nAttained / Not-attained")
    rp.cell(t2, 4, "Action Plan for Improvement")
    rp.merge_cells(start_row=t2, start_column=2, end_row=t2, end_column=3)
    rp.merge_cells(start_row=t2, start_column=4, end_row=t2, end_column=last_col)
    rp.row_dimensions[t2].height = 48
    for i in range(k):
        r = t2 + 1 + i
        s_r = th + 1 + i
        rp.cell(r, 1, f"CO{i + 1}")
        rp.cell(r, 2, f'=IF({sm}L{s_r}="","",{sm}L{s_r})').font = BOLD
        rp.cell(r, 4, f'=IF({sm}M{s_r}="","",{sm}M{s_r})')
        rp.merge_cells(start_row=r, start_column=2, end_row=r, end_column=3)
        rp.merge_cells(start_row=r, start_column=4, end_row=r, end_column=last_col)
        rp.row_dimensions[r].height = 32
    for r in range(t2, t2 + k + 1):
        for c in range(1, last_col + 1):
            cell = rp.cell(r, c)
            cell.border = FORM_BOX
            cell.alignment = LEFT if c >= 4 and r > t2 else CENTER
            if r == t2:
                cell.font = BOLD

    sign = t2 + k + 4
    rp.cell(sign, 1, "Faculty Signature").font = BOLD
    hod = rp.cell(sign, last_col, "HoD Signature")
    hod.font = BOLD
    hod.alignment = Alignment(horizontal="right")

    rp.column_dimensions["A"].width = 36
    for c in range(2, last_col + 1):
        rp.column_dimensions[L(c)].width = 11
    rp.print_area = f"A1:{L(last_col)}{sign}"
    rp.page_setup.paperSize = rp.PAPERSIZE_A4
    rp.page_setup.orientation = "portrait"
    rp.page_setup.fitToWidth = 1
    rp.page_setup.fitToHeight = 1
    rp.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    rp.print_options.horizontalCentered = True
    rp.sheet_view.showGridLines = False

    for sheet in wb.worksheets:  # avoid opening with several tabs grouped
        sheet.sheet_view.tabSelected = False
    wb.active = wb.sheetnames.index(rp.title)
    rp.sheet_view.tabSelected = True
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
