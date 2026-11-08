# Adapter presets and pre-flight checks

Additional presets:

- NEBNext Low-bias: `AGATCGGAAGAGCACACGTCTGAACTCCAGTCA` ([NEB instructions](https://www.neb.com/en-us/faqs/what-are-the-sequences-needed-to-trim-the-nebnext-low-bias-small-rna-libraries)).
- Illumina Small RNA v1.5 (legacy libraries): `ATCTCGTATGCCGTCTTCTGCTTG` ([Illumina sequences](https://support-docs.illumina.com/SHARE/AdapterSequences/Content/OligoSeqsSmallRNA.htm)).

Existing presets and custom 3–128 base A/C/G/T sequences remain available. Select the protocol actually used. Presets specify the 3′ adapter; they do not implement kit-specific UMI processing.

External-backend pre-flight uses the installed Cutadapt matcher with the analysis command's defaults: regular 3′ adapter, 10% maximum error rate, minimum overlap 3 bases, indels allowed. The portable backend retains full exact matching. See [Cutadapt documentation](https://cutadapt.readthedocs.io/en/stable/guide.html#regular-3-adapters).

Length percentages use all sampled reads as denominator. Histograms include only predicted trimmed inserts or successfully merged pairs. The existing single-end pipeline discards unmatched reads, including already-trimmed reads without the adapter. Low matches still warn. Other presets matching at least 50% of sampled reads in full and exactly are diagnostic candidates only, never selected automatically. Pre-flight samples at most 1,000 records.
