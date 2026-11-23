export type Issue = { level: "error" | "warning" | "info"; message: string; cell: string | null };

export type Question = { letter: string; component: string; co: number | null; max: number | null };

export type Analysis = {
  sheet: string;
  sheet_names: string[];
  header_rows: { component: number | null; co: number; max: number };
  questions: Question[];
  student_count: number;
  detected_cos: number[];
  issues: Issue[];
  ignored: { from: string; label: string; reason: string }[];
  terminal: Question[];
  sheet_ep: Record<string, number>;
  sheet_ela: Record<string, number>;
};

export type Settings = {
  subject_code: string;
  subject_name: string;
  academic_year: string;
  semester: string;
  faculty: string;
  num_cos: number;
  ep_by_co: (number | null)[]; // null = staff have not entered it yet
  ela: (number | null)[];
  internal_weight: number;
  operator: ">=" | ">";
  terminal_operator: ">=" | ">";
  decimals: number;
  absent_policy: "zero" | "exclude";
  terminal_absent_policy: "zero" | "exclude";
  ela_compare: "exact" | "rounded";
  action_plans: Record<number, string>;
  untagged_mapping: Record<string, number[]>;
  excluded_columns: string[];
};

export type CoSummary = {
  co: number;
  max: number;
  questions: string[];
  ep: number;
  ela: number | null;
  count: number;
  ca_pct: number | null;
  weighted: number | null;
  te_count: number;
  te_pct: number | null;
  te_weighted: number | null;
  total: number | null;
  total_rounded: number | null;
  outcome: "Attained" | "Not Attained" | null;
  action_plan: string;
};

export type StudentRow = {
  reg: string;
  name: string;
  included: boolean;
  pct: (number | null)[];
  meets: boolean[];
  te_pct: (number | null)[];
  te_meets: boolean[];
};

export type ComputeResult = {
  n: number;
  total_students: number;
  has_terminal: boolean;
  terminal_mode: "none" | "total" | "split";
  summary: CoSummary[];
  students: StudentRow[];
  warnings: string[];
};

const MAX_UPLOAD = 15 * 1024 * 1024;
const worker = new Worker(new URL("./py.worker.ts", import.meta.url), { type: "module" });
const pending = new Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>();
let nextId = 1;

worker.onmessage = ({ data }) => {
  const job = pending.get(data.id);
  if (!job) return;
  pending.delete(data.id);
  if (data.error) job.reject(new Error(data.error));
  else job.resolve(data.value);
};

function send<T>(message: object, transfer: Transferable[] = []): Promise<T> {
  const id = nextId++;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (v: unknown) => void, reject });
    worker.postMessage({ id, ...message }, transfer);
  });
}

// Start loading now so the first upload is quicker. A failure is reported on that upload.
send({ kind: "boot" }).catch(() => {});

async function run<T>(kind: string, file: File, sheet: string, settings?: Settings): Promise<T> {
  if (!/\.(xlsx|xlsm)$/i.test(file.name)) throw new Error("Please upload an Excel .xlsx file.");
  if (file.size === 0) throw new Error("The file is empty.");
  if (file.size > MAX_UPLOAD) throw new Error("File is larger than 15 MB.");
  const buffer = await file.arrayBuffer();
  return send<T>({ kind, buffer, sheet, settings: settings ? JSON.stringify(settings) : "{}" }, [buffer]);
}

export const analyze = (file: File, sheet = "") => run<Analysis>("analyze", file, sheet);

export const compute = (file: File, sheet: string, s: Settings) => run<ComputeResult>("compute", file, sheet, s);

export async function exportXlsx(file: File, sheet: string, s: Settings) {
  const bytes = await run<Uint8Array>("export", file, sheet, s);
  const blob = new Blob([bytes], {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
  const stem = file.name.replace(/\.[^.]+$/, "").replace(/[^\w\-. ]/g, "_");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${stem}_CO_attainment.xlsx`;
  a.click();
  URL.revokeObjectURL(url);
}
