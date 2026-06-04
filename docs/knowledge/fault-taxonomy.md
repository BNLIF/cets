# FEMB QC fault taxonomy

Test items (t1–t17) as they appear in QC run reports (`report_FEMB_*_t<N>_<P|F>_S<slot>.md`), with fault types and recommended operator actions. Derived from ce-workflow's `backend/femb_test_schema.py` (2026-06-04) and completed with t17, which that schema lacks; this document is the diagnosis source of truth for cets.

Granularity: **channel** = individual channels independently · **chip** = all 16 channels of one LArASIC together · **board** = whole FEMB (128 channels).

## Test items

| # | Name | Granularity | Measures |
|---|------|-------------|----------|
| t1 | pwr_consumption | board | Power consumption per rail (BIAS, LArASIC, ColdADC, COLDATA) in SE and differential modes |
| t2 | pwr_cycle | board | Power cycling stability — rails recover to nominal after each cycle |
| t3 | leakage_current | channel | Per-channel FE pulse response at leakage current settings (100 pA–5 nA) |
| t4 | check_pulse | channel | Pulse response across gains, peaking times, output modes, baselines |
| t5 | rms_noise | channel | Per-channel RMS noise in ADC counts — pedestal run, no pulse injection |
| t6 | calibration_1 | channel | Gain curve: 200 mV baseline, 4.7 mV/fC, 0.5 µs (snc=1, sg0=1, sg1=1, st0=0, st1=1) |
| t7 | calibration_2 | channel | Gain curve: 200 mV baseline, 7.8 mV/fC, 1.0 µs (snc=1, sg0=1, sg1=0, st0=1, st1=0) |
| t8 | calibration_3 | channel | Gain curve: 200 mV baseline, 14 mV/fC, 2.0 µs (snc=1, sg0=0, sg1=0, st0=1, st1=1) |
| t9 | calibration_4 | channel | Gain curve: 200 mV baseline, 25 mV/fC, 3.0 µs (snc=1, sg0=0, sg1=1, st0=1, st1=1) |
| t10 | fe_monitor | board | FE voltage monitoring — LTC2990/LTC2991 power monitors on WIB |
| t11 | fe_dac_monitor | board | LArASIC internal DAC output voltages |
| t12 | coldata_dac_monitor | board | COLDATA/ColdADC internal reference voltages |
| t13 | calibration_5 | channel | Gain curve: 900 mV baseline, 4.7 mV/fC, 0.5 µs (snc=0, sg0=1, sg1=1, st0=0, st1=1) |
| t14 | calibration_6 | channel | Gain curve: 900 mV baseline, 14 mV/fC, 2.0 µs (snc=0, sg0=0, sg1=0, st0=1, st1=1) |
| t15 | adc_sync_pattern | chip | All 16 channels of each chip lock to the COLDATA sync pattern |
| t16 | pll_scan | chip | COLDATA PLL locks across the full frequency scan range |
| t17 | regulator_monitor | board | Regulator output voltages at 4 V_in (2.6/3.0/3.5/4.0 V) × 3 ASIC configs (SE off / SE on / DIFF on) = 12 sets, per rail (CDVDDA, CDVDDIO, ADCR/LVDDD1P2, FER/LVDDP, ADCR/LP25V, …) |

## Fault types

| Fault type | Granularity | Description | Recommended action |
|------------|-------------|-------------|--------------------|
| `overcurrent` | board | Current draw exceeds rail limit — possible short or damaged component | Power off immediately; inspect FEMB for visible damage or short circuit |
| `undercurrent` | board | Current draw below expected minimum — open circuit or failed power domain | Check connector seating and power cable; inspect solder joints on power rails |
| `power_cycle_fail` | board | Rail voltages do not recover to nominal after power cycle | Retry power cycle; if persistent, inspect decoupling capacitors and voltage regulators |
| `leakage_high` | channel | Channel leakage current exceeds 5 nA spec | Identify affected chip/channel; likely damaged input protection diode or contamination |
| `dead_channel` | channel | No pulse/calibration response, or RMS effectively zero | Check wire-bond continuity; if entire chip is dead, suspect COLDATA I2C config failure; re-run `wib_adc_autocali.py` for the affected chip |
| `gain_error` | channel | Charge response deviates >20% from expected gain curve | Re-configure LArASIC registers; compare with adjacent channels on same chip; baseline-dependent error (t6 vs t13) suggests LArASIC bias issue; if both 200 mV and 900 mV curves fail, gain path is damaged |
| `high_noise` | channel | Channel RMS exceeds 2.5× median of all 128 channels | Check cable shielding and ground connections; verify ADC bias settings via `wib_cfgs`; recurring single-channel excess after re-test → suspect the LArASIC serving that channel |
| `rail_voltage_error` | board | VFE or VCD rail voltage outside ±5% of nominal | Check power supply output and cable resistance; inspect WIB power delivery path |
| `dac_error` | board | FE or COLDATA DAC output deviates >10% from programmed value | Re-write DAC registers / re-run `wib_adc_autocali.py`; if persistent, suspect the chip |
| `adc_sync_loss` | chip | Chip fails to lock ADC data lanes to sync pattern — all 16 ch affected | Run `wib_coldata_reset.py` for the affected chip slot; if persistent, re-run `wib_adc_autocali.py` |
| `pll_lock_fail` | chip | COLDATA PLL fails to lock at one or more scan frequencies | Run `wib_coldata_reset.py`; check clock signal integrity; if persistent, COLDATA may need replacement |
| `regulator_out_of_range` | board | A regulator rail deviates from its expected output in one or more of the 12 V_in × config sets (red cells in the t17 table) | Config-dependent deviation (e.g. only SE-on columns) points at load-dependent regulator weakness; check the regulator feeding the flagged rail and its input/output capacitors; compare left/right (ADCL*/ADCR*) rails to localize |

## Report-side conventions

- Failing channels appear at the top of a failed report as `[[<channels>], [<chip indices>]]`, e.g. `[[44], [2]]` = channel 44, chip index 2. Chip index = `channel // 16` (index 0–7 over the 128 channels).
- Chip index → physical position (`LArASIC F1–F4 / B1–B4` in the db's `core_fe.femb_pos`): readout-order mapping **not yet confirmed** — verify before naming a physical chip for replacement.
- LArASIC register encodings used in test configs: `snc` 1=200 mV / 0=900 mV baseline; gain `(sg0,sg1)`: 4.7=(1,1), 7.8=(1,0), 14=(0,0), 25=(0,1) mV/fC; peaking `(st0,st1)`: 0.5µs=(0,1), 1µs=(1,0), 2µs=(1,1), 3µs=(1,1).
