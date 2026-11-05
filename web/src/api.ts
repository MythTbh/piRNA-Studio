export type Severity = "pass" | "warning" | "error";
export interface Sample {
  sample_id: string;
  condition: string;
  replicate: number | string;
  library_kit: string;
}
export interface SampleQC {
  sample_id: string;
  total_reads: number;
  piRNA_range_pct: number;
  unique_pct: number;
  u1_pct: number;
  a10_pct: number;
  pingpong_z: number | null;
  status: string;
  length_histogram: Record<string, number>;
}
export interface AccountingRow {
  sample_id: string;
  stage: string;
  reads: number;
}
export interface Cluster {
  cluster_id: string;
  chr: string;
  start: number;
  end: number;
  length: number;
  strand_mode: string;
  total_reads: number;
  support_n: number;
  u1_pct: number | null;
  a10_pct: number | null;
  repeat_pct: number | null;
  counts: Record<string, number>;
}
export interface DERow {
  cluster_id: string;
  contrast: string;
  base_mean: number | null;
  log2fc: number | null;
  pvalue: number | null;
  padj: number | null;
  flag: string;
}
export interface RunResults {
  samples: Sample[];
  qc: SampleQC[];
  accounting: AccountingRow[];
  clusters: Cluster[];
  tracks: {
    chr: string;
    start: number;
    end: number;
    strand: string;
    count: number;
  }[];
  de: DERow[];
  validation: {
    precision: number | null;
    recall: number | null;
    jaccard: number | null;
    matched: { cluster_id: string; ref_id: string }[];
    missed: string[];
    extra: string[];
  };
  provenance: {
    run_id: string;
    tools: Record<string, string>;
    methods: string;
    parameters: Record<string, unknown>;
  };
}
interface Check {
  name: string;
  severity: Severity;
  message: string;
  fix?: string;
  histogram?: Record<string, number>;
}
interface Preflight {
  checks: Check[];
  blocking: boolean;
}
interface RunSummary {
  run_id: string;
  created_at: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
}
interface RunStatus extends RunSummary {
  stage: string;
  progress: number;
  logs: string[];
  accounting?: AccountingRow[];
  error?: string;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch("/api/" + path, options);
  if (!response.ok) {
    let message = "Request failed (" + response.status + ")";
    try {
      const body: { detail?: unknown; error?: unknown } = await response.json();
      const reason = body.detail ?? body.error;
      if (typeof reason === "string") message = reason;
    } catch {
      /* The web server may return a plain-text error. */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
const resource = (id: string, end: string) =>
  "runs/" + encodeURIComponent(id) + "/" + end;
export const api = {
  prepareReference: (id: string) => request<any>("references/" + encodeURIComponent(id), {method:"POST"}),
  referenceStatus: (id: string) => request<any>("references/" + encodeURIComponent(id)),
  health: () => request<{ status: string; service: string; max_upload_bytes?: number }>("health"),
  list: () => request<{ runs: RunSummary[] }>("runs"),
  preflight: (body: FormData) =>
    request<Preflight>("preflight", { method: "POST", body }),
  start: (body: FormData) =>
    request<{ run_id: string }>("runs", { method: "POST", body }),
  results: (id: string) => request<RunResults>(resource(id, "results")),
  status: (id: string) => request<RunStatus>(resource(id, "status")),
  cancel: (id: string) =>
    request<RunStatus>(resource(id, "cancel"), { method: "POST" }),
  exportUrl: (id: string, format: "html" | "zip" | "reproduce") =>
    "/api/" + resource(id, "export") + "?format=" + format,
};
