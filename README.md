# CO Attainment

Upload the department marks sheet, check what was read, set subject details, see CA + TE attainment per CO, and download the workbook with three added sheets (`CO Calculation`, `CO Attainment`, `CO Report`) built from live Excel formulas. The website can also print the signed CO report.

## Run

```bash
# backend (Python 3.12)
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows (use .venv/bin on Linux/macOS)

# frontend
cd ../frontend
npm install
npm run build          # FastAPI serves frontend/dist

# start (from repo root)
backend/.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --port 8000
# open http://localhost:8000
```

For frontend development with hot reload, run the backend as above plus `npm run dev` in `frontend` (http://localhost:5173, proxies `/api`).

## Test

```bash
cd backend && .venv/Scripts/python -m pytest -q
```

Tests include an exact match against the department workbook in `Pre-Context` (skipped when it is absent), the earlier Sheet4 values, and a 1,000-student speed check.

## Sample input

`samples/sample_internal_marks.xlsx` – 14 students transcribed from the department screenshots (22IT260). Rebuild with `python backend/scripts/make_sample.py`.

## Layout

- `backend/app/parser.py` – finds the component / CO / max-marks header rows and student rows; validation report
- `backend/app/engine.py` – vectorised calculation (NumPy), Excel-style rounding
- `backend/app/writer.py` – adds result sheets with formulas to the uploaded workbook
- `backend/app/main.py` – FastAPI: `/api/analyze`, `/api/compute`, `/api/export` (stateless)
- `frontend/src/App.tsx` – single-page UI
