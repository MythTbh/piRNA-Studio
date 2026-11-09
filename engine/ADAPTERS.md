# Adapter presets and pre-flight checks

Additional presets:

- NEBNext Low-bias: `AGATCGGAAGAGCACACGTCTGAACTCCAGTCA` ([NEB instructions](https://www.neb.com/en-us/faqs/what-are-the-sequences-needed-to-trim-the-nebnext-low-bias-small-rna-libraries)).
- Illumina Small RNA v1.5 (legacy libraries): `ATCTCGTATGCCGTCTTCTGCTTG` ([Illumina sequences](https://support-docs.illumina.com/SHARE/AdapterSequences/Content/OligoSeqsSmallRNA.htm)).

Existing presets and custom 3–128 base A/C/G/T sequences remain available. Select the protocol actually used. Presets specify the 3′ adapter; they do not implement kit-specific UMI processing.

External-backend pre-flight uses the installed Cutadapt matcher with the analysis command's defaults: regular 3′ adapter, 10% maximum error rate, minimum overlap 3 bases, indels allowed. The portable backend retains full exact matching. See [Cutadapt documentation](https://cutadapt.readthedocs.io/en/stable/guide.html#regular-3-adapters).

## Adapter handling and read length

New analyses in the web app default to **Trim matching adapters; retain unmatched reads** and **Length filter off**. Missing adapter matches do not prevent mapping, and nonempty reads outside the target 24–32 nt range are retained. The target range still informs QC and proTRAC; these settings do not establish piRNA identity or guarantee cluster calls. Other complexity, mapping, and caller filters still apply.

Choose **Already trimmed** to skip trimming for verified preprocessed single-end libraries. Choose **Require adapter** to discard unmatched reads. Adapter handling is independent of the optional target-range length filter. Paired-end assembly is unchanged: only uniquely overlapping mates are retained.

API/config parameters: `adapter_mode` is `retain` (default), `require`, or `skip`; `length_filter` is `all` or `range` (default for older configs). New web submissions explicitly set `all`. Parameters and read accounting record these choices. For an already-running analysis, start a new run to use new settings.

Pre-flight histograms include retained unmatched read lengths when requested, without claiming they are confirmed insert lengths. Low adapter matches and low proportions in the target range remain warnings. QC computes the target-range percentage from in-range reads even when all lengths are mapped.

Additional named presets added in this update:

- [Illumina miRNA UD](https://support-docs.illumina.com/SHARE/AdapterSequences/Content/Illumina-miRNA-Indexes.htm): `AGATCGGAAGAGCACACGTCTGAACTCCAGTCA`.
- [Lexogen miRVEL](https://faqs.lexogen.com/faq/What-are-the-adapter-sequences-for-miRVEL-Profiling%3F.1796669441.html): `TGGAATTCTCGGGTGCCAAGG`.

These protocols share trimming sequences with other presets. Custom sequences remain supported. A matching sequence does not identify the kit; confirm the study protocol.
