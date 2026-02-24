# Discovery: Boundary Return Variant Sweep (BTC, Training + Last 48h Validation)

Date: 2026-02-11

Run artifacts:
- `/Users/vitolo/Desktop/projects/poly/scripts/output/window_edge_variations/20260211T092018Z`

Config source:
- `/Users/vitolo/Desktop/projects/poly/docs/discoveries/experiments.yaml`

Runner:
- `/Users/vitolo/Desktop/projects/poly/scripts/window_edge/run_boundary_return_experiments.py`

## Scope
- 5 experiments from `experiments.yaml`
- Training: full `training` timeline (`spot_15m` events at `:00/:15/:30/:45`, BTC only)
- Validation: `indicators` last 48 hours
- Thresholding: global training mean/std with sigma ladder `{0.25,0.5,0.75,1,1.5,2,3,4}`
- Operational decision in validation: strongest triggered sigma per event

## Validation Summary (Operational)
experiment | val_n | triggered | trigger_rate | win_rate
---|---:|---:|---:|---:
`1m_5m_boundary_return` | 184 | 124 | 67.3913% | 55.6452%
`10m_30m_boundary_return` | 182 | 133 | 73.0769% | 53.3835%
`5m_15m_boundary_return` | 183 | 136 | 74.3169% | 50.0000%
`10m_20m_boundary_return` | 184 | 127 | 69.0217% | 48.8189%
`5m_10m_boundary_return` | 185 | 144 | 77.8378% | 46.5278%

## Key Findings
- None of these 5 new variants showed strong correlation on training comparable to the prior successful boundary setup.
- `1m_5m_boundary_return` was the best of this batch, but still weak in live-window validation (~55.6%).
- `5m_10m`, `10m_20m`, and `5m_15m` are effectively flat/negative for directional edge in this test.
- This sweep does not produce a replacement for the previously stronger 1m boundary variant.

