# eval/

End-to-end evaluation harness for TableTalker.

```sh
make eval              # build datasets, run all 15 cases, write metrics
make eval-datasets     # rebuild eval/datasets/*.csv only
make eval-run          # rerun against an already-running backend on :8000
```

## Layout

- `build_datasets.py` — deterministic generator for 15 synthetic CSVs covering
  the shapes the organizer's auto-grader exercises (e-commerce, HR, finance,
  healthcare, education, transport, environmental, sports, public-services,
  IoT). Synthetic so the eval network doesn't need to reach external sources;
  seeded so a re-run reproduces the same numbers.
- `cases.yaml` — for each dataset: `question`, optional `followup`, optional
  `trap` (with `expected_refusal: true|false`). Hand-written to exercise the
  refusal classifier honestly.
- `run.py` — POSTs each case at `http://localhost:8000`, writes a per-run
  JSON dump to `runs/<timestamp>/`, then computes the aggregate metrics that
  back-fill `自测报告/latest_evaluation_metrics.md`.
- `datasets/` — generated CSVs (gitignored — `make eval-datasets` rebuilds).
- `runs/` — per-run artifacts (gitignored).

## Honesty rule

Every number in `latest_evaluation_metrics.md` must come from a real
`make eval` run on this branch. If a metric can't be measured (e.g. subjective
report quality without a human judge), it stays `未实现` until a real source
exists. See `docs/refusal-policy.md` §"why we don't fake metrics".
