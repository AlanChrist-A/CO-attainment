"""FastAPI app: CO attainment (internal + terminal).

Stateless: the browser sends the Excel file with each request, so any number
of server copies can run behind a load balancer. Files are small (<1 MB).
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .engine import Result, Settings, compute, round_half_up
from .parser import ParsedSheet, SheetFormatError, parse_workbook
from .writer import build_output

# Vercel rejects request bodies above 4.5 MB.
MAX_UPLOAD_MB = 4 if os.environ.get("VERCEL") else 15
MAX_UPLOAD = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED = (".xlsx", ".xlsm")

app = FastAPI(title="CO Attainment", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)


async def _read(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith(ALLOWED):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, f"File is larger than {MAX_UPLOAD_MB} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    return data


def _parse(data: bytes, sheet: str | None) -> ParsedSheet:
    try:
        return parse_workbook(data, sheet or None)
    except SheetFormatError as exc:
        raise HTTPException(422, str(exc)) from exc


def _settings(raw: str) -> Settings:
    try:
        return Settings(**json.loads(raw or "{}"))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        raise HTTPException(422, f"Invalid settings: {exc}") from exc


def _num(x):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) else x


def _analysis_json(p: ParsedSheet) -> dict:
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


def _result_json(p: ParsedSheet, s: Settings, r: Result) -> dict:
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


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), sheet: str = Form("")):
    data = await _read(file)
    p = await asyncio.to_thread(_parse, data, sheet)
    return _analysis_json(p)


@app.post("/api/compute")
async def compute_endpoint(file: UploadFile = File(...), sheet: str = Form(""),
                           settings: str = Form("{}")):
    data = await _read(file)
    s = _settings(settings)
    p = await asyncio.to_thread(_parse, data, sheet)
    r = await asyncio.to_thread(compute, p, s)
    return _result_json(p, s, r)


@app.post("/api/export")
async def export(file: UploadFile = File(...), sheet: str = Form(""),
                 settings: str = Form("{}")):
    data = await _read(file)
    s = _settings(settings)
    p = await asyncio.to_thread(_parse, data, sheet)
    r = await asyncio.to_thread(compute, p, s)
    try:
        out = await asyncio.to_thread(build_output, data, p, s, r)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    stem = re.sub(r"[^\w\-. ]", "_", Path(file.filename or "marks").stem)
    return Response(
        out,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{stem}_CO_attainment.xlsx"'},
    )


# Serve the built frontend (single-container deploy). Dev uses Vite's proxy instead.
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="web")
