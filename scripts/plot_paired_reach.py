"""R5: the headline paired comparison had no figure -- only Table 2.

Renders the 200 paired seeds of random_seed_campaigns_200_fair_extended.json two
ways, because the mean and the median tell different stories and the paper's
claim ("the separation is widest at the centre") is about the second:

  (a) paired scatter, one point per seed, log-log, with the y = x diagonal.
      Points above the diagonal are seeds the co-maintainer channel wins.
      This makes the 135 / 58 / 7 split visible directly.

  (b) empirical CDFs of the two reach distributions with the medians marked.
      The horizontal gap at F = 0.5 is the 12.4x median separation.

Reads only the published artifact; runs no simulation, so it cannot disagree
with Table 2. Palette matches Figure 1: orange = the worm's channel
(co-maintainer), blue = the dependency channel.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

BASE = Path(__file__).resolve().parent.parent
SRC = BASE / 'data' / 'npm' / 'random_seed_campaigns_200_fair_extended.json'
OUT = BASE / 'figures' / 'paired_reach_B_vs_Dext.png'

CO = '#d66e14'   # wormorange  -- co-maintainer channel
DEP = '#1f487d'  # pkgclean    -- dependency channel
GREY = '#646970'


def ecdf(a):
    x = np.sort(a)
    return x, np.arange(1, len(x) + 1) / len(x)


def main():
    d = json.loads(SRC.read_text())
    b = np.array(d['reach_B_pkgs'], float)
    e = np.array(d['reach_D_extended_pkgs'], float)
    assert len(b) == len(e) == 200

    win, loss, tie = int((b > e).sum()), int((b < e).sum()), int((b == e).sum())
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.6))

    # --- (a) paired scatter ------------------------------------------------
    lim = (0.7, max(b.max(), e.max()) * 1.6)
    ax1.plot(lim, lim, '-', color=GREY, lw=1, zorder=1)
    above = b > e
    ax1.scatter(e[above], b[above], s=26, facecolor=CO, edgecolor='white',
                linewidth=0.4, alpha=0.85, zorder=3,
                label=f'co-maintainer reaches further ({win})')
    ax1.scatter(e[~above & (b != e)], b[~above & (b != e)], s=26, facecolor=DEP,
                edgecolor='white', linewidth=0.4, alpha=0.85, zorder=3,
                label=f'dependency reaches further ({loss})')
    ax1.scatter(e[b == e], b[b == e], s=26, facecolor='none', edgecolor=GREY,
                linewidth=0.9, zorder=3, label=f'tied ({tie})')
    ax1.set(xscale='log', yscale='log', xlim=lim, ylim=lim,
            xlabel='dependency reach on $D_{\\mathrm{ext}}$ (packages)',
            ylabel='co-maintainer reach on $B$ (packages)')
    ax1.text(0.90, 0.86, 'equal reach', transform=ax1.transAxes, ha='right',
             va='top', color=GREY, fontsize=8, rotation=41,
             rotation_mode='anchor')
    ax1.legend(loc='upper left', fontsize=8, frameon=False)
    ax1.set_title('(a) Paired reach, 200 matched seeds', fontsize=10, loc='left')
    ax1.grid(alpha=0.25, lw=0.5)

    # --- (b) dual ECDF -----------------------------------------------------
    for arr, col, lab in ((b, CO, 'co-maintainer $B$'), (e, DEP, 'dependency $D_{\\mathrm{ext}}$')):
        x, y = ecdf(arr)
        ax2.step(x, y, where='post', color=col, lw=1.8, label=lab)
        med = np.median(arr)
        ax2.plot([med], [0.5], 'o', color=col, ms=5, zorder=5)
        ax2.annotate(f'median {med:g}', (med, 0.5), textcoords='offset points',
                     xytext=(8, -14) if col == DEP else (10, 8),
                     color=col, fontsize=8.5)
    ax2.axhline(0.5, color=GREY, lw=0.8, ls=':', zorder=1)
    ax2.set(xscale='log', xlabel='final reach (packages)',
            ylabel='fraction of seeds $\\leq$ reach', ylim=(0, 1.02))
    ax2.legend(loc='lower right', fontsize=9, frameon=False)
    ax2.set_title('(b) Reach distribution over the same seeds', fontsize=10, loc='left')
    ax2.grid(alpha=0.25, lw=0.5)

    fig.tight_layout()
    fig.savefig(OUT, dpi=200)
    print(f'wrote {OUT}')
    print(f'  B mean {b.mean():.1f} median {np.median(b):.1f} max {b.max():.0f}')
    print(f'  D mean {e.mean():.1f} median {np.median(e):.1f} max {e.max():.0f}')
    print(f'  win/loss/tie = {win}/{loss}/{tie}')


if __name__ == '__main__':
    main()
