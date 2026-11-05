# Drosophila inputs

| File | Origin and transformation |
| --- | --- |
| SRR1568761.first20000.fastq.gz | First 20,000 complete FASTQ records in archive order from the ENA distribution for SRR1568761. Quality strings and original IDs retained. |
| chr2R.fa | UCSC dm6 chromosome 2R, 25,286,936 bases. Fetched in contiguous one-megabase intervals, uppercased, and wrapped at 80 bases per line. |
| chr2R.bed | All 38 chromosome 2R records in the Release 6 Drosophila piRNAclusterDB GTF. The left endpoint is shifted by one base for BED. Names checked against the coordinate-matched database RPM table. |
| dm6-2R-window.fa and published.bed | Pilot window spanning zero-based chr2R coordinates 6,200,000 to 6,550,000. Reference Dmel_0001 shifted into that coordinate space. |

The chromosome benchmark uses chromosome.json. The window-scale pilot uses config.json. Both use the same sequence reads. See the project README for source links, invocation and interpretation.
