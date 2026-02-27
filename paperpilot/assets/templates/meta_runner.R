#!/usr/bin/env Rscript
# meta_runner.R — PaperPilot Meta-Analysis Runner
# Args: analysis_csv output_dir outcome_type(binary|continuous) [measure]

suppressPackageStartupMessages({
  library(metafor)
  library(jsonlite)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 3) {
  stop("Usage: Rscript meta_runner.R <analysis_csv> <output_dir> <binary|continuous> [measure]")
}

analysis_csv <- args[1]
output_dir   <- args[2]
outcome_type <- args[3]
measure      <- if (length(args) >= 4) args[4] else NULL

dir.create(output_dir, showWarnings = FALSE, recursive = TRUE)
dat <- read.csv(analysis_csv, stringsAsFactors = FALSE)

results <- list()

if (outcome_type == "binary") {
  measure <- if (is.null(measure)) "OR" else measure
  escalc_dat <- escalc(measure = measure,
                       ai = dat$events_t, n1i = dat$total_t,
                       ci = dat$events_c, n2i = dat$total_c,
                       data = dat)
  res <- rma(yi, vi, data = escalc_dat)
  results$measure      <- measure
  results$estimate     <- as.numeric(res$b)
  results$ci_lb        <- as.numeric(res$ci.lb)
  results$ci_ub        <- as.numeric(res$ci.ub)
  results$pval         <- as.numeric(res$pval)
  results$I2           <- as.numeric(res$I2)
  results$tau2         <- as.numeric(res$tau2)
  results$k            <- res$k
  results$QE           <- as.numeric(res$QE)
  results$QEp          <- as.numeric(res$QEp)
  results$studies      <- dat$study_id

  png(file.path(output_dir, "forest_plot.png"), width = 1000, height = 400 + res$k * 30)
  forest(res, slab = dat$study_id, xlab = measure)
  dev.off()

} else if (outcome_type == "continuous") {
  measure <- if (is.null(measure)) "SMD" else measure
  escalc_dat <- escalc(measure = measure,
                       m1i = dat$mean_t, sd1i = dat$sd_t, n1i = dat$n_t,
                       m2i = dat$mean_c, sd2i = dat$sd_c, n2i = dat$n_c,
                       data = dat)
  res <- rma(yi, vi, data = escalc_dat)
  results$measure      <- measure
  results$estimate     <- as.numeric(res$b)
  results$ci_lb        <- as.numeric(res$ci.lb)
  results$ci_ub        <- as.numeric(res$ci.ub)
  results$pval         <- as.numeric(res$pval)
  results$I2           <- as.numeric(res$I2)
  results$tau2         <- as.numeric(res$tau2)
  results$k            <- res$k
  results$QE           <- as.numeric(res$QE)
  results$QEp          <- as.numeric(res$QEp)
  results$studies      <- dat$study_id

  png(file.path(output_dir, "forest_plot.png"), width = 1000, height = 400 + res$k * 30)
  forest(res, slab = dat$study_id, xlab = measure)
  dev.off()

} else {
  stop(paste("Unknown outcome_type:", outcome_type))
}

results_path <- file.path(output_dir, "results.json")
write_json(results, results_path, auto_unbox = TRUE, pretty = TRUE)
cat("Results written to:", results_path, "\n")
cat("Forest plot written to:", file.path(output_dir, "forest_plot.png"), "\n")
