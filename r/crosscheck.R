# Independent re-analysis of a metakit outcome with metafor.
# Usage: Rscript r/crosscheck.R <effects.csv> <method> <test> <out.json>
# Called by `metakit crosscheck`; prints nothing on success.
suppressPackageStartupMessages({ library(metafor); library(jsonlite) })
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[1], stringsAsFactors = FALSE)
res <- rma(yi, vi, data = d, method = args[2], test = args[3],
           control = list(threshold = 1e-10, tol = 1e-12))
out <- list(metafor_version = as.character(packageVersion("metafor")),
            k = res$k, estimate = as.numeric(res$beta), se = as.numeric(res$se),
            ci_lb = res$ci.lb, ci_ub = res$ci.ub, pval = res$pval,
            tau2 = res$tau2, I2 = res$I2, QE = res$QE)
if (res$k >= 3) {
  rt <- regtest(res); out$egger_p <- rt$pval
  tf <- trimfill(res); out$trimfill_k0 <- tf$k0; out$trimfill_estimate <- as.numeric(tf$beta)
}
writeLines(toJSON(out, auto_unbox = TRUE, digits = NA), args[4])
