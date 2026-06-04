# Quality Control of ColdADC chips for DUNE FD1-HD and FD2-VD Bottom Drift Time Projection Chamber (TPC) Readout Electronics

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/QC procedures/ColdADC_QC.pdf
> Converted: 2026-06-04 (full-text extraction)

Long Baseline Neutrino Facility, DUNE & CERN Neutrino Platform

Document EDMS identifier: Fermilab LBNF 3303611
Created: 30-June-2025
Last Modified: 16-July-2025
Rev. No: 1.2

## Abstract

This document describes the QC process for the ColdADC ASIC chips used in the DUNE TPC detector readout electronics.

## Approvals

| Prepared by | Checked by | To be approved by |
|-------------|-----------|-------------------|
| V. Tishchenko (BNL) | C-J Lin (LBNL) | J. Paley (FERMILAB) |
| S. Gao (BNL) | D. Christian (FERMILAB) | K. Fahey (FERMILAB) |
| | H. Chen (BNL) | |

## Distribution List / History of Changes

| Date | Version | Changes/Comments | Authors |
|------|---------|------------------|---------|
| 30-June-2025 | 0 | Separated into a standalone document from CE QC plan. | V. Tishchenko, S. Gao |
| 13-July-2025 | 1 | Acceptance criteria updated | S. Gao |
| 15-July-2025 | 1.1 | Updated the list of QC reps. | C-J Lin |
| 16-July-2025 | 1.2 | Testing plan updated | C-J Lin |

## Table of Contents

1. PURPOSE AND SCOPE
2. REPRESENTATIVES AND RESPONSIBILITIES
   - 2.1 CE Consortium Leadership
   - 2.2 Institutional CE QC Representative
3. DOCUMENT CONTROL
   - 3.1 Firmware and Software
   - 3.2 Procedures and documents
4. GENERAL DESCRIPTION
5. QC PROCESS OVERVIEW
   - 5.1 Visual Inspection
   - 5.2 Functionality Testing
     - 5.2.1 Power cycling
     - 5.2.2 I2C communication verification
     - 5.2.3 Check power-on reset (verify default register values)
     - 5.2.4 Reference measurement
     - 5.2.5 Autocalibration
     - 5.2.6 Measure channel performance
     - 5.2.7 Ring oscillator frequency measurement
   - 5.3 Final Acceptance Criteria
6. NON-CONFORMANCE HANDLING
7. DOCUMENTATION AND REPORTING
8. DATA TO HWDB
9. TESTING PLAN

## 1 Purpose and Scope

This Quality Control (QC) Plan defines the inspection, testing, and acceptance criteria for the ColdADC Application Specific Integrated Circuit (ASIC) chips used in the DUNE TPC readout electronics. The objective is to ensure that the chips meet the functional, electrical, and reliability requirements necessary for operation in cryogenic conditions.

This QC process applies to all ColdADC chips manufactured for the DUNE experiment. It includes:

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

### 2.2 Institutional CE QC Representative

- Cheng-Ju Lin (Lawrence Berkeley National Laboratory)
- Martin Tzanov (Louisiana State University)

Responsibilities:

- Supervise and coordinate daily QC activities at the Test Site, ensuring compliance with established QC procedures and QC plan (see EDMS:3303611).
- Review and verify inspection and test data for accuracy, completeness, and compliance with acceptance criteria.
- Serve as the primary liaison with the CE Consortium QC Representative on all QA/QC-related matters, providing updates and addressing concerns.
- Track and monitor the status of all required testing according to the Testing Plan and Log, ensuring timely execution.
- Identify, document, and report deficiencies by issuing Nonconformance Reports (NCRs) and coordinating necessary corrective actions.
- Monitor the yield, ensuring proper tracking and resolution of nonconforming components.
- Investigate the cause of failures to ensure the functionality of the Test Setup and adherence to the procedures.
- Ensure proper record-keeping by accurately logging QC data and test results in the DUNE Hardware Database (HWDB).
- Oversee and maintain QC test setups, ensuring that all equipment is functional and calibrated as required.
- Ensure QC software is up to date and properly configured to support testing and data collection.
- Adapt and refine the QC process as needed to accommodate new requirements and evolving procedures.

## 3 Document Control

All relevant QC documents (procedures, manuals, etc.) must be uploaded to CERN EDMS (under EDMS:3303611) and regularly updated to ensure accuracy and compliance. Modifications must be reviewed and approved by the CE Consortium Leadership and CE Consortium QC Representative.

### 3.1 Firmware and Software

The Firmware and software developed for QC testing is available is available in the following git repositories:

- EPSON robot control program: https://github.com/DUNE/CE-RTS
- Scripts to acquire and analyse QC data for ColdADC chips using WIB interface board and DAT test boards: https://github.com/sgaobnl/BNL_CE_WIB_SW_QC
- Standard WIB firmware: git:wib_sim, EDMS:3301152 (files: WIB_firmware.pdf, WIB_firmware.zip)
- WIB firmware for ColdADC QC: git:wib_fw_coldadc_qc

### 3.2 Procedures and documents

1. RTS operation manual at BNL (EDMS:3166660, file RTS-manual-BNL.docx)
2. RTS operation manual at MSU (EDMS:3166660, file RTS-Manual-MSU.pdf)
3. ColdADC testing procedure: step by step instructions (EDMS:3303611, file TBD; the procedure is very similar to the one for LArASIC testing, see document RTS-manual-BNL.docx in EDMS:3166660)
4. ESD Protection document (EDMS:2782612)
5. Image recognition tools (git:dune-rts-sn-rec)
6. ColdADC chip documentation (EDMS:2314429)

## 4 General Description

The ColdADC chip is implemented in a 65 nm CMOS process. The design was done using cold transistor models produced by Logix Consulting. Logix made measurements of 65 nm transistors (supplied by Fermilab) at liquid nitrogen (LN2) temperature and extracted and provided to the design teams Simulation Program with Integrated Circuit Emphasis (SPICE) models valid at LN2 temperature. These models were used in analog simulations of ColdADC subcircuits. To eliminate the risk of accelerated aging due to the hot-carrier effect, no transistor with a channel length less than 90 nm was used in ASIC design. A special library of standard cells using 90 nm channel-length transistors was developed by members of the University of Pennsylvania and Fermilab groups. Timing parameters were developed for this standard cell library using the Cadence Liberate tool 6 and the Logix SPICE models. Most of the digital logic used in ColdADC was synthesized from Verilog code using this standard cell library and the Cadence Innovus tool. Innovus was also used for the layout of the synthesized logic 400 K range. After the design was complete, simulations using cold models provided by Logix Consulting were used to verify the design.

The ColdADC chips were fabricated by Taiwan Semiconductor Manufacturing Company (TSMC), one of the leading companies in the semiconductor industry. The dicing and packaging of the ASICs followed standard industry procedures and were carried out by specialized semiconductor manufacturing facilities.

Even though ColdADC chips are much less susceptible to damage from Electrostatic Discharges (ESD) compared LArASIC chips, we require that strict handling procedures must be followed, and appropriate protective equipment must be used during chip and FEMB handling, installation, testing, and transportation, as outlined in the ESD Protection document (EDMS:2782612). To mitigate the risk of ESD-related damage, the Robotic Chip Testing Station (RTS) minimizes human intervention in the chip testing process, ensuring a safer and more uniform handling and evaluation (see EDMS:CERN-0000260416).

Using RTS, all ColdADC chips will undergo room temperature testing, while a subset which passed the room temperature test will also be tested in LN2.

The RTS is equipped with an optical system and image recognition software that automatically reads chip serial numbers from the packages. This ensures that test results are accurately linked to each ASIC by serial number, minimizing the risk of human error.

For each tested chip, a detailed test report will be generated and transferred to the central DUNE Hardware Database (HWDB). Only ASICs that successfully pass this QC step will be selected for installation on FEMBs.

## 5 QC Process Overview

QC tests of ColdADC chips include measurements of the effective noise levels and of differential as well as integral non-linearity. The QC process follows a tiered approach, consisting of visual inspection and functionality testing both at room temperature and at cryogenic temperature, as described in the following sections.

### 5.1 Visual Inspection

Inspect chips for physical defects, packaging integrity, and contamination.
Reject chips with cracks, bent pins, and other visible damages.

### 5.2 Functionality Testing

Functionality testing both at room and cryogenic temperatures with RTS includes the following test items for each ColdADC chip. Any ColdADC chip failing these initial tests would be excluded from the tests in LN2.

ColdADC chip QC will be performed using the DUNE ASIC Test (DAT) board. All QC Items required and doable on DAT are listed below:

#### 5.2.1 Power cycling

Ensure that the chip can withstand six power on / power off cycles at both room temperature and liquid nitrogen temperature. Power consumption measurement is included in every power cycling.

Acceptance criteria:

| Configuration | Accepted Range |
|---------------|----------------|
| **1st power cycle:** Single-Ended interface between ColdADC and ADC, SDC and DB buffer bypassed, LArASIC in the calibration mode | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |
| **2nd power cycle:** Same config as 1st | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |
| **3rd power cycle:** Differential interface between ColdADC and ADC, SDC and DB buffer bypassed, LArASIC in the calibration mode | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |
| **4th power cycle:** Same config as 3rd | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |
| **5th power cycle:** Single-Ended interface between ColdADC and ADC, SDC enabled, DB buffer bypassed, LArASIC in the calibration mode | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |
| **6th power cycle:** Single-Ended interface between ColdADC and ADC, SDC enabled, DB buffer bypassed, LArASIC in the calibration mode | Both RT & LN2: Power: 100 ± 20 mW; Pedestal: 9500 ± 2000 ADC bin; RMS: 5 - 30 ADC bin; Positive Pulse Amplitude (PosA): 4500 ± 1500 ADC bin; Negative Pulse Amplitude (NegA): 4500 ± 1500 ADC bin; Abs (PosA - NegA) < 500 ADC bin |

#### 5.2.2 I2C communication verification

The I2C communication to and from the chip should be tested. ADC config registers can be written and read. No I2C error during the configuration.

Acceptance criteria: Pass / Fail.

#### 5.2.3 Check power-on reset (verify default register values)

Test the chip reset and ensure that after the reset the chip comes up in the default state. register values will be read after POR and soft reset, compare them with the default register values listed in the datasheet.

Acceptance criteria: Pass / Fail.

#### 5.2.4 Reference measurement

Sweep the 8-bit DACs for the four reference voltages VREFP, VREFN, VCMI, VCMO.

Acceptance criteria:

| DAC for | Gain range / mV | Offset Range / mV | Voltage with default setting / mV |
|---------|-----------------|-------------------|-----------------------------------|
| VREFP | 35 - 45 | 5 - 15 | 0xDF: 1950 ± 50 mV |
| VREFN | 35 - 45 | 5 - 15 | 0x33: 450 ± 50 mV |
| VCMI | 35 - 45 | 5 - 15 | 0x89: 900 ± 50 mV |
| VCMO | 35 - 45 | 5 - 15 | 0x67: 1200 ± 50 mV |

#### 5.2.5 Autocalibration

Perform the autocalibration procedure.

Acceptance criteria: After the auto calibration, the weights should be in 0.8 - 1.2 times of default weights.

#### 5.2.6 Measure channel performance

Verify the performance of every channel by performing the following measurements.

##### 1. Noise performance

Noise performanc of each chanel under 8 modes are measured. Acceptance criteria are listed below.

| Mode | ADC Noise Range / ADC LSB |
|------|---------------------------|
| ADC set to SE input, input floating | 1.5 – 3 |
| ADC set to DIFF input, input floating | 1 – 2 |
| ADC set to SE input, input connect to external DAC | 2 – 4 |
| ADC set to DIFF input, input connect to external DAC | 1 – 2 |
| ADC set to SE input, input connect to FE (SNC0, SDD0, SDF0) | 13 ± 5 |
| ADC set to SE input, input connect to FE (SNC0, SDD1, SDF0) | 13 ± 5 |
| ADC set to SE input, input connect to FE (SNC0, SDD0, SDF1) | 13 ± 5 |
| ADC set to SE input, input connect to FE (SNC0, SDD0, SDF0) | 13 ± 5 |
| ADC set to SE input, input connect to FE (SNC0, SDD1, SDF0) | 13 ± 5 |
| ADC set to SE input, input connect to FE (SNC0, SDD0, SDF1) | 13 ± 5 |

##### 2. Non-linearity performance

Either Ramp or Sine waveform will be applied to measure the non-linearity of each channel.

Acceptance criteria: DNL < 1 LSB when ADC range is between 1500 and 15000. No missing code when ADC range is between 1500 and 15000. All channel on the same chips exhibit the same INL pattern.

##### 3. Dynamic linearity performance (SNR measurement)

Low distortion sine waveform will be injected to ColdADC for the dynamic linearity measurement.

Acceptance criteria: ADC sampling rate at 1.953125 MS/s.

Signal-to-noise ratio (SNR) is the ratio of the fundamental (PS) to the noise floor (PN), excluding the power at DC and in the first five harmonics. The SNR

| Freq of Sine Waveform / Hz | Acceptance SNR (dBFS) |
|----------------------------|------------------------|
| 8106.23 | > 80 |
| 14781.95 | > 80 |
| 31948.09 | > 80 |
| 72002.41 | > 80 |
| 119686.13 | > 60 |
| 200748.33 | > 60 |
| 358104.70 | > 60 |

##### 4. Full-scale range and overflow check

Measure ADC full-scale range under the proper ADC reference setting (VREFP = 1.95 V, VREFN = 0.45 V, VCMI = 0.9 V, VCMO = 1.2 V).

Acceptance criteria: ADC full scale range (0x0000 – 0x3FFF) is 1.4 ± 0.1 V. No roll-back issue is observed when ADC input voltage is between -0.1 V to 1.9 V.

#### 5.2.7 Ring oscillator frequency measurement

The frequency of the ring oscillator should be measured. This provides a reference value that depends on transistor properties that may change batch to batch (process parameters).

Acceptance criteria: The ring oscillator frequency must be in the range:

- Room temperature: 15 ± 2.0 MHz
- LN2 temperature: 18 ± 2.0 MHz

### 5.3 Final Acceptance Criteria

A chip passes QC if:

1. It meets all visual, electrical, and performance criteria.
2. It operates within specification at both room and cryogenic temperatures as outlined in the previous sections.
3. It shows no degradation during QC testing.

We will assess the viability of selectively cold testing the ASICs after we have more information on the yield. Chips with missing 14-bit codes will be considered non-functional.

## 6 Non-Conformance Handling

If a chip fails QC testing, it will be rejected and placed into a dedicated tray for bad chips clearly labelled as not for installation in DUNE.

## 7 Documentation and Reporting

All QC activities are recorded automatically by the QC script in a QC log and stored electronically. The QC analysis script generates detailed Reports which include:

1. Test results for each chip and each QC step.
2. QC test traceability records for future reference.
3. QC test pass/fail status.

## 8 Data to HWDB

The following information will be recorded to DUNE HWDB for each ColdADC chip:

- Serial number
- Wafer batch number
- QC test site
- QC result (pass/fail)

## 9 Testing Plan

To meet the delivery schedule of CE components for DUNE Far Detectors, the following schedule must be observed for QC testing of 75 wafers of ColdADC chips (21,000 chips for FD2-VD and 42,500 chips for FD1-HD):

| # | Name | Due date |
|---|------|----------|
| 1 | Complete testing of the 1st batch of 20% of ColdADC chips | 12/01/2025 |
| 2 | Complete testing of the 2nd batch of 20% of ColdADC chips | 04/01/2026 |
| 3 | Complete testing of the 3rd batch of 20% of ColdADC chips | 08/01/2026 |
| 4 | Complete testing of the 4th batch of 20% of ColdADC chips | 12/01/2026 |
| 5 | Complete testing of the last batch of 20% of ColdADC chips | 03/01/2027 |

In the early phase of the production, only chips that are fully functional after the LN test will be installed on the FEMBs. We will assess the viability of selectively cold testing the ASICs after we have more information on the yield.
