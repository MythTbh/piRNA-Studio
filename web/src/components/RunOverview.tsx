import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { AccountingRow, RunResults } from "../api";
import { Button } from "./ui/Button";

const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const compact = new Intl.NumberFormat(undefined, {
  notation: "compact",
  maximumFractionDigits: 1,
});

function ReadAccounting({ accounting }: { accounting: AccountingRow[] }) {
  const stages = useMemo(() => {
    const totals = new Map<string, number>();
    accounting.forEach(({ stage, reads }) =>
      totals.set(stage, (totals.get(stage) ?? 0) + reads),
    );
    return [...totals].map(([stage, reads]) => ({ stage, reads }));
  }, [accounting]);
  if (!stages.length)
    return <p className="empty">No read accounting values are available.</p>;
  return (
    <>
      <div role="img" aria-label="Retained reads by processing stage">
        <ResponsiveContainer
          width="100%"
          height={Math.max(220, stages.length * 32 + 36)}
        >
          <BarChart
            data={stages}
            layout="vertical"
            margin={{ top: 12, right: 12, bottom: 16, left: 0 }}
            accessibilityLayer
          >
            <CartesianGrid
              horizontal={false}
              stroke="var(--line)"
              strokeDasharray="3 4"
            />
            <XAxis
              type="number"
              allowDecimals={false}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              tickFormatter={(v) => compact.format(v)}
              label={{
                value: "Reads retained",
                position: "insideBottom",
                offset: -10,
                fill: "var(--muted)",
                fontSize: 12,
              }}
            />
            <YAxis
              type="category"
              dataKey="stage"
              width={112}
              axisLine={false}
              tickLine={false}
              tick={{ fill: "var(--muted)", fontSize: 11 }}
              interval={0}
            />
            <Tooltip
              cursor={{ fill: "var(--soft)" }}
              contentStyle={{
                background: "var(--surface)",
                color: "var(--text)",
                border: "1px solid var(--line)",
                borderRadius: 6,
              }}
              formatter={(v) => [number.format(Number(v)), "Retained reads"]}
            />
            <Bar
              dataKey="reads"
              fill="#78917B"
              radius={[0, 4, 4, 0]}
              maxBarSize={14}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="caption">
        Each bar counts reads retained at that stage across all samples.
      </p>
      <details className="mt-2 text-sm">
        <summary>Read totals</summary>
        <dl>
          {stages.map(({ stage, reads }) => (
            <div className="between" key={stage}>
              <dt>{stage}</dt>
              <dd>{number.format(reads)}</dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
export function RunOverview({ data, run }: { data: RunResults; run: string }) {
  const n = data.qc.reduce((n, s) => n + s.total_reads, 0);
  const inRange = n
    ? data.qc.reduce((n, s) => n + s.piRNA_range_pct * s.total_reads, 0) / n
    : null;
  const tested = data.de.filter((r) => r.padj !== null && r.log2fc !== null);
  const significant = new Set(
    tested
      .filter((r) => r.padj! <= 0.05 && Math.abs(r.log2fc!) >= 1)
      .map((r) => r.cluster_id),
  );
  const kpis = [
    ["Samples", number.format(data.samples.length)],
    ["Input reads", number.format(n)],
    ["piRNA-sized", inRange === null ? "Not available" : number.format(inRange) + "%"],
    ["Clusters", number.format(data.clusters.length)],
    [
      "Significant clusters",
      tested.length ? number.format(significant.size) : "Not available",
    ],
  ];
  return (
    <>
      <div className="kpis">
        {kpis.map(([label, value]) => (
          <section className="kpi" key={label}>
            <small>{label}</small>
            <strong>{value}</strong>
          </section>
        ))}
      </div>
      <div className="grid">
        <section className="panel">
          <h2>Read accounting</h2>
          <ReadAccounting accounting={data.accounting} />
        </section>
        <section className="panel">
          <h2>Sample quality</h2>
          {data.qc.map((s) => (
            <div className="check between" key={s.sample_id}>
              <span className="mono">{s.sample_id}</span>
              <span className={"chip " + s.status}>

                {s.status}
              </span>
            </div>
          ))}
          <p className="caption">
            {data.qc.filter((s) => s.status === "pass").length} of{" "}
            {data.qc.length} samples passed all quality checks.
          </p>
          <Button asChild className="mt-3">
            <a href={"#results/" + encodeURIComponent(run) + "/qc"}>
              Inspect QC metrics
            </a>
          </Button>
        </section>
      </div>
    </>
  );
}
