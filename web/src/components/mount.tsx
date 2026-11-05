import { createRoot, type Root } from "react-dom/client";
import type { RunResults } from "../api";
import { RunOverview } from "./RunOverview";
import { StudioHeader } from "./StudioHeader";

let headerRoot: Root | null = null;
let overviewRoot: Root | null = null;
export function mountHeader(page: string, latestRun: string) {
  const host = document.getElementById("top");
  if (!host) return;
  headerRoot ??= createRoot(host);
  headerRoot.render(<StudioHeader page={page} latestRun={latestRun} />);
}
export function releaseOverview() {
  overviewRoot?.unmount();
  overviewRoot = null;
}
export function mountOverview(data: RunResults, run: string) {
  const host = document.getElementById("overview");
  if (!host) return;
  releaseOverview();
  overviewRoot = createRoot(host);
  overviewRoot.render(<RunOverview data={data} run={run} />);
}
