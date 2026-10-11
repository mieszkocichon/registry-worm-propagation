# Worm reach in package registries: co-maintainer vs. dependency channels

Code and small result files for the study of how far a credential-stealing,
self-propagating registry worm reaches through the co-maintainer graph compared
with the dependency graph (npm, with cross-checks on PyPI, crates.io, RubyGems).

This repository contains **analysis and simulation code only**. It holds no
malware samples or package contents: the inputs are registry metadata (package
names, timestamps, maintainer handles), and the simulations are in-memory
sparse-matrix computations. The fetch scripts only issue read-only requests to
public APIs (OSV.dev, the npm registry, deps.dev, ecosyste.ms).

## Layout

- `scripts/` - data collection (`fetch_*`), graph construction, the SIR engine
  (`simulation_engine.py`, incl. the bilayer mode), plotting, unit tests.
- `run_*.py` - one script per reported experiment (200 paired seeds, sweeps,
  2FA counterfactuals, Zimmermann baseline, bilayer evaluation).
- `notebooks/` - analysis sources as plain `.py` (survival fit, epidemic
  modelling, dependency analysis, counterfactual defence, combined vector).
- `docs/adr/` - design decisions behind the engine and its caches.
- `data/npm/`, `data/cross_ecosystem/` - small result files (JSON) and the
  dependency matrix. Large raw inputs are not in git, see `data/README.md`.
- `release/` - licence texts and `NOTICE.md` for each data package;
  `scripts/build_release.py` builds the packages (see `data/README.md`).
- `figures/` - output directory for generated plots.

## Usage

```bash
pip install -r requirements.txt
python scripts/fetch_osv_data.py          # then the other scripts/fetch_*.py
python run_stats200_fair.py               # e.g. the paired 200-seed campaign
python -m pytest scripts                  # unit tests
```

Run scripts from the repository root, except `notebooks/*.py`, which expect to
be run from `notebooks/`.

## License

Code: MIT (see `LICENSE`). Data derived from third-party sources keeps the
licence of its source; see `data/README.md`.
