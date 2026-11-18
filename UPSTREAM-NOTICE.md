# Upstream algorithm attribution

The pure function in `upstream_oracle.py` is extracted from `Estimator.estimate()`
in the repository supplied by the user:
https://github.com/Neoinvoker/epic7-item-estimator

Commit: 52238a18b990bb3cd2eacddf48bfcccd5aac2e03 (2023-07-19).

Only its display strings become numeric codes and unused annotations/imports
are removed. No ADB connection or original executable is invoked. The legacy
adapter and oracle remain solely as historical implementation references.
PC 0.4 uses picture_algorithm.py, implementing the user's latest flowchart
and scoring image. It does not use upstream score gates or verdicts.

No top-level license file was present in the inspected revision. This notice
does not grant a new license for the upstream code. Preserve attribution and
check upstream terms before redistributing beyond this private adaptation.

Python/Tcl/Tk, Pillow and the community hero-data snapshot retain their own
bundled license notices. No original user screenshot is included.
