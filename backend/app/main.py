"""FastAPI app: CO attainment (internal + terminal).

Stateless: the browser sends the Excel file with each request, so any number
of server copies can run behind a load balancer. Files are small (<1 MB).
The Netlify build does not use this server; see browser.py.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .engine import Settings, compute
from .parser import ParsedSheet, SheetFormatError, parse_workbook
from .serialize import analysis_json, result_json
from .writer import build_output

MAX_UPLOAD = 15 * 1024 * 1024
ALLOWED = (".xlsx", ".xlsm")

app = FastAPI(title="CO Attainment", version="0.1.0")
app.add_middleware(GZipMiddleware, minimum_size=1000)


async def _read(file: UploadFile) -> bytes:
    name = (file.filename or "").lower()
    if not name.endswith(ALLOWED):
        raise HTTPException(400, "Please upload an Excel .xlsx file.")
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File is larger than 15 MB.")
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


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...), sheet: str = Form("")):
    data = await _read(file)
    p = await asyncio.to_thread(_parse, data, sheet)
    return analysis_json(p)


@app.post("/api/compute")
async def compute_endpoint(file: UploadFile = File(...), sheet: str = Form(""),
                           settings: str = Form("{}")):
    data = await _read(file)
    s = _settings(settings)
    p = await asyncio.to_thread(_parse, data, sheet)
    r = await asyncio.to_thread(compute, p, s)
    return result_json(p, s, r)


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
