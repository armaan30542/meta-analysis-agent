# Generates tests/fixtures/metafor_reference.json: gold-standard numbers from
# the R package metafor (Viechtbauer 2010) that metakit's Python engine must match.
# Run from the repo root:  Rscript r/make_reference.R
suppressPackageStartupMessages({ library(metafor); library(jsonlite) })

fit_summary <- function(res) {
  out <- list(
    k = res$k, p = res$p, method = res$method, test = res$test,
    beta = as.numeric(res$beta), se = as.numeric(res$se),
    ci_lb = as.numeric(res$ci.lb), ci_ub = as.numeric(res$ci.ub),
    zval = as.numeric(res$zval), pval = as.numeric(res$pval),
    tau2 = res$tau2, QE = res$QE, QEp = res$QEp,
    I2 = res$I2, H2 = res$H2
  )
  if (res$p > 1) { out$QM <- res$QM; out$QMp <- res$QMp; out$QMdf <- as.numeric(res$QMdf) }
  if (res$p == 1) {
    pr <- predict(res)
    out$pi_lb <- as.numeric(pr$pi.lb); out$pi_ub <- as.numeric(pr$pi.ub)
  }
  out
}

ref <- list(metafor_version = as.character(packageVersion("metafor")))

## 1. BCG vaccine trials (Colditz et al., 1994): log risk ratios
dat <- escalc(measure="RR", ai=tpos, bi=tneg, ci=cpos, di=cneg, data=dat.bcg)
ref$bcg <- list(
  data = dat.bcg[, c("trial","author","year","tpos","tneg","cpos","cneg","ablat","alloc")],
  yi = as.numeric(dat$yi), vi = as.numeric(dat$vi)
)
ref$bcg$fits <- list()
for (m in c("FE","DL","REML","PM","ML","HE")) ref$bcg$fits[[m]] <- fit_summary(rma(yi, vi, data=dat, method=m))
ref$bcg$fits$REML_knha <- fit_summary(rma(yi, vi, data=dat, method="REML", test="knha"))
ci <- confint(rma(yi, vi, data=dat, method="REML"))
ref$bcg$tau2_ci <- as.numeric(ci$random["tau^2", ])
ref$bcg$I2_ci <- as.numeric(ci$random["I^2(%)", ])
ci_dl <- confint(rma(yi, vi, data=dat, method="DL"))
ref$bcg$tau2_ci_DL <- as.numeric(ci_dl$random["tau^2", ])
res <- rma(yi, vi, data=dat, method="REML")
rt <- regtest(res); ref$bcg$egger_rma <- list(zval=rt$zval, pval=rt$pval, limit=as.numeric(rt$est))
rt2 <- regtest(res, model="lm"); ref$bcg$egger_lm <- list(zval=rt2$zval, pval=rt2$pval, dfs=rt2$dfs, limit=as.numeric(rt2$est))
rk <- ranktest(res); ref$bcg$ranktest <- list(tau=as.numeric(rk$tau), pval=rk$pval)
tf <- trimfill(res); ref$bcg$trimfill <- list(k0=tf$k0, side=tf$side, beta=as.numeric(tf$beta), se=as.numeric(tf$se), tau2=tf$tau2)
tf_fe <- trimfill(rma(yi, vi, data=dat, method="FE")); ref$bcg$trimfill_FE <- list(k0=tf_fe$k0, side=tf_fe$side, beta=as.numeric(tf_fe$beta), se=as.numeric(tf_fe$se))
l1o <- leave1out(res); ref$bcg$leave1out <- list(estimate=as.numeric(l1o$estimate), se=as.numeric(l1o$se), tau2=as.numeric(l1o$tau2), I2=as.numeric(l1o$I2))
ref$bcg$metareg_ablat <- fit_summary(rma(yi, vi, mods = ~ ablat, data=dat, method="REML"))
ref$bcg$metareg_ablat_knha <- fit_summary(rma(yi, vi, mods = ~ ablat, data=dat, method="REML", test="knha"))
ref$bcg$metareg_alloc <- fit_summary(rma(yi, vi, mods = ~ factor(alloc), data=dat, method="REML"))
ref$bcg$metareg_ablat_DL <- fit_summary(rma(yi, vi, mods = ~ ablat, data=dat, method="DL"))
ref$bcg$cumul_year <- as.numeric(cumul(res, order=dat$year)$estimate)
dat_or <- escalc(measure="OR", ai=tpos, bi=tneg, ci=cpos, di=cneg, data=dat.bcg)
ref$bcg$or_yi <- as.numeric(dat_or$yi); ref$bcg$or_vi <- as.numeric(dat_or$vi)
dat_rd <- escalc(measure="RD", ai=tpos, bi=tneg, ci=cpos, di=cneg, data=dat.bcg)
ref$bcg$rd_yi <- as.numeric(dat_rd$yi); ref$bcg$rd_vi <- as.numeric(dat_rd$vi)

## 2. Normand (1999): length of hospital stay, continuous outcome
d <- dat.normand1999
md <- escalc(measure="MD", m1i=m1i, sd1i=sd1i, n1i=n1i, m2i=m2i, sd2i=sd2i, n2i=n2i, data=d)
smd <- escalc(measure="SMD", m1i=m1i, sd1i=sd1i, n1i=n1i, m2i=m2i, sd2i=sd2i, n2i=n2i, data=d)
ref$normand <- list(data = d[, c("study","source","n1i","m1i","sd1i","n2i","m2i","sd2i")],
  md_yi = as.numeric(md$yi), md_vi = as.numeric(md$vi),
  smd_yi = as.numeric(smd$yi), smd_vi = as.numeric(smd$vi),
  md_REML = fit_summary(rma(yi, vi, data=md, method="REML")),
  smd_REML = fit_summary(rma(yi, vi, data=smd, method="REML")),
  smd_DL = fit_summary(rma(yi, vi, data=smd, method="DL")))

## 3. Molloy (2014): correlations (Fisher z)
d <- dat.molloy2014
z <- escalc(measure="ZCOR", ri=ri, ni=ni, data=d)
ref$molloy <- list(data = d[, c("authors","year","ni","ri")], yi = as.numeric(z$yi), vi = as.numeric(z$vi),
  REML = fit_summary(rma(yi, vi, data=z, method="REML")))

## 4. Pritz (1997): proportions (logit)
d <- dat.pritz1997
pl <- escalc(measure="PLO", xi=xi, ni=ni, data=d)
ref$pritz <- list(data = d[, c("study","authors","xi","ni")], yi = as.numeric(pl$yi), vi = as.numeric(pl$vi),
  REML = fit_summary(rma(yi, vi, data=pl, method="REML")))

## 5. Single-arm means (synthetic numbers, used only to check the MN formulas)
sm <- data.frame(mi=c(1.2,0.9,1.5,1.1,1.3), sdi=c(0.4,0.5,0.6,0.3,0.45), ni=c(40,55,32,80,61))
mn <- escalc(measure="MN", mi=mi, sdi=sdi, ni=ni, data=sm)
ref$single_mean <- list(data = sm, yi = as.numeric(mn$yi), vi = as.numeric(mn$vi),
  REML = fit_summary(rma(yi, vi, data=mn, method="REML")))

## 6. Zero-cell handling for OR (continuity correction)
zc <- data.frame(ai=c(0,3,5), bi=c(20,17,15), ci=c(4,6,0), di=c(16,14,20))
zo <- escalc(measure="OR", ai=ai, bi=bi, ci=ci, di=di, data=zc)
ref$zero_cell <- list(data = zc, or_yi = as.numeric(zo$yi), or_vi = as.numeric(zo$vi))

## 7. Mean/SD from five-number summaries (conv.fivenum, method = "default" = Luo/Wan/Shi)
fn <- list(n = c(10, 25, 60, 200), min = c(1, 2, 0.5, 3), q1 = c(3, 4, 2, 5), median = c(4, 5, 3, 6),
           q3 = c(6, 7, 4.5, 8), max = c(9, 12, 8, 15))
c1 <- conv.fivenum(min=fn$min, median=fn$median, max=fn$max, n=fn$n, test=FALSE)
c2 <- conv.fivenum(q1=fn$q1, median=fn$median, q3=fn$q3, n=fn$n, test=FALSE)
c3 <- conv.fivenum(min=fn$min, q1=fn$q1, median=fn$median, q3=fn$q3, max=fn$max, n=fn$n, test=FALSE)
ref$fivenum <- list(input = fn,
  range = list(mean = c1$mean, sd = c1$sd), iqr = list(mean = c2$mean, sd = c2$sd),
  both = list(mean = c3$mean, sd = c3$sd))

## 8. More zero-cell handling (RD and PR/PLO add 0.5 to studies with a zero cell)
zr <- escalc(measure="RD", ai=c(0,3), bi=c(20,17), ci=c(4,0), di=c(16,20))
zp <- escalc(measure="PR", xi=c(0,5,20), ni=c(20,30,20))
zl <- escalc(measure="PLO", xi=c(0,5,20), ni=c(20,30,20))
ref$zero_more <- list(rd_yi = as.numeric(zr$yi), rd_vi = as.numeric(zr$vi),
  pr_yi = as.numeric(zp$yi), pr_vi = as.numeric(zp$vi), plo_yi = as.numeric(zl$yi), plo_vi = as.numeric(zl$vi))

writeLines(toJSON(ref, auto_unbox=TRUE, digits=NA, pretty=TRUE, na="null"), "tests/fixtures/metafor_reference.json")
cat("wrote tests/fixtures/metafor_reference.json\n")
