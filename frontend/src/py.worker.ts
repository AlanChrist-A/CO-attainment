// Runs the Python calculation in the browser, so the uploaded file never leaves this computer.
import browserPy from "../../backend/app/browser.py?raw";
import enginePy from "../../backend/app/engine.py?raw";
import parserPy from "../../backend/app/parser.py?raw";
import serializePy from "../../backend/app/serialize.py?raw";
import writerPy from "../../backend/app/writer.py?raw";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.7/full/";
const WHEELS = ["et_xmlfile-2.0.0-py3-none-any.whl", "openpyxl-3.1.5-py2.py3-none-any.whl"];

type PyCall = (kind: string, buffer: unknown, sheet: string, settings: string) => unknown;
type Job = { id: number; kind: "boot" | "analyze" | "compute" | "export"; buffer?: ArrayBuffer; sheet?: string; settings?: string };

let ready: Promise<PyCall> | null = null;

async function boot() {
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE}pyodide.mjs`);
  const py = await loadPyodide({ indexURL: PYODIDE });
  const base = new URL(import.meta.env.BASE_URL, self.location.origin);
  await py.loadPackage(["numpy", "pydantic", ...WHEELS.map((w) => new URL(`py/${w}`, base).href)], {
    messageCallback: () => {},
  });
  py.FS.mkdirTree("/co/app");
  const files = { "__init__": "", browser: browserPy, engine: enginePy, parser: parserPy, serialize: serializePy, writer: writerPy };
  for (const [name, source] of Object.entries(files)) py.FS.writeFile(`/co/app/${name}.py`, source);
  py.runPython("import sys; sys.path.insert(0, '/co')");
  return py.pyimport("app.browser").call as PyCall;
}

self.onmessage = async ({ data: job }: MessageEvent<Job>) => {
  try {
    ready ??= boot();
    const call = await ready;
    if (job.kind === "boot") {
      self.postMessage({ id: job.id, value: true });
      return;
    }
    const out = call(job.kind, new Uint8Array(job.buffer!), job.sheet ?? "", job.settings ?? "{}");
    if (typeof out === "string") {
      const parsed = JSON.parse(out);
      if (parsed.error) self.postMessage({ id: job.id, error: parsed.error });
      else self.postMessage({ id: job.id, value: parsed });
    } else {
      self.postMessage({ id: job.id, value: out });
    }
  } catch (e) {
    if (!job.buffer) ready = null; // allow a retry if loading failed
    console.error(e);
    self.postMessage({ id: job.id, error: "Could not process this file. Check your internet connection and try again." });
  }
};
