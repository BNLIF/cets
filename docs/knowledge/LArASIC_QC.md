# Quality Control of LArASIC chips for DUNE FD1-HD and FD2-VD Bottom Drift Time Projection Chamber (TPC) Readout Electronics

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/QC procedures/LArASIC_QC.pdf
> Converted: 2026-06-04 (full-text extraction)

Long Baseline Neutrino Facility, DUNE & CERN Neutrino Platform

Document EDMS identifier: 3284638 (Fermilab LBNF)
Created: 24-March-2025
Last Modified: 16-July-2025
Rev. No: 1.1

## Abstract

This document describes the QC process for the front-end chips (LArASIC) used in the DUNE TPC detector readout electronics.

Prepared by:
- V. Tishchenko (BNL)
- S. Gao (BNL)

Checked by:
- C-J Lin (LBNL)
- D. Christian (FERMILAB)
- H. Chen (BNL)

To be approved by:
- J. Paley (FERMILAB)
- K. Fahey (FERMILAB)

## History of Changes

| Date | Version | Changes/Comments | Authors |
|------|---------|------------------|---------|
| 25-March-2025 | 0 | Separated into a standalone document from CE QC plan. | V. Tishchenko |
| 12-July-2025 | 1 | Updated acceptance criteria | S. Gao |
| 16-July-2025 | 1.1 | Testing plan updated | C-J Lin |

## Table of Contents

1. PURPOSE AND SCOPE
2. REPRESENTATIVES AND RESPONSIBILITIES
   - 2.1 CE Consortium Leadership
   - 2.2 Institutional QC Representatives
3. DOCUMENT CONTROL
   - 3.1 Firmware and Software
   - 3.2 Procedures and documents
4. GENERAL DESCRIPTION
5. QC PROCESS OVERVIEW
   - 5.1 Visual Inspection
   - 5.2 Functionality Testing
     - 5.2.1 Power Consumption
     - 5.2.2 Power Cycling
     - 5.2.3 Configuration Registers
     - 5.2.4 Bandgap Reference
     - 5.2.5 Temperature sensor
     - 5.2.6 Baselines
     - 5.2.7 Internal DAC
     - 5.2.8 Baseline & Noise Measurement using ColdADC
     - 5.2.9 Response to an injected pulser
     - 5.2.10 Calibration with Internal DAC
     - 5.2.11 Calibration with External Precise Source (DAC on DAT board)
     - 5.2.12 Direct Input Calibration
     - 5.2.13 Internal Calibration Capacitor
   - 5.3 Cryogenic Testing (Liquid Nitrogen Environment)
   - 5.4 Final Acceptance Criteria
6. DOCUMENTATION AND REPORTING
7. DATA TO HWDB
8. NON-CONFORMANCE HANDLING
9. REFERENCE LARASIC CHIPS
10. TESTING PLAN

## 1 Purpose and Scope

This Quality Control (QC) Plan defines the inspection, testing, and acceptance criteria for the LArASIC Application Specific Integrated Circuit (ASIC) front-end chips used in the DUNE TPC readout electronics. The objective is to ensure that the chips meet the functional, electrical, and reliability requirements necessary for operation in cryogenic conditions.

This QC process applies to all LArASIC chips manufactured for the DUNE experiment. It includes:

- Incoming inspection of fabricated chips.
- Functionality testing at room temperature.
- Performance verification under expected operating conditions (at cryogenic temperatures) for a fraction of chips from each production batch.
- Analysing the information collected during the QC processes.
- Reviewing the results of QC process at regular intervals and developing corrective actions.
- Screening and defect identification.
- Record Keeping – Maintaining detailed records of QC activities for traceability and compliance. The CE consortium uses DUNE HardWare DataBase (HWDB) for record keeping of QC test progress and results, as well as tracking the production, shipping and installation of various components.
- Training and Competency – Ensuring personnel are adequately trained to maintain quality standards.
- Continuous Improvement – Implementing feedback loops and data analysis to enhance processes and reduce defects over time.
- Reporting – Providing updates to DUNE CE consortium leadership and CE Consortium QC specialist on QC progress from each QC testing site.
- Documentation – developing and maintaining QC procedures (testing, shipping, installation, handling, etc.).
- Software – developing and maintaining the software for QC testing.
- Coordinating the work between different QC testing sites; assuring that the QC procedures are applied uniformly across the various sites involved in detector construction, installation, and integration.
- Organizing QC meetings to share experience between different testing sites, discuss problems, develop corrective action, etc.

## 2 Representatives and Responsibilities

### 2.1 CE Consortium Leadership

See EDMS:2815079.

### 2.2 Institutional QC Representatives

- Vladimir Tischenko (BNL QC Test Site)
- Kendall Mahn (MSU QC Test Site)

Responsibilities:

- Supervise and coordinate daily QC activities at the Test Site, ensuring compliance with established QC procedures and QC plan (see EDMS:3284638).
- Review and verify inspection and test data for accuracy, completeness, and compliance with acceptance criteria.
- Serve as the primary liaison with the CE Consortium QC Manager on all QA/QC-related matters, providing updates and addressing concerns.
- Track and monitor the status of all required testing according to the Testing Plan and Log, ensuring timely execution.
- Identify, document, and report deficiencies by issuing Nonconformance Reports (NCRs) and coordinating necessary corrective actions.
- Monitor the yield, ensuring proper tracking and resolution of nonconforming components.
- Investigate the cause of failures to ensure the functionality of the Test Setup and adherence to the procedures.
- Ensure proper record-keeping by accurately logging QC data and test results in the DUNE Hardware Database (HWDB).
- Oversee and maintain QC test setups, ensuring that all equipment is functional and calibrated as required.
- Ensure QC software is up to date and properly configured to support testing and data collection.
- Adapt and refine the QC process as needed to accommodate new requirements and evolving procedures.

## 3 Document Control

All relevant QC documents (procedures, manuals, etc.) must be uploaded to CERN EDMS (under EDMS:3284638) and regularly updated to ensure accuracy and compliance. Modifications must be reviewed and approved by the CE Consortium Leadership and CE Consortium QC Representative.

### 3.1 Firmware and Software

The Firmware and software developed for QC testing is available in the following git repositories:

- EPSON robot control program: git:CE-RTS
- Scripts to acquire and analyse QC data for LArASIC chips using WIB interface board and DAT test boards: git:BNL_CE_WIB_SW_QC
- WIB Firmware: git:wib_sim, EDMS:3301152 (files: WIB_firmware.pdf, WIB_firmware.zip)
- Image recognition tools: git:dune-rts-sn-rec

### 3.2 Procedures and documents

1. RTS operation manual at BNL (EDMS:3166660, file RTS-manual-BNL.docx)
2. RTS operation manual at MSU (EDMS:3166660, file RTS-Manual-MSU.pdf)
3. LArASIC testing procedure: step by step instructions (EDMS:3166660, in file RTS-manual-BNL.docx)
4. ESD Protection document (EDMS:2782612)
5. LArASIC chip documentation (EDMS:2314428)

## 4 General Description

LArASIC chips are the frontend chips used in Frontend Electronics MotherBoards (FEMBs) to amplify signals from DUNE TPC sense wires (in FD1-HD) or strips (in FD2-VD) and perform signal shaping to maximize the signal to noise ratio. These chips were produced by Taiwan Semiconductor Manufacturing Company (TSMC), one of the leading companies in the semiconductor industry. The dicing and packaging of the ASICs followed standard industry procedures and were carried out by specialized semiconductor manufacturing facilities.

LArASIC chips are the most fragile electronic components of the FEMB as they are susceptible to damage from Electrostatic Discharges (ESD). Therefore, strict handling procedures must be followed, and appropriate protective equipment must be used during chip and FEMB handling, installation, testing, and transportation, as outlined in the ESD Protection document (EDMS:2782612). To mitigate the risk of ESD-related damage, the Robotic Chip Testing Station (RTS) minimizes human intervention in the chip testing process, ensuring a safer and more uniform handling and evaluation (see EDMS:CERN-0000260416).

Using RTS, all LArASIC chips will undergo room temperature testing, while a subset which passed the room temperature test will also be tested in liquid nitrogen (LN).

The RTS is equipped with an optical system and image recognition software that automatically reads chip serial numbers from the packages. This ensures that test results are accurately linked to each ASIC by serial number, minimizing the risk of human error.

For each tested chip, a detailed test report will be generated and transferred to the central DUNE Hardware Database (HWDB). Only ASICs that successfully pass this QC step will be selected for installation on FEMBs.

## 5 QC Process Overview

The QC process follows a tiered approach, consisting of:

### 5.1 Visual Inspection

Inspect chips for physical defects, packaging integrity, and contamination. Reject chips with cracks, bent pins, and other visible damages.

### 5.2 Functionality Testing

Functionality testing both at room and cryogenic temperatures with RTS includes the following test items for each LArASIC chip:

#### 5.2.1 Power Consumption

Measure the power consumption on the three rails of LArASIC (VDDP, VDDA, VDDO) when FE works with ~4 kHz calibration pulser, for each of six configurations: (two baseline references: 200 mV and 900 mV; three configurations of the output buffer: bypassed, single-ended, differential), calibration with ASIC-DAC set to 0x010.

Acceptance criteria: the measured power consumption must be in the range as specified in the table below:

| baseline | output buffer: bypassed | output buffer: single-ended | output buffer: differential |
|----------|-------------------------|-----------------------------|-----------------------------|
| 200 mV | 100 ± 20 mW @ RT; 100 ± 20 mW @ LN2 | 130 ± 30 mW @ RT; 130 ± 30 mW @ LN2 | 150 ± 20 mW @ RT; 150 ± 30 mW @ LN2 |
| 900 mV | 100 ± 20 mW @ RT; 100 ± 20 mW @ LN2 | 130 ± 30 mW @ RT; 130 ± 30 mW @ LN2 | 150 ± 20 mW @ RT; 150 ± 30 mW @ LN2 |

#### 5.2.2 Power Cycling

Perform multiple power on/off cycles (at least five) and measure the pulse response under predefined configuration (e.g., 14 mV/fC gain, 2.0 μs shaping time, 200 mV baseline, 500 pA leakage current) to ensure stable performance and consistent behaviour after power cycling.

Acceptance criteria: The measured power consumption must be in the range while all 16 channels are active (has response to the inject pulser).

| Configuration | Accepted Range | Note |
|---------------|----------------|------|
| • Baseline: 900 mV<br>• Gain: 14 mV/fC<br>• SE and DIFF output buffer: bypassed<br>• Leakage current: 500 pA<br>• Calibration pulser: ASIC-DAC = 0x10, ~4 kHz | Both RT & LN2:<br>• Power: 100 ± 20 mW<br>• Pedestal: 9500 ± 2000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin<br>• Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin<br>• Abs (PosA - NegA) < 500 ADC bin | Typical configuration in detector commissioning |
| • Baseline: 900 mV<br>• Gain: 14 mV/fC<br>• SE and DIFF output buffer: bypassed<br>• Leakage current: 100 pA<br>• Calibration pulser: ASIC-DAC = 0x10, ~4 kHz | Both RT & LN2:<br>• Power: 100 ± 20 mW<br>• Pedestal: 9300 ± 2000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin<br>• Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin<br>• Abs (PosA - NegA) < 500 ADC bin | Inactive channels prone to appear with lower FE leak current |
| • Baseline: 900 mV<br>• Gain: 14 mV/fC<br>• SE and DIFF output buffer: bypassed<br>• Leakage current: 1000 pA<br>• Calibration pulser: ASIC-DAC = 0x10, ~4 kHz | Both RT & LN2:<br>• Power: 100 ± 20 mW<br>• Pedestal: 9700 ± 2000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin<br>• Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin<br>• Abs (PosA - NegA) < 500 ADC bin | |
| • Baseline: 900 mV<br>• Gain: 14 mV/fC<br>• SE and DIFF output buffer: bypassed<br>• Leakage current: 5000 pA<br>• Calibration pulser: ASIC-DAC = 0x10, ~4 kHz | Both RT & LN2:<br>• Power: 100 ± 20 mW<br>• Pedestal: 11,500 ± 2000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin<br>• Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin<br>• Abs (PosA - NegA) < 500 ADC bin | |
| • Baseline: 200 mV<br>• Gain: 14 mV/fC<br>• SE and DIFF output buffer: bypassed<br>• Leakage current: 500 pA<br>• Calibration pulser: DAT-DAC = 60mV (~60 pC), ~4 kHz | Both RT & LN2:<br>• Power: 100 ± 20 mW<br>• Pedestal: 1200 ± 1000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude: 2000 ± 1000 ADC bin | |
| • Baseline: 200 mV<br>• Gain: 14 mV/fC<br>• SE buffer: bypassed<br>• DIFF buffer: enabled<br>• Leakage current: 500 pA<br>• Calibration pulser: DAT-DAC = 60 mV (~60 pC), ~4 kHz | Both RT & LN2:<br>• Power: 150 ± 20 mW<br>• Pedestal: 100 ~ 1000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude: 2000 ± 1000 ADC bin | |
| • Baseline: 200 mV<br>• Gain: 14 mV/fC<br>• SE buffer: enabled<br>• DIFF buffer: bypassed<br>• Leakage current: 500 pA<br>• Calibration pulser: DAT-DAC = 60 mV (~60 pC), ~4 kHz | Both RT & LN2:<br>• Power: 130 ± 20 mW<br>• Pedestal: 1200 ± 1000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude: 2000 ± 1000 ADC bin | |
| • Baseline: 200 mV<br>• Gain: 14 mV/fC<br>• SE buffer: enabled<br>• DIFF buffer: bypassed<br>• Leakage current: 500 pA<br>• Direct DAT pulser to FE input: 60 pC, ~4 kHz | Both RT & LN2:<br>• Power 100 ± 20 mW<br>• Pedestal: 1200 ± 1000 ADC bin<br>• RMS: 5 ~ 30 ADC bin<br>• Positive Pulse Amplitude: 2000 ± 1000 ADC bin | |

#### 5.2.3 Configuration Registers

Conduct multiple write/read operations on the configuration registers via the SPI interface and verify that the readback values match the expected data, ensuring proper functionality and data integrity.

Acceptance criteria: the readback values must exactly match the write-in values. Since LArASIC programming is performed by COLDATA chips, the way to check SPI programming status is via the FASTACT Status Register #2 (Register 36) of COLDATA. It returns value = 0xFF when 4 LArASIC chips under the same CODATA are programmed as expected.

#### 5.2.4 Bandgap Reference

Measure the bandgap reference voltage to verify its stability and ensure it remains within the specified operating range, confirming proper functionality of the voltage reference circuit.

Acceptance criteria: the measured voltage must be
- 1190 ± 20 mV at RT
- 1160 ± 30 mV at LN2

#### 5.2.5 Temperature sensor

Measure the output voltage of the embedded temperature sensor to verify its functionality and ensure it operates within the expected range for accurate temperature monitoring.

Acceptance criteria: the measured output voltage of the temperature sensor must be in the range
- 850 ± 100 mV at RT
- 250 ± 100 mV at LN2

#### 5.2.6 Baselines

Check baseline (DC output level) of each channel through the monitor pin.

Acceptance criteria: FE baseline of each channel must be in range below:

| Environment | Configuration | Accepted Range of each FE channel |
|-------------|---------------|-----------------------------------|
| RT | 200 mV BL | 250 ± 50 mV |
| RT | 900 mV BL | 920 ± 50 mV |
| LN2 | 200 mV BL | 200 ± 50 mV |
| LN2 | 900 mV BL | 900 ± 50 mV |

#### 5.2.7 Internal DAC

Evaluate the performance of the internal 6-bit Digital-to-Analog Converter (DAC) by measuring its Integral Non-Linearity (INL) and Differential Non-Linearity (DNL) across four gain settings (4.7 mV/fC, 7.8 mV/fC, 14 mV/fC, 25 mV/fC), ensuring proper functionality and accuracy. The actual pulse amplitude of the internal DAC will be monitored through an analog-to-digital converter (ADC) on the test board connected via an analog multiplexer to the appropriate pad of the chip being tested.

Acceptance criteria:

| Environment | Configuration | Accepted Range |
|-------------|---------------|----------------|
| RT | SGP = 1 (4.7mV/fC) | LSB = 19.1 ± 1 mV, INL < 0.2 %, Linear Range: 0~61 |
| RT | SGP = 0, 14mV/fC | LSB = 8.3 ± 1 mV, INL < 0.2 %, Linear Range: 0~63 |
| RT | SGP = 0, 25mV/fC | LSB = 4.7 ± 1 mV, INL < 0.3 %, Linear Range: 0~63 |
| RT | SGP = 0, 7.8mV/fC | LSB = 14.7 ± 1 mV, INL < 0.2 %, Linear Range: 0~63 |
| RT | SGP = 0, 4.7mV/fC | LSB = 19.1 ± 1 mV, INL < 0.2 %, Linear Range: 0~61 |
| LN2 | SGP = 1 (4.7mV/fC) | LSB = 18.6 ± 1 mV, INL < 0.2 %, Linear Range: 0~61 |
| LN2 | SGP = 0, 14mV/fC | LSB = 8.1 ± 1 mV, INL < 0.2 %, Linear Range: 0~63 |
| LN2 | SGP = 0, 25mV/fC | LSB = 4.5 ± 1 mV, INL < 0.3 %, Linear Range: 0~63 |
| LN2 | SGP = 0, 7.8mV/fC | LSB = 14.2 ± 1 mV, INL < 0.2 %, Linear Range: 0~63 |
| LN2 | SGP = 0, 4.7mV/fC | LSB = 18.6 ± 1 mV, INL < 0.2 %, Linear Range: 0~61 |

#### 5.2.8 Baseline & Noise Measurement using ColdADC

Measure the baseline and RMS noise with ColdADC chip under various operating conditions, covering four gain settings (4.7 mV/fC, 7.8 mV/fC, 14 mV/fC, 25 mV/fC), four shaping times (0.5 µs, 1 µs, 2 µs, and 3 µs), two baseline levels (200 mV and 900 mV), and four leakage current values (100 pA, 500 pA, 1 nA, and 5 nA), to ensure stability and consistency across configurations. There are 42 configurations in total.

Acceptance criteria:

| Configuration | RT Pedestal (min) | RT Pedestal (max) | RT RMS (min) | RT RMS (max) | LN2 Pedestal (min) | LN2 Pedestal (max) | LN2 RMS (min) | LN2 RMS (max) |
|---------------|-------------------|-------------------|--------------|--------------|--------------------|--------------------|---------------|---------------|
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG00_SG10 | 8600 | 9600 | 6 | 17 | 8200 | 9200 | 3 | 14 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG00_SG10 | 9000 | 10000 | 7 | 20 | 7900 | 8900 | 3 | 17 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG00_SG10 | 8500 | 9500 | 6 | 17 | 8100 | 9100 | 3 | 13 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8800 | 9800 | 6 | 18 | 7900 | 8900 | 3 | 15 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG00_SG11 | 8600 | 9600 | 3 | 9 | 8100 | 9100 | 2 | 8 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG00_SG11 | 8700 | 9700 | 4 | 11 | 7900 | 8900 | 2 | 10 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG00_SG11 | 8500 | 9500 | 3 | 9 | 8000 | 9000 | 2 | 8 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG11 | 8600 | 9600 | 4 | 11 | 8100 | 9100 | 2 | 9 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG01_SG10 | 8700 | 9700 | 10 | 29 | 8500 | 9500 | 5 | 23 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG01_SG10 | 9300 | 10300 | 12 | 35 | 8000 | 9000 | 6 | 30 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG01_SG10 | 8600 | 9600 | 10 | 29 | 8300 | 9300 | 5 | 23 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG10 | 9000 | 10000 | 11 | 32 | 7900 | 8900 | 6 | 28 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG01_SG11 | 8500 | 9500 | 2 | 6 | 8000 | 9000 | 1 | 6 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG01_SG11 | 8600 | 9600 | 2 | 6 | 7900 | 8900 | 1 | 7 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG01_SG11 | 8500 | 9500 | 2 | 6 | 7900 | 8900 | 1 | 6 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG11 | 8600 | 9600 | 2 | 6 | 300 | 1300 | 1 | 6 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST10_SG00_SG10 | 300 | 1300 | 5 | 15 | 600 | 1600 | 3 | 14 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST11_SG00_SG10 | 600 | 1600 | 7 | 20 | 200 | 1200 | 3 | 17 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST10_SG00_SG10 | 200 | 1200 | 5 | 15 | 400 | 1400 | 3 | 14 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 500 | 1500 | 6 | 17 | 200 | 1200 | 3 | 16 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST10_SG00_SG11 | 300 | 1300 | 3 | 9 | 400 | 1400 | 2 | 9 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST11_SG00_SG11 | 400 | 1400 | 4 | 11 | 200 | 1200 | 2 | 10 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST10_SG00_SG11 | 200 | 1200 | 3 | 9 | 300 | 1300 | 2 | 9 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG11 | 300 | 1300 | 3 | 9 | 400 | 1400 | 2 | 9 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST10_SG01_SG10 | 400 | 1400 | 9 | 27 | 900 | 1900 | 5 | 23 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST11_SG01_SG10 | 900 | 1900 | 12 | 35 | 300 | 1300 | 6 | 29 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST10_SG01_SG10 | 300 | 1300 | 9 | 27 | 600 | 1600 | 5 | 23 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG10 | 700 | 1700 | 10 | 30 | 200 | 1200 | 6 | 28 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST10_SG01_SG11 | 300 | 1200 | 2 | 6 | 300 | 1300 | 1 | 7 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST00_ST11_SG01_SG11 | 300 | 1300 | 2 | 6 | 200 | 1200 | 1 | 7 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST10_SG01_SG11 | 300 | 1200 | 2 | 6 | 300 | 1300 | 1 | 7 |
| RMS_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG11 | 300 | 1300 | 2 | 6 | 8100 | 9100 | 1 | 7 |
| RMS_OUTPUT_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8700 | 9700 | 6 | 18 | 8000 | 9000 | 3 | 15 |
| RMS_OUTPUT_SDD0_SDF1_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8600 | 9600 | 6 | 18 | 8100 | 9100 | 4 | 18 |
| RMS_OUTPUT_SDD1_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 9300 | 6 | 18 | 400 | 1400 | 3 | 16 |
| RMS_OUTPUT_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 500 | 1500 | 6 | 17 | 300 | 1300 | 3 | 15 |
| RMS_OUTPUT_SDD0_SDF1_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 300 | 1200 | 6 | 18 | 400 | 1400 | 3 | 16 |
| RMS_OUTPUT_SDD1_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 300 | 1100 | 6 | 17 | 8100 | 9100 | 3 | 15 |
| RMS_SLK_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8800 | 9800 | 6 | 18 | 10700 | 11700 | 3 | 15 |
| RMS_SLK_SDD0_SDF0_SLK00_SLK11_SNC0_ST01_ST11_SG00_SG10 | 10900 | 11900 | 8 | 23 | 7900 | 8900 | 7 | 37 |
| RMS_SLK_SDD0_SDF0_SLK01_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8600 | 9600 | 6 | 17 | 8400 | 9400 | 3 | 13 |
| RMS_SLK_SDD0_SDF0_SLK01_SLK11_SNC0_ST01_ST11_SG00_SG10 | 8900 | 9900 | 6 | 18 | 8400 | 9400 | 4 | 18 |

where:
- SDD0: Differential output buffer disabled
- SDD1: Differential output buffer enabled
- SDF0: Single-Ended buffer disabled
- SDF1: Single-Ended buffer enabled
- SLK00_SLK10: 500 pA leakage current
- SLK01_SLK10: 100 pA leakage current
- SLK00_SLK01: 5000 pA leakage current
- SLK01_SLK01: 1000 pA leakage current
- SNC0: 900 mV baseline
- SNC1: 200 mV baseline
- ST00_ST10: 1 µs shaping time
- ST01_ST10: 0.5 µs shaping time
- ST00_ST11: 3 µs shaping time
- ST01_ST11: 2 µs shaping time
- SG00_SG10: 14 mV/fC gain
- SG00_SG11: 7.8 mV/fC gain
- SG01_SG10: 25 mV/fC gain
- SG01_SG11: 4.7 mV/fC gain

#### 5.2.9 Response to an injected pulser

Measure the response of each FE channel with ColdADC chip under various operating conditions, covering four gain settings (4.7 mV/fC, 7.8 mV/fC, 14 mV/fC, 25 mV/fC), four shaping times (0.5 µs, 1 µs, 2 µs, and 3 µs), two baseline levels (200 mV and 900 mV), and four leakage current values (100 pA, 500 pA, 1 nA, and 5 nA), to ensure stability and consistency across configurations. There are 21 configurations in total.

Acceptance criteria:

##### Acceptance criteria for room temperature

| Configuration | Pedestal (min) | Pedestal (max) | RMS (min) | RMS (max) | PosA | NegA | Abs(PosA-NegA) |
|---------------|----------------|----------------|-----------|-----------|------|------|----------------|
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 10300 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG11 | 8100 | 10100 | 4 | 11 | 4300 +/- 500 | 4300 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG10 | 8500 | 10500 | 11 | 33 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG11 | 8100 | 10100 | 3 | 8 | 3400 +/- 500 | 3400 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 500 | 1500 | 6 | 18 | 4300 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG11 | 300 | 1300 | 4 | 11 | 4300 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG10 | 700 | 1700 | 11 | 33 | 4400 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG11 | 300 | 1300 | 2 | 6 | 3300 +/- 500 | N/A | < 100 |
| CHK_OUTPUT_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 10300 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_OUTPUT_SDD0_SDF1_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8100 | 10100 | 6 | 18 | 4500 +/- 500 | 4500 +/- 500 | < 100 |
| CHK_OUTPUT_SDD1_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7800 | 9800 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_BL_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 10300 | 7 | 20 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_BL_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 500 | 1500 | 6 | 18 | 4300 +/- 500 | N/A | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 10300 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK00_SLK11_SNC0_ST01_ST11_SG00_SG10 | 9900 | 12900 | 8 | 23 | 4300 +/- 500 | 4300 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK01_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8100 | 10100 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK01_SLK11_SNC0_ST01_ST11_SG00_SG10 | 8400 | 10400 | 6 | 18 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG00_SG10 | 8100 | 10100 | 6 | 17 | 4300 +/- 500 | 4300 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG00_SG10 | 8400 | 10400 | 7 | 21 | 4400 +/- 500 | 4400 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG00_SG10 | 8000 | 10000 | 6 | 18 | 3600 +/- 500 | 3600 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 8300 | 10300 | 6 | 17 | 4400 +/- 500 | 4400 +/- 500 | < 100 |

##### Acceptance criteria for LN2

| Configuration | Pedestal (min) | Pedestal (max) | RMS (min) | RMS (max) | PosA | NegA | Abs(PosA-NegA) |
|---------------|----------------|----------------|-----------|-----------|------|------|----------------|
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 3 | 9 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG11 | 7500 | 9500 | 2 | 5 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG10 | 7700 | 9700 | 5 | 15 | 4100 +/- 500 | 4100 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG01_SG11 | 7400 | 9400 | 1 | 4 | 3100 +/- 500 | 3100 +/- 500 | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 400 | 1400 | 4 | 11 | 4000 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG11 | 300 | 1300 | 2 | 6 | 3900 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG10 | 600 | 1600 | 6 | 17 | 4000 +/- 500 | N/A | < 100 |
| CHK_GAINs_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG01_SG11 | 300 | 1300 | 1 | 4 | 3000 +/- 500 | N/A | < 100 |
| CHK_OUTPUT_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 3 | 9 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_OUTPUT_SDD0_SDF1_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 5 | 14 | 4200 +/- 500 | 4200 +/- 500 | < 100 |
| CHK_OUTPUT_SDD1_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 5 | 16 | 4200 +/- 500 | 4200 +/- 500 | < 100 |
| CHK_BL_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 3 | 9 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_BL_SDD0_SDF0_SLK00_SLK10_SNC1_ST01_ST11_SG00_SG10 | 400 | 1400 | 4 | 13 | 4000 +/- 500 | N/A | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 3 | 8 | 4100 +/- 500 | 4100 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK00_SLK11_SNC0_ST01_ST11_SG00_SG10 | 9300 | 11300 | 5 | 16 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK01_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7400 | 9400 | 2 | 7 | 4100 +/- 500 | 4100 +/- 500 | < 100 |
| CHK_SLKS_SDD0_SDF0_SLK01_SLK11_SNC0_ST01_ST11_SG00_SG10 | 7700 | 9700 | 4 | 11 | 4100 +/- 500 | 4100 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST10_SG00_SG10 | 7400 | 9400 | 3 | 8 | 4000 +/- 500 | 4000 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST00_ST11_SG00_SG10 | 7600 | 9600 | 3 | 10 | 4100 +/- 500 | 4100 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST10_SG00_SG10 | 7400 | 9400 | 3 | 8 | 3300 +/- 500 | 3300 +/- 500 | < 100 |
| CHK_TP_SDD0_SDF0_SLK00_SLK10_SNC0_ST01_ST11_SG00_SG10 | 7500 | 9500 | 3 | 8 | 4100 +/- 500 | 4100 +/- 500 | < 100 |

where:
- PosA: Positive FE output pulse amplitude
- NegA: Negative FE output pulse amplitude
- SDD0: Differential output buffer disabled
- SDD1: Differential output buffer enabled
- SDF0: Single-Ended buffer disabled
- SDF1: Single-Ended buffer enabled
- SLK00_SLK10: 500 pA leakage current
- SLK01_SLK10: 100 pA leakage current
- SLK00_SLK01: 5000 pA leakage current
- SLK01_SLK01: 1000 pA leakage current
- SNC0: 900 mV baseline
- SNC1: 200 mV baseline
- ST00_ST10: 1 µs shaping time
- ST01_ST10: 0.5 µs shaping time
- ST00_ST11: 3 µs shaping time
- ST01_ST11: 2 µs shaping time
- SG00_SG10: 14 mV/fC gain
- SG00_SG11: 7.8 mV/fC gain
- SG01_SG10: 25 mV/fC gain
- SG01_SG11: 4.7 mV/fC gain

#### 5.2.10 Calibration with Internal DAC

Measure the gain, linearity, and dynamic range using ColdADC chip under various operating conditions.

Acceptance criteria for both RT and LN2 temperatures:

Calibration with ASIC-DAC (SDD0_SDF0_SLK00_SLK10):

| Configuration | Output Polarity | Gain / (e-/bit) | INL | Linear range / fC |
|---------------|-----------------|-----------------|-----|-------------------|
| SNC0_ST01_ST11_SG00_SG10 | Positive | 30-40 | <1% | > 40 fC |
| SNC0_ST01_ST11_SG00_SG10 | Negative | 30-40 | <1% | > 40 fC |
| SNC1_ST01_ST11_SG00_SG10 | Positive | 30-40 | <1% | > 80 fC |
| SNC0_ST01_ST11_SG01_SG11 | Positive | 95-115 | <1% | > 100 fC |
| SNC0_ST01_ST11_SG01_SG11 | Negative | 95-115 | <1% | > 100 fC |
| SNC1_ST01_ST11_SG01_SG11 | Positive | 95-115 | <1% | > 200 fC |

where:
- SDD0: Differential output buffer disabled
- SDD1: Differential output buffer enabled
- SDF0: Single-Ended buffer disabled
- SDF1: Single-Ended buffer enabled
- SLK00_SLK10: 500 pA leakage current
- SLK01_SLK10: 100 pA leakage current
- SLK00_SLK01: 5000 pA leakage current
- SLK01_SLK01: 1000 pA leakage current
- SNC0: 900 mV baseline
- SNC1: 200 mV baseline
- ST00_ST10: 1 µs shaping time
- ST01_ST10: 0.5 µs shaping time
- ST00_ST11: 3 µs shaping time
- ST01_ST11: 2 µs shaping time
- SG00_SG10: 14mV/fC gain
- SG00_SG11: 7.8mV/fC gain
- SG01_SG10: 25mV/fC gain
- SG01_SG11: 4.7mV/fC gain

#### 5.2.11 Calibration with External Precise Source (DAC on DAT board)

Measure the gain, linearity, and dynamic range using ColdADC chip under various operating conditions.

Acceptance criteria for both RT and LN2 temperatures: Each LArASIC input channel must be connected to an external pulse to ensure that every preamplifier is properly connected to the input pin of the chip, and the measured gain, integrated nonlinearity and linear range must be in the range as specified in the table below:

Calibration with DAT-DAC (SLK00_SLK10_ST01_ST11_SG00_SG10):

| Configuration | Output Polarity | gain / (e-/bit) | INL | Linear range / fC |
|---------------|-----------------|-----------------|-----|-------------------|
| SDD0_SDF0_SNC0 | Positive | 30-40 | <1% | > 40 fC |
| SDD0_SDF0_SNC0 | Negative | 30-40 | <1% | > 40 fC |
| SDD0_SDF0_SNC1 | Positive | 30-40 | <1% | > 80 fC |
| SDD0_SDF1_SNC0 | Positive | 30-40 | <1% | > 40 fC |
| SDD0_SDF1_SNC0 | Negative | 30-40 | <1% | > 40 fC |
| SDD0_SDF1_SNC1 | Positive | 30-40 | <1% | > 80 fC |
| SDD1_SDF1_SNC0 | Positive | 30-40 | <1% | > 40 fC |
| SDD1_SDF1_SNC0 | Negative | 30-40 | <1% | > 40 fC |
| SDD1_SDF1_SNC1 | Positive | 30-40 | <1% | > 80 fC |

where:
- SDD0: Differential output buffer disabled
- SDD1: Differential output buffer enabled
- SDF0: Single-Ended buffer disabled
- SDF1: Single-Ended buffer enabled
- SLK00_SLK10: 500 pA leakage current
- SLK01_SLK10: 100 pA leakage current
- SLK00_SLK01: 5000 pA leakage current
- SLK01_SLK01: 1000 pA leakage current
- SNC0: 900 mV baseline
- SNC1: 200 mV baseline
- ST00_ST10: 1 µs shaping time
- ST01_ST10: 0.5 µs shaping time
- ST00_ST11: 3 µs shaping time
- ST01_ST11: 2 µs shaping time
- SG00_SG10: 14mV/fC gain
- SG00_SG11: 7.8mV/fC gain
- SG01_SG10: 25mV/fC gain
- SG01_SG11: 4.7mV/fC gain

#### 5.2.12 Direct Input Calibration

Measure the gain, linearity, and dynamic range using ColdADC chip under various operating conditions. The calibration pulser is injected directly into each LArASIC input channels.

Acceptance criteria for both RT and LN2 temperatures: Each LArASIC input channel must be connected to an external pulse to ensure that every preamplifier is properly connected to the input pin of the chip, and the measured gain, integrated nonlinearity and linear range must be in the range as specified in the table below:

Calibration pulser injected into FE input directly (SLK00_SLK10_ST01_ST11_SG00_SG10):

| Configuration | Output Polarity | Gain / (e-/bit) | INL | Linear range / fC |
|---------------|-----------------|-----------------|-----|-------------------|
| SNC0_ST01_ST11_SG00_SG10 | Positive | 30-40 | <1% | > 40 fC |
| SNC0_ST01_ST11_SG00_SG10 | Negative | 30-40 | <1% | > 40 fC |
| SNC1_ST01_ST11_SG00_SG10 | Positive | 30-40 | <1% | > 80 fC |

where:
- SDD0: Differential output buffer disabled
- SDD1: Differential output buffer enabled
- SDF0: Single-Ended buffer disabled
- SDF1: Single-Ended buffer enabled
- SLK00_SLK10: 500 pA leakage current
- SLK01_SLK10: 100 pA leakage current
- SLK00_SLK01: 5000 pA leakage current
- SLK01_SLK01: 1000 pA leakage current
- SNC0: 900 mV baseline
- SNC1: 200 mV baseline
- ST00_ST10: 1 µs shaping time
- ST01_ST10: 0.5 µs shaping time
- ST00_ST11: 3 µs shaping time
- ST01_ST11: 2 µs shaping time
- SG00_SG10: 14mV/fC gain
- SG00_SG11: 7.8mV/fC gain
- SG01_SG10: 25mV/fC gain
- SG01_SG11: 4.7mV/fC gain

#### 5.2.13 Internal Calibration Capacitor

Measure the capacitance of the internal calibration capacitor of LArASIC chip.

Acceptance criteria: the measured value of the internal calibration capacitor must be in the range between 185 ± 10 fF.

### 5.3 Cryogenic Testing (Liquid Nitrogen Environment)

Repeat all measurements described in the previous section with LArASIC chips submerged into LN2. Acceptance criteria are specified for the QC items above.

### 5.4 Final Acceptance Criteria

A chip passes QC if:

1. It meets all visual, electrical, and performance criteria.
2. It operates within specification at both room and cryogenic temperatures as outlined in the previous sections.
3. It shows no degradation during QC testing.

## 6 Documentation and Reporting

All QC activities are recorded automatically by the QC script in a QC log and stored electronically. The QC analysis script generates detailed Reports which include:

1. Test results for each chip and each QC step.
2. QC test traceability records for future reference.
3. QC test pass/fail status.

## 7 Data to HWDB

The following information will be recorded to DUNE HWDB for each LArASIC chip:

- Serial number
- Wafer batch number
- QC test site
- QC result (pass/fail)
- Measured noise (for various configurations, warm & cold)
- Measured power consumption (for various configurations, warm & cold)
- Measured bandgap voltage (warm & cold)
- Measured linearity (for various configurations, warm & cold)
- Measured gain (for various configurations, warm & cold)
- Links to QC data files
- Links to histogram & graphics plot files.

## 8 Non-Conformance Handling

If a chip fails QC testing, it will be rejected and placed into a dedicated tray for bad chips clearly labelled as not for installation in DUNE.

## 9 Reference LArASIC chips

For a limited number of LArASIC chips all the measurements will be performed for all the possible combinations of gain, baseline, shaping time, and bias current settings. These chips will be considered as reference chips and used also for intercalibration of the measurements for different chips, different test cards, different test sites. For the reference chips in addition to using the external calibration signal from a DAC we will also use an external pulse generator with even higher precision. For the reference chips we will also obtain the absolute value of the internal calibration capacitance by comparing the results from the internal pulse with measurements done using a well-known external reference capacitor.

## 10 Testing plan

To meet the delivery schedule of CE components for DUNE Far Detectors, the following schedule must be observed for QC testing of 150 wafers of LArASIC chips (15,500 chips for FD2-VD and 31,000 chips for FD1-HD):

| # | Name | Due date |
|---|------|----------|
| 1 | Complete testing of the 1st batch of 20% of LArASIC chips | 12/01/2025 |
| 2 | Complete testing of the 2nd batch of 20% of LArASIC chips | 04/01/2026 |
| 3 | Complete testing of the 3rd batch of 20% of LArASIC chips | 08/01/2026 |
| 4 | Complete testing of the 4th batch of 20% of LArASIC chips | 12/01/2026 |
| 5 | Complete testing of the last batch of 20% of LArASIC chips | 03/01/2027 |

In the early phase of the production, only chips that are fully functional after the LN2 test will be installed on the FEMBs. We will assess the viability of selectively cold testing the ASICs after we have more information on the yield. The criteria for the selection of the LArASIC chips to be used for populating the FEMBs and the exact list of combinations of gain, baseline, shaping time, and bias current settings to be used for some of the tests can be refined after testing a significant number of chips.
