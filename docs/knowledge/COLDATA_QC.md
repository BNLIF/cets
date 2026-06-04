# Quality Control of COLDATA chips for DUNE FD1-HD and FD2-VD Bottom Drift Time Projection Chamber (TPC) Readout Electronics

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/QC procedures/COLDATA_QC.pdf
> Converted: 2026-06-04 (full-text extraction)

Long Baseline Neutrino Facility, DUNE & CERN Neutrino Platform

Document EDMS identifier: 3298044 (Fermilab LBNF)
Created: 05-May-2025
Last Modified: 16-July-2025
Rev. No: 1.1

## Abstract

This document describes the QC process for the COLDATA ASIC chips used in the DUNE TPC detector readout electronics.

**Prepared by:**

- V. Tishchenko — BNL
- S. Gao — BNL

**Checked by:**

- C-J Lin — LBNL
- D. Christian — FERMILAB
- H. Chen — BNL

**To be approved by:**

- J. Paley — FERMILAB
- K. Fahey — FERMILAB

## History of Changes

| Date | Version | Changes/Comments | Authors |
|------|---------|------------------|---------|
| 5-May-2025 | 0 | Separated into a standalone document from CE QC plan. | V. Tishchenko, S. Gao |
| 7-July-2025 | 1 | Modified to reflect the steps implemented using the DAT board & RTS | D. Christian |
| 16-July-2025 | 1.1 | Updated to agree with P6 | D. Christian |

## 1 Purpose and Scope

This Quality Control (QC) Plan defines the inspection, testing, and acceptance criteria for the COLDATA Application Specific Integrated Circuit (ASIC) chips used in the DUNE TPC readout electronics. The objective is to ensure that the chips meet the functional, electrical, and reliability requirements necessary for operation in cryogenic conditions.

This QC process applies to all COLDATA chips manufactured for the DUNE experiment. It includes:

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

- Jon Paley (Fermilab QC Test Site)

Responsibilities:

- Supervise and coordinate daily QC activities at the Test Site, ensuring compliance with established QC procedures and QC plan (see EDMS:3298044).
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

All relevant QC documents (procedures, manuals, etc.) must be uploaded to CERN EDMS (under EDMS:3298044) and regularly updated to ensure accuracy and compliance. Modifications must be reviewed and approved by the CE Consortium Leadership and CE Consortium QC Representative.

### 3.1 Firmware and Software

The Firmware and software developed for QC testing is available in the following git repositories:

- EPSON robot control program: https://github.com/DUNE/FD_CE/tree/main/QC/ChipTesting/RTS_Robot
- Scripts to acquire and analyse QC data for COLDATA chips using WIB interface board and DAT test boards: https://github.com/sgaobnl/BNL_CE_WIB_SW_QC
- WIB firmware: git:wib_sim, EDMS:3301152 (files: WIB_firmware.pdf, WIB_firmware.zip)

### 3.2 Procedures and documents

1. RTS operation manual at BNL (EDMS:3166660, file RTS-manual-BNL.docx)
2. RTS operation manual at MSU (EDMS:3166660, file RTS-Manual-MSU.pdf)
3. COLDATA testing procedure: step by step instructions (EDMS:3298044, file TBD)
4. ESD Protection document (EDMS:2782612)
5. Image recognition tools (git:dune-rts-sn-rec)
6. COLDATA chip documentation (EDMS:2314430)

## 4 General Description

COLDATA is a control and communications ASIC designed to control four LArASIC front-end ASICs and four ColdADC ASICs and to concentrate data from four ColdADCs. It transmits ColdADC data (truncated to 14 bits and 8b10b encoded) to a Warm Interface Board (WIB) over two 1.25 Gbps data links. COLDATA receives commands either from a WIB or from another COLDATA ASIC. It either responds to commands directly (if they are intended for it) or relays the commands to their destination and responses from the destination.

The COLDATA chips were manufactured using a 65 nm CMOS process by Taiwan Semiconductor Manufacturing Company (TSMC), one of the leading companies in the semiconductor industry. The dicing and packaging of the ASICs followed standard industry procedures and were carried out by specialized semiconductor manufacturing facilities.

Even though COLDATA chips are much less susceptible to damage from Electrostatic Discharges (ESD) than LArASIC chips are, we require that strict handling procedures must be followed, and appropriate protective equipment must be used during chip and FEMB handling, installation, testing, and transportation, as outlined in the ESD Protection document (EDMS:2782612). To mitigate the risk of ESD-related damage, the Robotic Chip Testing Station (RTS) minimizes human intervention in the chip testing process, ensuring a safer and more uniform handling and evaluation (see EDMS:CERN-0000260416).

Using RTS, all COLDATA chips will undergo room temperature testing, while a subset which passed the room temperature test will also be tested in liquid nitrogen (LN).

The RTS is equipped with an optical system and image recognition software that automatically reads chip serial numbers from the packages. This ensures that test results are accurately linked to each ASIC by serial number, minimizing the risk of human error.

For each tested chip, a detailed test report will be generated and transferred to the central DUNE Hardware Database (HWDB). Only ASICs that successfully pass this QC step will be selected for installation on FEMBs.

## 5 QC Process Overview

The QC process follows a tiered approach, consisting of:

### 5.1 Visual Inspection

Inspect chips for physical defects, packaging integrity, and contamination.
Reject chips with cracks and bent pins.

### 5.2 Functionality Testing at Room Temperature

Functionality testing of the COLDATA at room temperature include verification of both the control and high-speed data output links. The following tests will be performed:

#### 5.2.1 Initialization checkout

The purpose of the initialization checkout is to tell if the chips are aligned with the sockets. Once the chips pass the initialization checkout, the full QC process starts.

##### 5.2.1.1 Power on reset (POR) check

After powering on the chip and enabling the external 62.5 MHz clock, the current drawn on the five power rails – VDDIO, VDD_LArASIC, VDDCORE, VDDD, and VDDA – is measured.

Acceptance criteria: The measured voltages and currents of POR (power on reset) must be in the range as specified in the table below:

| power rail | voltage (V) min | voltage (V) max | POR current (mA) min | POR current (mA) max |
|------------|-----------------|-----------------|----------------------|----------------------|
| CD_VDDA | 1.15 | 1.25 | 5 | 10 |
| FE_VDDA | 1.70 | 1.90 | -0.1 | 3 |
| CD_VDDCORE | 1.15 | 1.25 | 7 | 12 |
| CD_VDDD | 1.15 | 1.25 | 15 | 25 |
| CD_VDDIO | 2.20 | 2.35 | 40 | 55 |

This QC step verifies that the DAT board is functioning correctly and is ready for COLDATA chip testing.

If the measured currents or voltages fall outside the expected range, this may indicate improper chip seating in the socket, potentially causing short circuits or missing connections. The operator should attempt to resolve the issue by carefully reseating the chip following the procedure. If the problem persists, the COLDATA chip under test should be discarded (placed in the tray for defective chips) and marked as defective in HWDB. If multiple chips in a row exhibit similar issues, the operator should pause the testing and notify the technical coordinator for inspection and further action.

##### 5.2.1.2 Pulser response

The response of every channel to the internal pulser should be measured using a standard set of configuration parameters (see example in Fig. 1).

> **Figure 1:** Example of a response of Cold Electronics to a pulser: all 128 channels from eight groups of ASICs superimposed in one plot (left); evaluated pedestals and pulse height vs channel number (right).

| Configuration | Description |
|---------------|-------------|
| ASIC_DAC_PLS | 1. Differential interface between LArASIC and ColdADC. 2. Calibration pulser with LArASIC embedded DAC. 3. LArASIC: 14 mV/fC, 1 us peak time, 200mV BL, DAC = 0x20, SGP = 0. 4. 1 calibration pulser per 512 samples, control of pulser generated by COLDATA |
| DIRECT_PLS_CHK | 1. Single-ended interface between LArASIC (output buffer disable) and ColdADC. 2. Calibration pulser based on DAT-DAC. It injects into each FE input via 1pF capacitor. 1 calibration pulser per 512 samples. Pulse amplitude ~50mV. 3. LArASIC: 7.8 mV/fC, 1 us peak time, 200mV BL |

Acceptance criteria: Observed periodical stable pulse response of each channel and noise is in the expected range listed in table below.

| Configuration | Pulser Amplitude (ADC units) Min | Pulser Amplitude (ADC units) Max | RMS noise (ADC units) Min | RMS noise (ADC units) max |
|---------------|----------------------------------|----------------------------------|---------------------------|---------------------------|
| ASIC_DAC_PLS | 4000 | 10000 | 5 | 25 |
| DIRECT_PLS_CHK | 2000 | 8000 | 3 | 20 |

If the measured parameters fall outside the expected range, this may indicate 1) defective DAT board, 2) improper chip seating in the socket, 3) disconnect to the building ground. The operator should attempt to resolve the issue by carefully reseating the chip following the procedure. If the problem persists, the COLDATA chip under test should be discarded and replaced. If several chips in succession exhibit similar issues, the operator should pause the testing and notify the technical coordinator for inspection and further action.

This initialization checkout step also verifies:

a. LVDS links between WIB and COLDATA chips
b. I2C communication links between COLDATA chips and ColdADC chips
c. SPI data links between COLDATA chips and LArASIC chips.

#### 5.2.2 Basic functionality check

This test includes verification of reset commands, SPI programming of the LArASIC chips, and control of the COLDATA GPIO bits.

| Item | Description | Acceptance criteria |
|------|-------------|---------------------|
| Hard reset | COLDATA register can be reset to default via the reset pin of COLDATA | Pass / Fail |
| I2C Soft reset | The Soft Reset restores all COLDATA registers to their default values. It does not reset the PLL or interrupt any of the clocks. | Pass / Fail |
| Fast Command reset | Resets COLDATA | Pass / Fail |
| 5 GPIO | Each GPIO can either output 0 or 1 | Pass / Fail |
| SPI communication with LArASIC | Read-back values from LArASIC is same as write-in. | Pass / Fail |

#### 5.2.3 Primary/secondary check

First U1 is set as primary COLDATA (LVDS I2C interface with WIB) and U2 as secondary. I2C functionality is checked by reading and writing all COLDATA I2C registers as well as I2C registers in all 8 ColdADCs. The later is also verified by configuring the ColdADCs to output different patterns and verifying that the expected pattern is seen for each ColdADC. Then U2 is set as primary and U1 as secondary and the same tests are repeated. The test consists of the following steps:

a. Read all the COLDATA registers will and verify the default values. Standard registers should match their specified defaults (hardcoded in the QC test script), and all read-only registers should initially be set to 0.
b. Write data to all I2C registers, read back, and verify to ensure correct write/readback functionality.
c. Issue a soft reset. After the reset, standard registers must return to their default values, and all read-only registers must again be set to 0.
d. I2C relay functionality verification. This includes checking the communication between the primary COLDATA chip, secondary COLDATA chips, and four ColdADC chips. Registers on all five chips will be read and written, and their behaviour will be monitored following a soft reset.

Steps a–d will be performed twice: first using the LVDS I2C interface and then repeated using the CMOS I2C interface.

Acceptance criteria: All read, write, and readback operations must complete successfully, and all readback values must match the expected values.

#### 5.2.4 Power consumption and power cycling

Each COLDATA will be power cycle 6 times, and each time is under different configs. Acceptance criteria are listed below.

current (mA) range of different PLL BAND sets (reg65):

| power rail | PLL_BAND_0x20 min | PLL_BAND_0x20 max | PLL_BAND_0x25 min | PLL_BAND_0x25 max | PLL_BAND_0x26 min | PLL_BAND_0x26 max |
|------------|-------------------|-------------------|-------------------|-------------------|-------------------|-------------------|
| CD_VDDA | 5 | 15 | 5 | 15 | 5 | 15 |
| FE_VDDA | -0.1 | 3 | -0.1 | 3 | -0.1 | 3 |
| CD_VDDCORE | 7 | 15 | 7 | 15 | 7 | 15 |
| CD_VDDD | 15 | 30 | 15 | 30 | 15 | 30 |
| CD_VDDIO | 35 | 55 | 35 | 55 | 35 | 55 |

current (mA) range of different LVDS current set (reg17):

| power rail | LVDS_00 (2mA) min | LVDS_00 (2mA) max | LVDS_02 (4mA) min | LVDS_02 (4mA) max | LVDS_07 (8mA) min | LVDS_07 (8mA) max |
|------------|-------------------|-------------------|-------------------|-------------------|-------------------|-------------------|
| CD_VDDA | 5 | 15 | 5 | 15 | 5 | 10 |
| FE_VDDA | -0.1 | 3 | -0.1 | 3 | -0.1 | 3 |
| CD_VDDCORE | 7 | 15 | 7 | 15 | 7 | 12 |
| CD_VDDD | 15 | 30 | 15 | 30 | 15 | 25 |
| CD_VDDIO | 20 | 40 | 35 | 55 | 60 | 80 |

| Configuration | Pulser Amplitude (ADC units) Min | Pulser Amplitude (ADC units) Max | RMS noise (ADC units) Min | RMS noise (ADC units) max |
|---------------|----------------------------------|----------------------------------|---------------------------|---------------------------|
| PLL_BAND_0x20 | 1000 | 6000 | 5 | 30 |
| PLL_BAND_0x25 | 1000 | 6000 | 5 | 30 |
| PLL_BAND_0x26 | 1000 | 6000 | 5 | 30 |
| LVDS_00 (2mA) | 1000 | 6000 | 5 | 30 |
| LVDS_02 (4mA) | 1000 | 6000 | 5 | 30 |
| LVDS_07 (8mA) | 1000 | 6000 | 5 | 30 |

#### 5.2.5 PLL lock range measurement

The range of PLL band settings for which the PLL locks to the 62.5 MHz clock from the WIB is measured for each COLDATA chip. The voltage controlled oscillator of the PLL contains a binary weighted bank of capacitors so that the Capacitance (C) in the LC oscillator can be set to any one of 64 values. When the PLL is locked, the COLDATA LOCK output is set to a high logic level. The DAC ADC is used to measure this level NN times for each band setting. A typical plot of the measured LOCK level is shown in the figure below.

Acceptance criteria: To be determined.

#### 5.2.6 Fast Commands check

All the Fast Commands received by COLDATA are verified:

a. The Alert (1111_0000), Idle (1010_1010), and Act (1110_0100) commands are automatically verified, because all other features of COLDATA would not work unless these three commands operate correctly.
b. The Reset (1110_1000) command is verified by checking that after it has been issued all the standard register assume the default values and that all the read-only registers are set to zero.
c. The Edge = 1110_0001 (move edge of 2 MHz clock to next rising edge of 62.5 MHz clock) and Sync = 1110_0010 (zero timestamp) commands are combined during the data alignment procedure. Timestamps of primary and secondary COLDATA chips are initialized with different values by hard-reset. By performing data alignment procedure with EDGE and SYNC command sent, same timestamp shows up from both COLDATA chips.
d. The following FAST Command:Act commands are verified:
   a. Clear Saves
   b. LArASIC Pulse
   c. Save Timestamp
   d. Save Status
   e. Reset LArASICs
   f. LArASIC "SPI Reset"

Acceptance criteria: The chip must pass all tests.

#### 5.2.7 EFUSE programming

The RTS robot takes pictures of each COLDATA chip before picking it up from the tray, after placing it in a socket, and again after returning the chip to the tray when the QC procedure is finished. The picture of the chip in the tray is passed to an optical character recognition (OCR) program. After unique identifying numbers have been passed from the OCR program to the QC automation process, these serial numbers are passed to the DAT QC program and the COLDATA EFUSE registers are programmed. The EFUSE contents are then transferred to I2C registers and read back via I2C to verify that the serial numbers were successfully burned into the EFUSE bits.

Acceptance criteria: The readback value matches the value programmed in.

### 5.3 Cryogenic Testing (Liquid Nitrogen Environment)

All tests from the previous section (except for EFUSE programming where EFUSE readout only must be verified) should be repeated with the chip immersed in LN2.

Only a representative sample of COLDATA chips will be tested in LN2 unless FEMB testing indicates that there is a non-negligible failure rate in LN2 of COLDATA chips that pass RT QC testing.

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

The following information will be recorded to DUNE HWDB for each COLDATA chip:

- Serial number
- Wafer batch number
- QC test site
- QC result (pass/fail)

## 8 Non-Conformance Handling

If a chip fails QC testing, it will be rejected and placed into a dedicated tray for bad chips clearly labelled as not for installation in DUNE.

## 9 Testing Plan

To meet the delivery schedule of CE components for DUNE Far Detectors, the following QC testing schedule for COLDATA chips must be observed:

| # | Name | Due date |
|---|------|----------|
| 1 | Complete testing of the 1st batch of 20% of COLDATA chips | 12/01/25 |
| 2 | Complete testing of the 2nd batch of 20% of COLDATA chips | 04/01/26 |
| 3 | Complete testing of the 3rd batch of 20% of COLDATA chips | 08/01/26 |
| 4 | Complete testing of the 4th batch of 20% of COLDATA chips | 12/01/26 |
| 5 | Complete testing of the last batch of 20% of COLDATA chips | 03/01/27 |
