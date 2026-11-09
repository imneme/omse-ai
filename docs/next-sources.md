# The Spectrum Next: bring your own sources

omse-ai's Spectrum Next (`next.py`, over `src/nextcore.cpp`) needs none of these to build or to run most of its tests. Three kinds of test reach for files that aren't in this repository, and each skips, saying which, when they're missing.

| Setting | What | Needed for |
|---|---|---|
| `OMSE_AI_NEXT_ROMS` | the official distribution's `machines/next` folder | `Next(boot='fast')`, which starts NextZXOS from the firmware's handover, and the tests that use it |
| `OMSE_AI_NEXT_VHDL` | the core 3.02.02 VHDL: its `cores/zxnext` folder | the tests that check the code's citations against the VHDL lines they cite |
| `OMSE_AI_NEXT_SURVEY` | the folder with `nextregs.tsv` from the survey (see below) | one table check |

## The distribution

The Next's System/Next SD card files, from the tbblue repository. `machines/next` holds the ROM images, `MENU.DEF` and `CONFIG.INI` that the firmware reads:

```sh
git clone https://gitlab.com/thesmog358/tbblue.git
export OMSE_AI_NEXT_ROMS="$PWD/tbblue/machines/next"
```

omse-ai was built against `de6e464aab8be694ee0add6f57581406711b20e7` (6 November 2026: System/Next 26.11, NextZXOS 2.10). Every file there is copyright its authors, under its own licence (`tbblue/docs/licenses/`). Nothing of it is in this repository.

## The VHDL

The Next's hardware, as the FPGA core's VHDL. omse-ai models **core 3.02.02**, the core on the machine that judged this work:

```sh
git clone https://gitlab.com/SpectrumNext/ZX_Spectrum_Next_FPGA.git
git -C ZX_Spectrum_Next_FPGA checkout 20d34a5220e0d310a99b9fdee6e7133f023de9f2   # branch 30202
export OMSE_AI_NEXT_VHDL="$PWD/ZX_Spectrum_Next_FPGA/cores/zxnext"
```

Citations in the code and tests, such as `zxnext:5789` or `zxula.vhd:583`, are line numbers in that commit's files under `cores/zxnext/src/`. The core is by Victor Trucco, Fabio Belavenuto and Alvin Albrecht, with contributions from many others (its `changelog.md` and file headers), under GPL v3 (`cores/zxnext/COPYING`). omse-ai's Next was written by reading it. None of it is copied here.

## The survey

Tests and comments also cite `§N`: sections of NEXT-MACHINE.md, a cited survey of core 3.02.02 written during the build. It isn't in this repository yet, so those references point outside it, and the one test that reads its register table skips.
