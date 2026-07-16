# Knowledge base index

Full-text markdown conversions of CE reference documents (converted 2026-06-04 from PDFs in the OneDrive `CE Knowledge Database`), plus the diagnosis fault taxonomy. Not summaries — grep/read these for register names, spec limits, and acceptance criteria. Figures are caption-only placeholders; consult the source PDF (path in each file's header) when a diagram matters.

## Diagnosis

- [fault-taxonomy.md](fault-taxonomy.md) — QC test items t1–t17 with fault types, granularity, and recommended operator actions. Source of truth for `/ce-diagnose`.

## Chip datasheets

- [LArASIC_datasheet.md](LArASIC_datasheet.md) — LArASIC P5 (16-ch front-end, 180 nm CMOS): channel architecture, gain/peaking/baseline config bits, global+channel register maps, DAC specs, pin/pad list, ENC values.
- [ColdADC_datasheet.md](ColdADC_datasheet.md) — ColdADC: power domains, reference voltages/currents, configuration-memory map, all control registers (page 1 + page 2 I2C), I2C/UART protocol, ring-oscillator process monitors, wirebond pad list.
- [COLDATA_datasheet.md](COLDATA_datasheet.md) — COLDATA: register maps (main page, page-5 PLL/serializer/line-driver, LArASIC pages 1–4), 8b10b flow control, FASTACT commands, frame formats, line-driver settings per cable case, pad/pin list.

## HWDB data geography

- [test-date-registry.md](test-date-registry.md) — where each component type stores its physics test date in `test_data` (path + format + parsing rule), with spike evidence. Mirrors `TEST_DATE_SPECS` in `explore/events.py`.

## QC procedures

- [CE_QC_plan.md](CE_QC_plan.md) — overall CE QC plan: cold cables, flanges (pressure/leak criteria), patch panels, WIB and PTC QC item tables, burn-in requirements, yields and quantities.
- [LArASIC_QC.md](LArASIC_QC.md) — LArASIC chip QC: power consumption/cycling limits, pulse-response and noise acceptance tables (RT and LN2), config legends (SDD/SDF/SLK/SNC/ST/SG).
- [ColdADC_QC.md](ColdADC_QC.md) — ColdADC chip QC: power cycling, reference DAC checks, noise and SNR criteria, full-scale and ring-oscillator limits.
- [COLDATA_QC.md](COLDATA_QC.md) — COLDATA chip QC: POR voltage/current limits, pulser amplitude/RMS noise thresholds, basic-functionality items, power-cycling current ranges by PLL band.

## Adding documents

Convert new PDFs to full-text md (`pdftotext -layout` + cleanup), add the `> Source:` / `> Converted:` header, and list them here with a one-line description. Detailed diagnostic notes will be added over time.
