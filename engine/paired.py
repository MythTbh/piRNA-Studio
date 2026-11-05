"""Assemble overlapping small RNA mates in R1 orientation, once per molecule."""
from itertools import zip_longest
import re

if __package__:
    from .inputs import fastq_records
    from .science import rc
else:
    from inputs import fastq_records
    from science import rc

MIN_OVERLAP = 12
MAX_MISMATCH_FRACTION = 0.10


def read_pairs(r1_path, r2_path):
    for index, pair in enumerate(zip_longest(fastq_records(r1_path), fastq_records(r2_path)), 1):
        r1, r2 = pair
        if r1 is None or r2 is None:
            raise ValueError(f"R1 and R2 have different record counts at pair {index}")
        ids = [re.sub(r"/[12]$", "", read[0]) for read in pair]
        if ids[0] != ids[1]:
            raise ValueError(f"R1/R2 identifiers differ at pair {index}: {ids[0]} and {ids[1]}")
        yield r1, r2


def merge_pair(r1, r2):
    """Choose a unique ungapped overlap; remove sequence beyond inferred insert ends.

    Both reads begin at opposite ends of the same fragment. Candidate fragment
    lengths allow read-through adapters as well as partially overlapping mates.
    Scores reward overlap and penalize mismatches. Ambiguous lengths are rejected.
    """
    _, a, qa = r1
    _, b, qb = r2
    reverse, qualities = rc(b), qb[::-1]
    best_score = 0
    best = None
    tied = False
    for length in range(MIN_OVERLAP, len(a) + len(b) - MIN_OVERLAP + 1):
        start = max(0, length - len(b))
        stop = min(len(a), length)
        overlap = stop - start
        if overlap < MIN_OVERLAP:
            continue
        mate = reverse[-min(length, len(b)):]
        mismatches = sum(x != y or "N" in (x, y) for x, y in zip(a[start:stop], mate[:overlap]))
        if mismatches > overlap * MAX_MISMATCH_FRACTION:
            continue
        score = overlap - 5 * mismatches
        if score == best_score:
            tied = True
        elif score > best_score:
            best_score, best, tied = score, (length, start, stop, mate), False
    if best is None or tied:
        return None
    length, start, stop, mate = best
    mate_quality = qualities[-len(mate):]
    sequence = list(a[:min(length, len(a))])
    for pos in range(start, stop):
        j = pos - start
        if sequence[pos] != mate[j]:
            if sequence[pos] == "N" or mate_quality[j] > qa[pos]:
                sequence[pos] = mate[j]
            elif qa[pos] == mate_quality[j]:
                sequence[pos] = "N"
    sequence.extend(mate[stop - start:])
    return "".join(sequence)
