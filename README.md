# CO Attainment

Upload the department marks sheet, check what was read, set subject details, see CA + TE attainment per CO, and download the workbook with three added sheets (`CO Calculation`, `CO Attainment`, `CO Report`) built from live Excel formulas. The website can also print the signed CO report.

## Hosting (Netlify)

Netlify serves the static site from `netlify.toml`. Netlify cannot run Python, so the calculation code in `backend/app` runs in the browser through Pyodide in a Web Worker. Uploaded files stay on the user's computer.

## Run locally

```bash
cd frontend
npm ci
npm run build
npm run preview        # http://localhost:4173
```

For hot reload, use `npm run dev` (http://localhost:5173).

## Test the Python code

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows (use .venv/bin on Linux/macOS)
.venv/Scripts/python -m pytest -q
```

Tests and sample workbooks are kept out of git because they contain student data.

## Layout

- `backend/app/parser.py` – finds the component / CO / max-marks header rows and student rows; validation report
- `backend/app/engine.py` – vectorised calculation (NumPy), Excel-style rounding
- `backend/app/writer.py` – adds result sheets with formulas to the uploaded workbook
- `backend/app/browser.py` – entry point used by the Netlify build
- `backend/app/main.py` – optional FastAPI server for a later hosted backend
- `frontend/src/py.worker.ts` – loads and runs the Python code in the browser
- `frontend/src/App.tsx` – single-page UI
