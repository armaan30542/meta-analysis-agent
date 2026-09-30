# Vendored skill: pubmed-search-builder

This folder is an unmodified copy of **pubmed-search-builder** by Aaron Tay
(https://github.com/aarontaycheehsien/pubmed-search-builder), MIT licence (see `LICENSE`),
at upstream commit `b217cf4bb630703315b6aeb4d013c8263e733765`.

Excluded from the copy: `.codex/` hooks, `.github/`, and `.env*` files, which configure the
upstream repository rather than the skill.

How it connects to this project: the skill's deliverable, `final_strategy.md`, is passed to
`metakit search --strategy final_strategy.md -p <project>`, which runs the strategy against
PubMed, logs it for PRISMA-S, and builds the screening set.

To update: re-copy from upstream and change the commit hash above. Do not edit files here;
contribute changes upstream.
