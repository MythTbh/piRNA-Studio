# Usage: Rscript packaging/crosscheck.R run_directory numerator denominator
args <- commandArgs(trailingOnly = TRUE)
stopifnot(length(args) == 3)
suppressPackageStartupMessages(library(DESeq2))
suppressPackageStartupMessages(library(jsonlite))
run <- args[[1]]
raw <- read.delim(file.path(run, "de-counts.tsv"), row.names=1, check.names=FALSE)
res <- fromJSON(file.path(run, "results.json"))
group <- setNames(res$samples$condition, res$samples$sample_id)
stopifnot(all(colnames(raw) %in% names(group)))
stopifnot(all(c(args[[2]], args[[3]]) %in% group))
stopifnot(all(as.matrix(raw) == round(as.matrix(raw))))
meta <- data.frame(condition=factor(group[colnames(raw)]), row.names=colnames(raw))
min.count <- res$provenance$parameters$min_total_count
if (is.null(min.count)) min.count <- res$provenance$params$min_total_count
if (is.null(min.count)) stop("Missing count filter in provenance")
raw <- raw[rowSums(raw) >= min.count,,drop=FALSE]
dds <- DESeqDataSetFromMatrix(round(as.matrix(raw)), meta, ~condition)
# Very low dispersion in a synthetic fixture can preclude estimating a trend.
dds <- tryCatch(DESeq(dds, sfType="poscounts", quiet=TRUE), error=function(err) {
  if (!grepl("all gene-wise dispersion estimates", conditionMessage(err), fixed=TRUE)) stop(err)
  message("Using DESeq2's gene-wise dispersion fallback for this low-variance dataset.")
  obj <- estimateSizeFactors(dds, type="poscounts")
  obj <- estimateDispersionsGeneEst(obj, quiet=TRUE)
  dispersions(obj) <- mcols(obj)$dispGeneEst
  nbinomWaldTest(obj, quiet=TRUE)
})
reference <- as.data.frame(results(dds, contrast=c("condition", args[2], args[3]), alpha=0.05))
reference$cluster_id <- rownames(reference)
py <- subset(res$de, contrast==paste(args[2], "vs", args[3]))
stopifnot(nrow(py)>0, any(is.finite(py$padj)))
comparison <- merge(py, reference[, c("cluster_id", "log2FoldChange", "padj")], by="cluster_id", suffixes=c("_python", "_r"))
comparison$agree <- with(comparison, ((padj_python<0.05 & abs(log2fc)>=1) == (padj_r<0.05 & abs(log2FoldChange)>=1)))
write.table(comparison, file.path(run, "crosscheck.tsv"), sep="\t", quote=FALSE, row.names=FALSE)
message("Comparable calls: ", sum(!is.na(comparison$agree)), "; agreeing: ", sum(comparison$agree, na.rm=TRUE))
message("Spearman log2 fold-change correlation: ", with(comparison, cor(log2fc, log2FoldChange, method="spearman", use="complete.obs")))
