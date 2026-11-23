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

async function post(path: string, file: File, sheet: string, settings?: Settings): Promise<Response> {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("sheet", sheet);
  if (settings) fd.append("settings", JSON.stringify(settings));
  const res = await fetch(path, { method: "POST", body: fd });
  if (!res.ok) {
    let msg = res.status === 413 ? "This file is too large to upload." : `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res;
}

export const analyze = async (file: File, sheet = "") =>
  (await (await post("/api/analyze", file, sheet)).json()) as Analysis;

export const compute = async (file: File, sheet: string, s: Settings) =>
  (await (await post("/api/compute", file, sheet, s)).json()) as ComputeResult;

export async function exportXlsx(file: File, sheet: string, s: Settings) {
  const res = await post("/api/export", file, sheet, s);
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? "CO_attainment.xlsx";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
