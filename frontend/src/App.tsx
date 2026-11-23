import { useMemo, useState, type KeyboardEvent } from "react";
import {
  analyze,
  compute,
  exportXlsx,
  type Analysis,
  type ComputeResult,
  type Settings,
} from "./api";

const fmt = (v: number | null | undefined, dp: number) =>
  v === null || v === undefined ? "–" : v.toFixed(dp);

function defaultSettings(a: Analysis, prev?: Settings): Settings {
  const num = Math.max(6, ...a.detected_cos);
  const untagged: Record<string, number[]> = {};
  // Assignments default to every CO. Any other untagged column waits for a staff choice.
  for (const q of a.questions)
    if (q.co === null)
      untagged[q.letter] = /^(A\d|ASSIGN|SL)/i.test(q.component)
        ? Array.from({ length: num }, (_, i) => i + 1)
        : [];
  return {
    subject_code: prev?.subject_code ?? "",
    subject_name: prev?.subject_name ?? "",
    academic_year: prev?.academic_year ?? "",
    semester: prev?.semester ?? "",
    faculty: prev?.faculty ?? "",
    num_cos: num,
    // Staff inputs: prefilled from the sheet's yellow table, otherwise left blank to be typed.
    ep_by_co: Array.from({ length: num }, (_, i) => a.sheet_ep[String(i + 1)] ?? null),
    ela: Array.from({ length: num }, (_, i) => a.sheet_ela[String(i + 1)] ?? null),
    internal_weight: prev?.internal_weight ?? 40,
    operator: prev?.operator ?? ">=",
    terminal_operator: prev?.terminal_operator ?? ">",
    decimals: prev?.decimals ?? 1,
    absent_policy: prev?.absent_policy ?? "zero",
    terminal_absent_policy: prev?.terminal_absent_policy ?? "exclude",
    ela_compare: prev?.ela_compare ?? "rounded",
    action_plans: {},
    untagged_mapping: untagged,
    excluded_columns: [],
  };
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [result, setResult] = useState<ComputeResult | null>(null);
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState<"" | "analyze" | "compute" | "export">("");
  const [error, setError] = useState("");

  async function run<T>(kind: typeof busy, fn: () => Promise<T>): Promise<T | undefined> {
    setBusy(kind);
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  async function onFile(f: File | null, sheet = "") {
    if (!f) return;
    setFile(f);
    setResult(null);
    const a = await run("analyze", () => analyze(f, sheet));
    if (a) {
      setAnalysis(a);
      setSettings((prev) => defaultSettings(a, prev ?? undefined));
    } else {
      setAnalysis(null);
    }
  }

  function update(patch: Partial<Settings>) {
    if (!settings) return;
    const next = { ...settings, ...patch };
    if (patch.num_cos !== undefined) {
      const n = patch.num_cos;
      next.ela = Array.from({ length: n }, (_, i) => settings.ela[i] ?? null);
      next.ep_by_co = Array.from({ length: n }, (_, i) => settings.ep_by_co[i] ?? null);
      next.untagged_mapping = Object.fromEntries(
        Object.entries(settings.untagged_mapping).map(([k, v]) => [k, v.filter((c) => c <= n)]),
      );
    }
    setSettings(next);
    if (result) setStale(true);
  }

  // Action plans only change the report text, so results stay valid.
  function setPlan(co: number, text: string) {
    setSettings((s) => (s ? { ...s, action_plans: { ...s.action_plans, [co]: text } } : s));
  }

  async function onCompute() {
    if (!file || !analysis || !settings) return;
    const r = await run("compute", () => compute(file, analysis.sheet, settings));
    if (r) {
      setResult(r);
      setStale(false);
    }
  }

  async function onExport() {
    if (!file || !analysis || !settings) return;
    await run("export", () => exportXlsx(file, analysis.sheet, settings));
  }

  const errors = analysis?.issues.filter((i) => i.level === "error").length ?? 0;
  const validTarget = (v: number | null) => v !== null && v >= 0 && v <= 100;
  const targetsReady = !!settings && settings.ep_by_co.every(validTarget) && settings.ela.every(validTarget);

  return (
    <div className="page">
      <header className="top">
        <div>
          <h1>CO Attainment</h1>
          <p className="muted">Internal + terminal attainment and the staff CO report</p>
        </div>
      </header>

      <section className="card">
        <h2>
          <span className="step">1</span> Upload marks sheet
        </h2>
        <label className={`drop ${busy === "analyze" ? "is-busy" : ""}`}>
          <input
            type="file"
            accept=".xlsx,.xlsm"
            onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          />
          <span>
            {file ? <strong>{file.name}</strong> : "Choose the department marks sheet (.xlsx)"}
          </span>
          <span className="muted small">
            Needs a row of CO tags (CO1, CO2 …) with the max-marks row right below it.
          </span>
        </label>
        {analysis && analysis.sheet_names.length > 1 && (
          <div className="row">
            <label className="field inline">
              <span>Sheet</span>
              <select value={analysis.sheet} onChange={(e) => onFile(file, e.target.value)}>
                {analysis.sheet_names.map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
          </div>
        )}
      </section>

      {error && <div className="alert error">{error}</div>}

      {analysis && settings && (
        <>
          <SheetCheck analysis={analysis} settings={settings} update={update} />
          <SettingsCard settings={settings} update={update} />

          <div className="actions">
            <button
              className="primary"
              onClick={onCompute}
              disabled={busy !== "" || errors > 0 || !targetsReady}
              title={errors ? "Fix the errors in the sheet first" : ""}
            >
              {busy === "compute" ? "Calculating…" : "Calculate"}
            </button>
            {errors > 0 && (
              <span className="muted small">Fix the {errors} error(s) in the sheet and upload again.</span>
            )}
            {errors === 0 && !targetsReady && (
              <span className="muted small">Enter EP and ELA (0 to 100) for every CO.</span>
            )}
          </div>
        </>
      )}

      {result && settings && (
        <Results
          result={result}
          settings={settings}
          stale={stale}
          busy={busy}
          onExport={onExport}
        />
      )}

      {result?.has_terminal && settings && (
        <Report result={result} settings={settings} stale={stale} setPlan={setPlan} />
      )}
    </div>
  );
}

function SheetCheck({
  analysis,
  settings,
  update,
}: {
  analysis: Analysis;
  settings: Settings;
  update: (p: Partial<Settings>) => void;
}) {
  const a = analysis;
  const excluded = new Set(settings.excluded_columns);
  const coList = Array.from({ length: settings.num_cos }, (_, i) => i + 1);

  function toggleColumn(letter: string) {
    const next = new Set(excluded);
    if (next.has(letter)) next.delete(letter);
    else next.add(letter);
    update({ excluded_columns: [...next] });
  }

  function toggleMap(letter: string, co: number) {
    const cur = settings.untagged_mapping[letter] ?? [];
    const next = cur.includes(co) ? cur.filter((c) => c !== co) : [...cur, co].sort((x, y) => x - y);
    update({ untagged_mapping: { ...settings.untagged_mapping, [letter]: next } });
  }

  function setAll(letter: string, on: boolean) {
    update({ untagged_mapping: { ...settings.untagged_mapping, [letter]: on ? coList : [] } });
  }

  const comps = useMemo(() => {
    const m = new Map<string, number>();
    for (const q of a.questions) m.set(q.component, (m.get(q.component) ?? 0) + 1);
    return [...m.entries()];
  }, [a.questions]);

  return (
    <section className="card">
      <h2>
        <span className="step">2</span> Check what was read
      </h2>
      <p className="facts">
        Sheet <strong>{a.sheet}</strong> · <strong>{a.student_count}</strong> students ·{" "}
        <strong>{a.questions.length}</strong> question columns (
        {comps.map(([c, n]) => `${c}: ${n}`).join(", ")}) · header rows{" "}
        {a.header_rows.component ?? "–"} / {a.header_rows.co} / {a.header_rows.max} · terminal:{" "}
        <strong>
          {a.terminal.length === 0
            ? "not found"
            : a.terminal.some((q) => q.co !== null)
              ? `split by CO (${a.terminal.length} columns)`
              : `one total in column ${a.terminal[0].letter} (out of ${a.terminal[0].max})`}
        </strong>
      </p>

      {a.issues.length > 0 && (
        <ul className="issues">
          {a.issues.map((i, k) => (
            <li key={k} className={i.level}>
              <span className="tag">{i.level}</span>
              {i.cell && <code>{i.cell}</code>} {i.message}
            </li>
          ))}
        </ul>
      )}
      {a.ignored.length > 0 && (
        <p className="muted small">
          Not read as marks:{" "}
          {a.ignored.map((g) => `${g.label} (from column ${g.from}) – ${g.reason}`).join("; ")}
        </p>
      )}

      <div className="table-wrap">
        <table className="grid compact">
          <thead>
            <tr>
              <th>Use</th>
              <th>Column</th>
              <th>Component</th>
              <th>CO</th>
              <th>Max</th>
            </tr>
          </thead>
          <tbody>
            {a.questions.map((q) => {
              const off = excluded.has(q.letter);
              const mapped = settings.untagged_mapping[q.letter] ?? [];
              return (
                <tr key={q.letter} className={off ? "off" : ""}>
                  <td>
                    <input
                      type="checkbox"
                      checked={!off}
                      onChange={() => toggleColumn(q.letter)}
                      aria-label={`Use column ${q.letter}`}
                    />
                  </td>
                  <td>
                    <code>{q.letter}</code>
                  </td>
                  <td>{q.component}</td>
                  <td>
                    {q.co !== null ? (
                      `CO${q.co}`
                    ) : (
                      <div className="chips">
                        <span className="muted small">Add to:</span>
                        {coList.map((c) => (
                          <button
                            key={c}
                            className={`chip ${mapped.includes(c) ? "on" : ""}`}
                            onClick={() => toggleMap(q.letter, c)}
                            disabled={off}
                          >
                            CO{c}
                          </button>
                        ))}
                        <button
                          className="link"
                          disabled={off}
                          onClick={() => setAll(q.letter, mapped.length !== coList.length)}
                        >
                          {mapped.length === coList.length ? "none" : "all"}
                        </button>
                      </div>
                    )}
                  </td>
                  <td>{q.max ?? <span className="bad">missing</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Columns without a CO tag (like an assignment) are added in full to each CO you pick.
      </p>
    </section>
  );
}

// Left / right arrows move between EP and ELA boxes, continuing onto the next row.
function moveBetweenTargets(e: KeyboardEvent<HTMLInputElement>) {
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  e.preventDefault();
  const inputs = [...(e.currentTarget.closest("table")?.querySelectorAll("input") ?? [])];
  const next = inputs[inputs.indexOf(e.currentTarget) + (e.key === "ArrowRight" ? 1 : -1)];
  next?.focus();
  next?.select();
}

function SettingsCard({
  settings: s,
  update,
}: {
  settings: Settings;
  update: (p: Partial<Settings>) => void;
}) {
  const presets = [40, 50];
  const custom = !presets.includes(s.internal_weight);
  return (
    <section className="card">
      <h2>
        <span className="step">3</span> Subject settings
      </h2>
      <div className="form">
        <label className="field">
          <span>Subject code</span>
          <input value={s.subject_code} onChange={(e) => update({ subject_code: e.target.value })} placeholder="22IT260" />
        </label>
        <label className="field wide">
          <span>Subject name</span>
          <input value={s.subject_name} onChange={(e) => update({ subject_name: e.target.value })} />
        </label>
        <label className="field">
          <span>Academic year</span>
          <input value={s.academic_year} onChange={(e) => update({ academic_year: e.target.value })} placeholder="2025-26" />
        </label>
        <label className="field">
          <span>Semester</span>
          <input value={s.semester} onChange={(e) => update({ semester: e.target.value })} />
        </label>
        <label className="field wide">
          <span>Course faculty</span>
          <input value={s.faculty} onChange={(e) => update({ faculty: e.target.value })} />
        </label>
        <label className="field">
          <span>Number of COs</span>
          <input
            type="number"
            min={1}
            max={12}
            value={s.num_cos}
            onChange={(e) => update({ num_cos: Math.min(12, Math.max(1, Number(e.target.value) || 1)) })}
          />
        </label>
        <label className="field">
          <span>Internal: meets EP when</span>
          <select value={s.operator} onChange={(e) => update({ operator: e.target.value as Settings["operator"] })}>
            <option value=">=">≥ EP</option>
            <option value=">">&gt; EP</option>
          </select>
        </label>
        <label className="field">
          <span>Terminal: meets EP when</span>
          <select
            value={s.terminal_operator}
            onChange={(e) => update({ terminal_operator: e.target.value as Settings["terminal_operator"] })}
          >
            <option value=">=">≥ EP</option>
            <option value=">">&gt; EP</option>
          </select>
        </label>
        <label className="field">
          <span>Compare total with ELA</span>
          <select
            value={s.ela_compare}
            onChange={(e) => update({ ela_compare: e.target.value as Settings["ela_compare"] })}
          >
            <option value="rounded">Rounded (81.91 → 82)</option>
            <option value="exact">Exact (81.91 &lt; 82)</option>
          </select>
        </label>
        <label className="field">
          <span>Decimal places</span>
          <select value={s.decimals} onChange={(e) => update({ decimals: Number(e.target.value) })}>
            <option value={0}>0</option>
            <option value={1}>1</option>
            <option value={2}>2</option>
          </select>
        </label>
        <div className="field">
          <span>Internal / terminal weight</span>
          <div className="seg">
            {presets.map((p) => (
              <button key={p} className={s.internal_weight === p ? "on" : ""} onClick={() => update({ internal_weight: p })}>
                {p} / {100 - p}
              </button>
            ))}
            <input
              type="number"
              min={1}
              max={100}
              className={custom ? "on" : ""}
              value={s.internal_weight}
              onChange={(e) => update({ internal_weight: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })}
              aria-label="Custom internal weight"
            />
          </div>
        </div>
        <label className="field">
          <span>Blank / AB internal marks</span>
          <select
            value={s.absent_policy}
            onChange={(e) => update({ absent_policy: e.target.value as Settings["absent_policy"] })}
          >
            <option value="zero">Count as 0</option>
            <option value="exclude">Leave student out</option>
          </select>
        </label>
        <label className="field">
          <span>Blank / AB terminal mark</span>
          <select
            value={s.terminal_absent_policy}
            onChange={(e) => update({ terminal_absent_policy: e.target.value as Settings["terminal_absent_policy"] })}
          >
            <option value="exclude">Leave student out</option>
            <option value="zero">Count as 0</option>
          </select>
        </label>
      </div>

      <div className="ela">
        <span className="label">EP and ELA for each CO (the yellow boxes in the staff sheet)</span>
        <div className="table-wrap targets">
          <table className="grid compact">
            <thead>
              <tr>
                <th />
                {s.ela.map((_, i) => (
                  <th key={i}>CO{i + 1}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(
                [
                  ["ep_by_co", "EP %"],
                  ["ela", "ELA %"],
                ] as const
              ).map(([key, label]) => (
                <tr key={key}>
                  <td className="strong">{label}</td>
                  {s[key].map((v, i) => (
                    <td key={i}>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        value={v ?? ""}
                        aria-label={`${label} for CO${i + 1}`}
                        className={v === null ? "empty" : ""}
                        onKeyDown={moveBetweenTargets}
                        onChange={(e) => {
                          const next = [...s[key]];
                          next[i] = e.target.value === "" ? null : Number(e.target.value);
                          update({ [key]: next });
                        }}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function Results({
  result: r,
  settings: s,
  stale,
  busy,
  onExport,
}: {
  result: ComputeResult;
  settings: Settings;
  stale: boolean;
  busy: string;
  onExport: () => void;
}) {
  const dp = s.decimals;
  const sign = (o: string) => (o === ">=" ? "≥" : ">");
  const wIn = s.internal_weight;
  const wTe = 100 - wIn;
  return (
    <section className="card">
      <div className="card-head">
        <h2>
          <span className="step">4</span> CO attainment
        </h2>
        <button className="primary" onClick={onExport} disabled={busy !== "" || stale}>
          {busy === "export" ? "Preparing…" : "Download Excel"}
        </button>
      </div>
      {stale && <div className="alert warn">Settings changed – press Calculate again.</div>}
      <p className="facts">
        {r.n} of {r.total_students} students counted · internal {sign(s.operator)} EP, terminal{" "}
        {sign(s.terminal_operator)} EP · weights {wIn} / {wTe}
      </p>
      {r.warnings.length > 0 && (
        <ul className="issues">
          {r.warnings.map((w, i) => (
            <li key={i} className="warning">
              <span className="tag">note</span>
              {w}
            </li>
          ))}
        </ul>
      )}

      <div className="table-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th>CO</th>
              <th>Max</th>
              <th>EP</th>
              <th>ELA</th>
              <th>CA students</th>
              <th>CA %</th>
              <th>CA × {wIn / 100}</th>
              <th>TE students</th>
              <th>TE %</th>
              <th>TE × {wTe / 100}</th>
              <th>CA + TE</th>
              {s.ela_compare === "rounded" && <th>Rounded</th>}
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {r.summary.map((c) => (
              <tr key={c.co}>
                <td>
                  <strong>CO{c.co}</strong>
                </td>
                <td className="num">{c.max}</td>
                <td className="num">{c.ep}</td>
                <td className="num">{c.ela ?? "–"}</td>
                <td className="num">{c.ca_pct === null ? "–" : `${c.count} / ${r.n}`}</td>
                <td className="num">{fmt(c.ca_pct, 2)}</td>
                <td className="num">{fmt(c.weighted, 2)}</td>
                <td className="num">{c.te_pct === null ? "–" : `${c.te_count} / ${r.n}`}</td>
                <td className="num">{fmt(c.te_pct, 2)}</td>
                <td className="num">{fmt(c.te_weighted, 2)}</td>
                <td className="num strong">{fmt(c.total, 2)}</td>
                {s.ela_compare === "rounded" && <td className="num strong">{fmt(c.total_rounded, 0)}</td>}
                <td className={c.outcome === "Attained" ? "ok" : c.outcome ? "low" : ""}>{c.outcome ?? "–"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3>Students · CO %</h3>
      <div className="table-wrap tall">
        <table className="grid">
          <thead>
            <tr>
              <th>#</th>
              <th>Reg. No</th>
              <th>Name</th>
              {r.summary.map((c) => (
                <th key={c.co}>CO{c.co}</th>
              ))}
              {r.terminal_mode === "total" && <th>Terminal</th>}
              {r.terminal_mode === "split" && r.summary.map((c) => <th key={c.co}>TE CO{c.co}</th>)}
            </tr>
          </thead>
          <tbody>
            {r.students.map((st, i) => (
              <tr key={i} className={st.included ? "" : "off"}>
                <td className="muted">{i + 1}</td>
                <td>
                  <code>{st.reg}</code>
                </td>
                <td>{st.name}</td>
                {st.pct.map((p, k) => (
                  <td key={k} className={`num ${p === null ? "" : st.meets[k] ? "ok" : "low"}`}>
                    {fmt(p, dp)}
                  </td>
                ))}
                {r.terminal_mode === "total" && (
                  <td className={`num ${st.te_pct[0] === null ? "" : st.te_meets[0] ? "ok" : "low"}`}>
                    {fmt(st.te_pct[0], dp)}
                  </td>
                )}
                {r.terminal_mode === "split" &&
                  st.te_pct.map((p, k) => (
                    <td key={k} className={`num ${p === null ? "" : st.te_meets[k] ? "ok" : "low"}`}>
                      {fmt(p, dp)}
                    </td>
                  ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small">
        Green = meets EP, red = below EP, grey = left out.
      </p>
    </section>
  );
}

function Report({
  result: r,
  settings: s,
  stale,
  setPlan,
}: {
  result: ComputeResult;
  settings: Settings;
  stale: boolean;
  setPlan: (co: number, text: string) => void;
}) {
  const total = (c: ComputeResult["summary"][number]) =>
    s.ela_compare === "rounded" ? fmt(c.total_rounded, 0) : fmt(c.total, 2);
  const plan = (c: ComputeResult["summary"][number]) => s.action_plans[c.co] ?? c.action_plan;
  const missing = r.summary.filter((c) => c.outcome === "Not Attained" && !plan(c).trim());
  const yearSem = [s.academic_year, s.semester].filter(Boolean).join(" / ");
  return (
    <section className="card report-card">
      <div className="card-head no-print">
        <h2>
          <span className="step">5</span> CO report
        </h2>
        <button className="primary" onClick={() => window.print()} disabled={stale || missing.length > 0}>
          Print report
        </button>
      </div>
      {missing.length > 0 && (
        <div className="alert warn no-print">
          Add an action plan for {missing.map((c) => `CO${c.co}`).join(", ")} (not attained) before printing.
        </div>
      )}
      <datalist id="plan-options">
        <option value="Existing system to be retained" />
        <option value="Solve more practice problems in class" />
        <option value="Add more practical demonstrations" />
        <option value="Increase laboratory sessions" />
        <option value="Review the syllabus coverage for this CO" />
      </datalist>

      <div className="form-sheet">
        <dl className="course">
          <dt>Course Code &amp; Name</dt>
          <dd>: {`${s.subject_code} ${s.subject_name}`.trim()}</dd>
          <dt>Academic Year / Semester</dt>
          <dd>: {yearSem}</dd>
          <dt>Course Faculty</dt>
          <dd>: {s.faculty}</dd>
        </dl>

        <h3>CO Attainment</h3>
        <table className="paper">
          <thead>
            <tr>
              <th />
              {r.summary.map((c) => (
                <th key={c.co}>CO{c.co}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="left">Expected Proficiency (EP)</td>
              {r.summary.map((c) => (
                <td key={c.co}>{c.ep}</td>
              ))}
            </tr>
            <tr>
              <td className="left">Expected level of attainment (ELA)</td>
              {r.summary.map((c) => (
                <td key={c.co}>{c.ela ?? "–"}</td>
              ))}
            </tr>
            <tr>
              <td className="left">Total CO Attainment (CA+TE)</td>
              {r.summary.map((c) => (
                <td key={c.co}>{total(c)}</td>
              ))}
            </tr>
          </tbody>
        </table>

        <table className="paper plans">
          <thead>
            <tr>
              <th>COs</th>
              <th>
                Outcome
                <br />
                Attained / Not-attained
              </th>
              <th>Action Plan for Improvement</th>
            </tr>
          </thead>
          <tbody>
            {r.summary.map((c) => (
              <tr key={c.co}>
                <td>CO{c.co}</td>
                <td>
                  <strong>{c.outcome ?? "–"}</strong>
                </td>
                <td className="left">
                  <input
                    className="no-print"
                    list="plan-options"
                    value={plan(c)}
                    onChange={(e) => setPlan(c.co, e.target.value)}
                    aria-label={`Action plan for CO${c.co}`}
                  />
                  <span className="print-only">{plan(c)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        <div className="signs">
          <strong>Faculty Signature</strong>
          <strong>HoD Signature</strong>
        </div>
      </div>
    </section>
  );
}
