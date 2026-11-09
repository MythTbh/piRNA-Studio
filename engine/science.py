"""Small-reference alignment, interval accounting, signatures and concordance."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log2
from statistics import mean, pstdev


def rc(seq):
    return seq.translate(str.maketrans("ACGTN", "TGCAN"))[::-1]


def loci(sequence, genome):
    for chrom, bases in genome.items():
        for strand, query in [("+", sequence), ("-", rc(sequence))]:
            start = bases.find(query)
            while start >= 0:
                yield chrom, start, start + len(query), strand
                start = bases.find(query, start + 1)


def complex_enough(sequence):
    # Shannon entropy filter for portable mode. The external workflow uses duster.
    return (
        -sum((n / len(sequence)) * log2(n / len(sequence)) for n in Counter(sequence).values()) >= 1.2
    )


@dataclass(frozen=True)
class Hit:
    chrom: str
    start: int
    end: int
    strand: str
    seq: str
    reads: int
    multiplicity: int

    @property
    def weight(self):
        return self.reads / self.multiplicity

    @property
    def five(self):
        return self.start if self.strand == "+" else self.end - 1


def portable_align(sequences, genome):
    hits = []
    for seq, n in sequences.items():
        places = list(loci(seq, genome)) if "N" not in seq else []
        hits.extend(Hit(*place, seq, n, len(places)) for place in places)
    return hits


def pingpong(hits, min_length):
    ends = defaultdict(Counter)
    at = defaultdict(set)
    for h in hits:
        ends[h.chrom, h.strand][h.five] += h.weight
        at[h.chrom, h.strand, h.five].add(h.seq)
    overlaps = [0.0] * min_length
    partners = set()
    for (chrom, strand), counts in ends.copy().items():
        if strand != "+":
            continue
        reverse = ends[chrom, "-"]
        for start, weight in counts.items():
            for k in range(min_length):
                overlaps[k] += weight * reverse[start + k]
            if reverse[start + 9]:
                partners.update(at[chrom, "+", start])
                partners.update(at[chrom, "-", start + 9])
    deviation = pstdev(overlaps)
    return (
        dict(enumerate(overlaps, 1)),
        (overlaps[9] - mean(overlaps)) / deviation if deviation else None,
        sorted(partners),
    )


def portable_calls(hits, params):
    """Group nearby distinct loci; a transparent exploratory caller for tiny genomes."""
    calls = []
    chrom = None
    start = end = n = 0
    for name, left, right in sorted({(h.chrom, h.start, h.end) for h in hits}):
        if name != chrom or left > end + params["max_gap"]:
            if chrom and end - start >= params["min_cluster_size"] and n >= params["min_loci"]:
                calls.append((chrom, start, end))
            chrom, start, end, n = name, left, right, 1
        else:
            end = max(end, right)
            n += 1
    if chrom and end - start >= params["min_cluster_size"] and n >= params["min_loci"]:
        calls.append((chrom, start, end))
    return calls


def merge(intervals):
    out = []
    for chrom, start, end in sorted(intervals):
        if out and out[-1][0] == chrom and start < out[-1][2]:
            out[-1] = (chrom, out[-1][1], max(end, out[-1][2]))
        else:
            out.append((chrom, start, end))
    return out


def consensus(calls, samples, threshold):
    """Require simultaneous overlap in N distinct samples of the same condition."""
    groups = defaultdict(list)
    for s in samples:
        groups[s["condition"]].append(s["sample_id"])
    accepted = []
    for ids in groups.values():
        events = defaultdict(Counter)
        for sid in ids:
            for chrom, start, end in merge(calls[sid]):
                events[chrom][start] += 1
                events[chrom][end] -= 1
        for chrom, changes in events.items():
            depth = 0
            for pos, delta in sorted(changes.items()):
                prior = depth
                depth += delta
                needed = min(len(ids), threshold)
                if prior < needed <= depth:
                    start = pos
                if prior >= needed > depth:
                    accepted.append((chrom, start, pos))
    return merge(accepted)


def counts_and_clusters(intervals, all_hits, calls, params, repeats):
    clusters, integer_counts = [], {}
    repeat_union = merge([r[:3] for r in repeats])
    for i, (chrom, start, end) in enumerate(intervals, 1):
        cid = f"C{i:06d}"
        counts, ints = {}, {}
        plus = u1 = a10 = 0.0
        support = 0
        for sid, hits in all_hits.items():
            support += any(c == chrom and a < end and b > start for c, a, b in calls[sid])
            total = unique = 0.0
            for h in hits:
                # Assignment uses the 5' end so a boundary-spanning read counts once.
                if h.chrom != chrom or not start <= h.five < end:
                    continue
                if h.multiplicity == 1:
                    unique += h.reads
                if params["count_mode"] == "unique" and h.multiplicity != 1:
                    continue
                total += h.weight
                plus += h.weight * (h.strand == "+")
                u1 += h.weight * (h.seq[0] == "T")
                a10 += h.weight * (len(h.seq) >= 10 and h.seq[9] == "A")
            counts[sid] = total
            ints[sid] = int(unique)
        total = sum(counts.values())
        frac = plus / total if total else 0
        repeat_bp = sum(max(0, min(end, b) - max(start, a)) for c, a, b in repeat_union if c == chrom)
        clusters.append(
            dict(
                cluster_id=cid,
                chr=chrom,
                start=start,
                end=end,
                length=end - start,
                strand_mode="dual" if 0.1 <= frac <= 0.9 else "unistrand",
                total_reads=total,
                u1_pct=100 * u1 / total if total else 0,
                a10_pct=100 * a10 / total if total else 0,
                repeat_pct=100 * repeat_bp / (end - start) if repeats else None,
                support_n=support,
                counts=counts,
            )
        )
        integer_counts[cid] = ints
    return clusters, integer_counts


def validate(clusters, reference):
    if reference is None:
        return dict(
            available=False, precision=None, recall=None, jaccard=None, matched=[], missed=[], extra=[]
        )
    pairs = []
    match_ref, match_calls = set(), set()
    for cl in clusters:
        for chrom, a, b, ref in reference:
            if cl["chr"] != chrom:
                continue
            ov = max(0, min(b, cl["end"]) - max(a, cl["start"]))
            if 2 * ov >= max(cl["length"], b - a):
                pairs.append(dict(cluster_id=cl["cluster_id"], ref_id=ref))
                match_ref.add(ref)
                match_calls.add(cl["cluster_id"])
    called = merge([(c["chr"], c["start"], c["end"]) for c in clusters])
    ref = merge([r[:3] for r in reference])
    union = sum(b - a for _, a, b in merge(called + ref))
    overlap = sum(b - a for _, a, b in called + ref) - union
    return dict(
        available=True,
        precision=len(match_calls) / len(clusters) if clusters else None,
        recall=len(match_ref) / len(reference) if reference else None,
        jaccard=overlap / union if union else None,
        matched=pairs,
        missed=[r[3] for r in reference if r[3] not in match_ref],
        extra=[c["cluster_id"] for c in clusters if c["cluster_id"] not in match_calls],
    )
