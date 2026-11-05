"""Portable HTML report shared by the command-line engine and the web API."""

import html
import json


def e(value):
    return html.escape(str(value), quote=True)


def table(records, fields):
    if not records:
        return "<p>No records available.</p>"
    headers = "".join(f"<th scope='col'>{e(f)}</th>" for f in fields)
    rows = []
    for row in records:
        cells = "".join(f"<td>{e(row.get(f, ''))}</td>" for f in fields)
        rows.append(f"<tr>{cells}</tr>")
    return f"<div><table><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def report(result, rid):
    samples = table(result["samples"], ["sample_id", "condition", "replicate", "library_kit"])
    qc = table(
        result["qc"],
        [
            "sample_id",
            "total_reads",
            "piRNA_range_pct",
            "unique_pct",
            "u1_pct",
            "a10_pct",
            "pingpong_z",
            "status",
        ],
    )
    accounting = table(result["accounting"], ["sample_id", "stage", "reads"])
    clusters = table(
        result["clusters"],
        ["cluster_id", "chr", "start", "end", "strand_mode", "support_n", "total_reads"],
    )
    de = table(result["de"], ["cluster_id", "contrast", "base_mean", "log2fc", "padj", "flag"])
    val = e(json.dumps(result["validation"], indent=2))
    manifest = e(json.dumps(result["provenance"], indent=2))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>piRNA Studio analysis report</title><style>
body{{max-width:1100px;margin:40px auto;padding:0 20px;color:#0e1a2b;font:16px/1.5 system-ui,sans-serif}}
h1,h2{{color:#34308a}}div{{overflow:auto}}table{{border-collapse:collapse;font-size:14px}}
th,td{{padding:7px 11px;border-bottom:1px solid #d9e0ec;text-align:left}}th{{background:#eef2f8}}
pre,code{{white-space:pre-wrap;overflow-wrap:anywhere}}@media print{{div{{overflow:visible}}}}
</style><main><h1>piRNA Studio analysis report</h1><p>Run <code>{e(rid)}</code></p>
<h2>Samples</h2>{samples}<h2>Sample quality</h2>{qc}<h2>Read accounting</h2>{accounting}
<h2>Discovered clusters</h2>{clusters}<h2>Differential expression</h2>{de}
<h2>Reference validation</h2><pre>{val}</pre><h2>Methods and provenance</h2><pre>{manifest}</pre>
</main></html>""".encode()
