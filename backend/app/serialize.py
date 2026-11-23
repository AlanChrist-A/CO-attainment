"""JSON shapes shared by the FastAPI server and the in-browser runtime."""

from __future__ import annotations

import math

from .engine import Result, Settings, round_half_up
from .parser import ParsedSheet


def _num(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


def analysis_json(p: ParsedSheet) -> dict:
    return {
        "sheet": p.sheet,
        "sheet_names": p.sheet_names,
        "header_rows": {"component": None if p.component_row is None else p.component_row + 1,
                        "co": p.co_row + 1, "max": p.max_row + 1},
        "questions": [{"letter": q.letter, "component": q.component, "co": q.co, "max": q.max}
                      for q in p.questions],
        "student_count": len(p.regs),
        "detected_cos": p.detected_cos,
        "issues": [i.__dict__ for i in p.issues],
        "ignored": p.ignored,
        "terminal": [{"letter": q.letter, "component": q.component, "co": q.co, "max": q.max}
                     for q in p.terminal_questions],
        "sheet_ep": p.sheet_ep,
        "sheet_ela": p.sheet_ela,
    }


def result_json(p: ParsedSheet, s: Settings, r: Result) -> dict:
    return {
        "n": r.n,
        "total_students": len(p.regs),
        "has_terminal": r.has_terminal,
        "terminal_mode": r.terminal_mode,
        "summary": [{
            "co": k,
            "max": r.co_max[k - 1],
            "questions": r.co_questions[k - 1],
            "ep": s.ep_for(k),
            "ela": s.ela_for(k),
            "count": r.count[k - 1],
            "ca_pct": r.ca_pct[k - 1],
            "weighted": r.weighted[k - 1],
            "te_count": r.te_count[k - 1],
            "te_pct": r.te_ca_pct[k - 1],
            "te_weighted": r.te_weighted[k - 1],
            "total": r.total[k - 1],
            "total_rounded": None if r.total[k - 1] is None else round_half_up(r.total[k - 1], 0),
            "outcome": r.outcome[k - 1],
            "action_plan": r.action_plans[k - 1],
        } for k in r.cos],
        "students": [{
            "reg": p.regs[i],
            "name": p.names[i],
            "included": bool(r.included[i]),
            "pct": [_num(v) for v in r.pct[i]],
            "meets": [bool(v) for v in r.meets[i]],
            "te_pct": [_num(v) for v in r.te_pct[i]],
            "te_meets": [bool(v) for v in r.te_meets[i]],
        } for i in range(len(p.regs))],
        "warnings": r.warnings,
    }
