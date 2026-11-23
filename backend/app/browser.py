"""Entry point when the calculation runs in the browser (Pyodide on Netlify)."""

from __future__ import annotations

import json

from pydantic import ValidationError
from pyodide.ffi import to_js

from .engine import Settings, compute
from .parser import SheetFormatError, parse_workbook
from .serialize import analysis_json, result_json
from .writer import build_output


def call(kind: str, buffer, sheet: str, settings_json: str = "{}"):
    """Returns a JSON string, or a Uint8Array for an Excel export."""
    data = bytes(buffer.to_py())
    try:
        parsed = parse_workbook(data, sheet or None)
        if kind == "analyze":
            return json.dumps(analysis_json(parsed))
        settings = Settings(**json.loads(settings_json or "{}"))
        result = compute(parsed, settings)
        if kind == "compute":
            return json.dumps(result_json(parsed, settings, result))
        return to_js(build_output(data, parsed, settings, result))
    except ValidationError as exc:
        return json.dumps({"error": f"Invalid settings: {exc.errors()[0]['msg']}"})
    except (SheetFormatError, ValueError) as exc:
        return json.dumps({"error": str(exc)})
