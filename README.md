# piRNA Studio

Analyze single-end or paired-end small RNA FASTQ libraries against a versioned NCBI reference assembly. The workspace connects sample quality, mapped coverage, cluster discovery, replicate-supported counts, differential expression, reference overlap and reproducible exports.

## Download

Download **piRNA-Studio.zip** from the [latest release](https://github.com/MythTbh/piRNA-Studio/releases/latest), extract it to a permanent writable folder, and open **Launch piRNA Studio.cmd** on Windows or **Launch piRNA Studio.command** on Mac. The first launch downloads the research dependencies automatically. The local upload limit is **4 GiB total per submission**. There are no watermarks or third-party promotional badges in the application interface.

This repository distributes the local app and precomputed demonstrations. A hosted multi-user analysis service is not deployed. The privacy and terms pages are drafts, and the custom-domain website launch remains pending.

## Open the workspace

* **Explore precomputed results.** Open `web/dist/index.html` in a browser. The Drosophila benchmark uses public sequencing data and is explicitly labelled. The Results tab stays empty until an analysis is selected. Synthetic results are not distributed in the interface or its downloads.
* **Analyze local files on Mac or Windows.** On Mac, double-click `Launch piRNA Studio.command`. On Windows, double-click `Launch piRNA Studio.cmd`. Keep the terminal window open while a run is active. On first launch, the launcher downloads and verifies a project-local Python 3.12 / Perl 5.32.1 environment, installs the pinned Python packages and research scripts, and then opens the app. Internet is required for initial setup. Subsequent launches verify and reuse the tools. Keep the extracted folder in its permanent location before first launch. On Linux x86_64, run `bash "Launch piRNA Studio.command"`. Windows uses native Python and Strawberry Perl; Docker and WSL are not required.
* **Run the research tools in containers.** From this directory run `docker compose up --build`. Open the same address and choose the proTRAC backend. Docker Compose runs a web proxy and the Python engine, with analysis files in the named runs volume. Stop a local launcher before starting Compose on the same port.

## Try an analysis

The six gzipped FASTQs, sample CSV, genome FASTA, rRNA filter and reference BED in `engine/example/` form a deterministic synthetic study. Run this synthetic study with the CLI commands below; its artificial genome is separate from the model-organism references in the setup wizard. A single request can contain up to 4 GiB total (all samples, references and multipart metadata combined). Uploads are buffered to temporary disk files and staged with bounded memory. Keep disk space available for both the temporary upload and staged files, plus analysis outputs. For larger studies use the CLI. This upload allowance does not bound analysis RAM usage. The local server keeps its run database and uploads in `.pirna-data/`; set `PIRNA_DATA` before launch to choose another location. Local analysis is designed for a single trusted workstation.

The portable backend requires only Python and accepts references up to two million bases. It performs exact matching on both strands and groups nearby mapped loci using explicit thresholds. Use the proTRAC backend to run cutadapt, NGS TOOLBOX duster, best-hit sRNAmapper and proTRAC. Without PyDESeq2 the portable environment can export descriptive fold changes. A fitted test uses integer unique-read counts, with fractional abundances separately available in the count matrix.

## Automatic first-launch setup

Extract the ZIP into a permanent writable folder. Open `Launch piRNA Studio.command` on Mac or `Launch piRNA Studio.cmd` on Windows. On Windows, a short path such as `C:\piRNA-Studio` helps avoid legacy tool path-length limits; do not run the launcher from inside the ZIP. Setup runs automatically when tools are absent or fail verification. It downloads a checksum-pinned micromamba bootstrap and Python 3.12 from conda-forge, pinned Python packages from PyPI, and checksum-verified upstream analysis scripts. Mac uses Perl 5.32.1 from conda-forge; Windows uses the checksum-verified Strawberry Perl 5.32.1.1 portable distribution. No administrator installation, Homebrew, Docker, WSL, or preinstalled Python/Conda is required. The Windows launcher applies its PowerShell execution setting only to the launched process; it does not change machine or user execution policies. macOS may still ask you to approve opening the unsigned launcher.

The installer targets 64-bit Windows 10/11 (Intel/AMD), macOS Apple Silicon and Intel, and Linux x86_64. Native Windows ARM64 and 32-bit Windows are not supported. The native-platform workflow checks installation and analysis on Windows and macOS; see its current status in GitHub Actions. Allow several minutes and several GB of free space, in addition to reference genomes and analysis files. Downloads depend on upstream services and internet access. A download failure stops setup before the app opens; reopening the launcher retries setup. Details appear in `.runtime/setup.log` on Mac or `.runtime/setup-windows.log` on Windows. Genomes download separately when selected.

The environment and its caches are under `.runtime/`, and research scripts under `.tools/`. Windows also stores portable Perl under `.runtime/strawberry/`. Snakemake is installed on Mac/Linux for optional workflow execution; the Windows launcher runs the same engine directly without Snakemake. Existing verified `.venv` / `.perl` installations are reused. Micromamba also records the environment path in the standard `~/.conda/environments.txt` registry. Setup does not modify `.pirna-data/`. Keep the app in its installation location because environments contain absolute paths. The Docker build remains an alternative for container-based deployment.

One sample per condition can run cluster discovery and descriptive fold changes; p-values and adjusted p-values are unavailable without biological replication. For the optional FastAPI service, use the installed runtime to run `uvicorn server.asgi:app --port 8765` with one worker and the tool paths configured by `packaging/runtime.sh`.

## Command line and exports

```sh
python -m engine.pipeline engine/example/config.json runs/synthetic
python -m engine.pipeline benchmark/config.json runs/fly-window
```

Use a fresh output directory. Paths in the JSON config are relative to the config file. The second command uses the research environment. Results include BED and GFF3 features, per-sample counts, DE results, QC, read accounting, reference validation and a machine-readable provenance record. A local run’s Export tab produces an HTML report, an output archive or a reproduction kit containing the uploaded inputs. BED coordinates are zero-based and half-open.

To compare the fitted Wald statistics with R on the same integer matrix, install R, DESeq2 and jsonlite, then run:

```sh
Rscript packaging/crosscheck.R runs/synthetic Perturbed Control
```

The script writes crosscheck.tsv next to the run and reports threshold agreement and rank correlation. Developer test fixtures use generated replicates and known input regions for software verification; they are not user-facing results. Biological interpretation belongs to the separate real-data benchmark, whose sampling limits and results are reported in the workspace.

## Implementation and scope

The offline web interface uses React, TypeScript, Vite, Tailwind, a Radix-based button, Recharts and SVG scientific views. The typed API client and editable frontend source are in web/src. Run `npm ci && npm run build` in web/ to rebuild the bundled interface while preserving the precomputed datasets. Both the Python standard-library HTTP service and the optional FastAPI entry point share the same local SQLite run store. New uploads run locally. The hosted demo distributes precomputed results.

piRNA Studio implements the input checks, portable mapper and exploratory caller, consensus algorithm, strand and sequence QC, fractional and unique counting, interval validation, run store, provenance, interface and reports. It wraps the following research software:

* [Cutadapt](https://cutadapt.readthedocs.io/) 5.1 for adapter trimming.
* [NGS TOOLBOX](https://sourceforge.net/projects/ngs-toolbox/) duster 2.1 for simple-repeat filtering.
* [sRNAmapper and proTRAC](https://sourceforge.net/projects/protrac/) 1.0.4 and 2.4.2 for mapping and probabilistic cluster discovery. The [Bioconda proTRAC recipe](https://bioconda.github.io/recipes/protrac/README.html) gives the CC BY-NC 2.0 license. The source archive supplies download instructions and checksums for the Perl tools.
* [PyDESeq2](https://pydeseq2.readthedocs.io/) 0.5.2 for negative-binomial differential testing, and [Snakemake](https://snakemake.readthedocs.io/) for workflow execution.

Repeat overlap accepts BED intervals. The optional genome-only prediction, piRBase annotation and SRA import extensions are outside this build.

## Reproduce the public benchmark

The benchmark report and interactive track use `benchmark/chromosome.json`. Run `python -m engine.pipeline benchmark/chromosome.json runs/fly-chr2R` from the research environment. The tested Perl version for this chromosome-scale run is 5.32.1. On the host’s system Perl 5.34.1, proTRAC 2.4.2 intermittently failed during its sliding-window scan. A fresh environment with Perl 5.32.1 completed the same run.

* The FASTQ contains the first 20,000 complete, unmodified records of ENA library [SRR1568761](https://www.ebi.ac.uk/ena/browser/view/SRR1568761), downloaded from its [FASTQ distribution](https://ftp.sra.ebi.ac.uk/vol1/fastq/SRR156/001/SRR1568761/SRR1568761.fastq.gz).
* The assembly is the 25,286,936-base [UCSC dm6 chromosome 2R](https://api.genome.ucsc.edu/getData/sequence?genome=dm6;chrom=chr2R). The 38 reference regions come from the [piRNAclusterDB Drosophila GTF](https://pirnaclusterdb.org/data/FASTA/Drosophila_melanogaster.piRNAclusters.gtf). Coordinates were converted to BED and region IDs checked against the database’s [abundance table](https://pirnaclusterdb.org/data/FASTA/Drosophila_melanogaster.piRNAclusters.rpm.tbl).
* The run retained 16,276 inserts in the length window and mapped 9,496 reads to 2R. The database profile called 12 clusters. Two met the 50% reciprocal-overlap criterion, giving 16.7% precision, 5.3% recall and 17.4% base-pair Jaccard overlap. The default proTRAC profile called zero clusters on the same reads. The comparison uses one shallow library and one chromosome. Its performance should be interpreted within those limits.

## Workflow and verification

On Mac/Linux, to execute the optional staged workflow, run `snakemake -s engine/Snakefile --cores 2 --config analysis=engine/example/config.json out=runs/snake-demo` from the project root. The per-stage Conda environments can be enabled with `--software-deployment-method conda`. The research container selects the Snakemake orchestrator. Run `python -m unittest engine.test_engine engine.test_workflow server.test_service` for the test suite; full native-tool coverage requires the research dependencies. The suite checks positive and empty calls, multimapping, interval overlap, reproducibility, uploads, cancellation and exports.

## Single-end, paired-end and biological replicates

Create one sample card per biological replicate. Give replicates from the same group the same condition and distinct replicate numbers (for example, Control 1, Control 2, Control 3). They remain separate samples for counting and differential expression; they are not pooled. Do not use technical replicates as independent biological replicates.

Single-end uses one FASTQ/FASTQ.GZ per card. Paired-end uses matching R1 and R2 files on the same card. Choose the layout on each card; mixed layouts are accepted. CSV and CLI inputs support `layout` (`single` or `paired`) and optional `fastq_r2_path` alongside `fastq_path` (R1).

Paired-end processing assembles overlapping mates in R1 orientation before length filtering. It requires a unique best overlap of at least 12 bases with no more than 10% mismatches, trims read-through sequence, and uses quality scores to resolve disagreements (ties become N). Each assembled pair contributes once. Unmerged pairs are discarded, so nonoverlapping libraries are not supported by this assembler. Pre-flight shows sampled merge rates; read accounting shows total pairs and pairs merged. Matching read identifiers and record counts are required. Both file checksums are recorded.

## Automatic NCBI reference genomes

The setup wizard asks for an organism, not a genome file. Choose fruit fly, C. elegans, zebrafish, mouse, rat, or human. The local app downloads the pinned NCBI RefSeq assembly when you continue, shows download progress, verifies the NCBI MD5 checksum and gzip integrity, and caches it under `.pirna-data/references/`. Later uses verify and reuse the cached download. Failed downloads can be retried with Continue. Internet access is needed for the initial download; compressed files range from about 30 to 930 MiB. Full genomes and analysis intermediates need additional disk space and RAM.

The wizard uses the installed proTRAC backend for these full genomes. Pre-flight checks external-tool availability before analysis. The public hosted website is a static workspace; downloads and computation run in the downloadable local app. No genome FASTA is uploaded by the user.

Assemblies are pinned in `engine/reference_catalog.json` (and mirrored for the web picker). The run manifest records the assembly accession/version, NCBI URL, expected MD5, SHA-256, and verification time. Sequence headers retain NCBI accession names; optional BED annotations must use the same assembly and sequence IDs. API/CLI workflows still accept custom genomes for existing scripts and the synthetic examples.
