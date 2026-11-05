"""Integer, unique-only DESeq2 inference; transparent descriptive output otherwise."""

from itertools import combinations
from math import isfinite, log2
from statistics import mean
import warnings


def differential(counts, samples, params):
    groups = {}
    for s in samples:
        groups.setdefault(s["condition"], []).append(s["sample_id"])
    if len(groups) < 2 or not counts:
        return [], "No contrast with countable features."
    ids = [s["sample_id"] for s in samples]
    keep = [cid for cid, v in counts.items() if sum(v.values()) >= params["min_total_count"]]
    dds = None
    reason = (
        "Descriptive CPM fold change, with a 0.5 CPM pseudocount; inferential statistics unavailable."
    )
    enough = all(len(g) >= 2 for g in groups.values())
    retained_totals = {sid: sum(counts[cid][sid] for cid in keep) for sid in ids}
    empty_libraries = [sid for sid, total in retained_totals.items() if not total]
    if empty_libraries:
        reason += " At least one sample has zero retained unique reads."
    if keep and enough and not empty_libraries and params["de_method"] != "descriptive":
        try:
            import pandas as pd
            from pydeseq2.dds import DeseqDataSet
            from pydeseq2.ds import DeseqStats
        except ImportError:
            if params["de_method"] == "pydeseq2":
                raise
        else:
            raw = pd.DataFrame({cid: counts[cid] for cid in keep}).loc[ids]
            metadata = pd.DataFrame({"condition": [s["condition"] for s in samples]}, index=ids)
            dds = DeseqDataSet(
                counts=raw,
                metadata=metadata,
                design="~condition",
                size_factors_fit_type="poscounts",
                n_cpus=1,
                quiet=True,
            )
            with warnings.catch_warnings(record=True) as observations:
                warnings.simplefilter("always")
                dds.deseq2()
            reason = "PyDESeq2 Wald test on integer unique-read counts."
            if any("did not converge" in str(w.message) for w in observations):
                reason += " The parametric dispersion trend did not converge; PyDESeq2 used its mean-trend fallback."
    if not enough:
        reason += " A condition has fewer than two biological replicates."
    totals = {s: sum(row[s] for row in counts.values()) for s in ids}
    rows = []
    for a, b in combinations(groups, 2):
        fitted = None
        if dds is not None:
            stats = DeseqStats(dds, contrast=["condition", b, a], n_cpus=1, quiet=True)
            stats.summary()
            fitted = stats.results_df
        for cid, values in counts.items():

            def norm(group):
                return mean((1e6 * values[s] / totals[s] if totals[s] else 0) for s in groups[group])

            flags = []
            if cid not in keep:
                flags.append("low counts")
            if min(len(groups[a]), len(groups[b])) < 3:
                flags.append("few replicates")
            row = dict(
                cluster_id=cid,
                contrast=f"{b} vs {a}",
                base_mean=mean(values.values()),
                log2fc=log2((norm(b) + 0.5) / (norm(a) + 0.5)),
                pvalue=None,
                padj=None,
            )
            if fitted is not None and cid in keep:
                for key, col in [
                    ("base_mean", "baseMean"),
                    ("log2fc", "log2FoldChange"),
                    ("pvalue", "pvalue"),
                    ("padj", "padj"),
                ]:
                    val = float(fitted.loc[cid, col])
                    row[key] = val if isfinite(val) else None
                if row["padj"] is None:
                    flags.append("adjusted p-value unavailable")
            else:
                flags.append("descriptive")
            row["flag"] = ", ".join(flags)
            rows.append(row)
    return rows, reason
