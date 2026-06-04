# COLDADC_P2 (Final) Datasheet

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/datasheets/ColdADC_datasheet.pdf
> Converted: 2026-06-04 (full-text extraction)

Authors: David Christian, Carl Grace
Date: May 1, 2022
Revision: 1.12

COLDADC is a 16-channel low-noise ADC ASIC intended to read out LArASIC preamps in the DUNE Liquid Argon Far Detectors. The ADC accepts single-ended or differential inputs and outputs a serial data stream to COLDATA, the DUNE digital data aggregator/serializer chip. The intended sample rate is approximately 2 MSPS. The ASIC produces 16-bit output which is intended to be truncated to 12 or 14 bits.

## Revision History

| Revision Number | Key Changes | Drafted by | Revision Date |
|---|---|---|---|
| 1.0 | Initial draft (Modified from the COLDADC_P1 datasheet) | DCC | 7/31/20 |
| 1.1 | Corrected sections on pipeline stage gain and on use of VCMI. | DCC | 8/3/20 |
| 1.2 | Corrected default values for registers 29 and 30. Included input configuration in description of default setup. | DCC | 8/3/20 |
| 1.3 | Corrected default state of ring oscillator (it is OFF by default). | DCC | 8/5/20 |
| 1.4 | Added figure showing pad numbering. | DCC | 9/1/20 |
| 1.5 | Added note about gap between pads 152 & 153 to figure showing pad numbering. | DCC | 9/2/20 |
| 1.6 | Added conditions for manual calibration. Removed cal_stages[2:0] from register list since it doesn't work. | CRG & DCC | 3/22/21 |
| 1.7 | Corrected figure caption for block diagram. | DCC | 5/18/21 |
| 1.8 | Eliminated redundant (and incomplete) paragraph on manual calibration. | DCC | 7/9/21 |
| 1.9 | Added a note saying that the default value of config_start_number is wrong (default = 0x10, should be 0x0C). | DCC | 7/9/21 |
| 1.10 | Added a note about unbonded pads 170, 172, 174, & 176 | DCC | 10/26/21 |
| 1.11 | Changed text to clarify that any value other than 1 in registers 2&3 will power down a SHA | DCC | 11/17/21 |
| 1.12 | Added clarification that VSSESD = VSSA2P5 | DCC | 5/1/22 |

## Table of Contents

- Introduction — 5
- Block Diagram — 6
- Power Domains — 6
- Functional Description — 7
  - Input Buffers — 7
  - Sample and Hold Amplifiers and Multiplexer — 8
  - Pipelined ADC and Correction Logic — 8
  - Calibration Engine — 10
  - Data Formatter — 10
  - Reference Blocks — 11
    - Reference Voltages — 11
    - Reference Currents — 12
    - Bandgap Reference — 13
    - CMOS Reference — 13
  - Control Interface — 13
    - I2C — 14
    - UART — 16
  - Power On Reset — 17
  - Process Monitor — 17
- Wire Bonding Pad and Package Pin List — 18
- Configuration Memory — 24
- Page 1 Control Registers — 26
  - Input Buffer Configuration — 26
  - Sample and Hold (SHA) Amplifier Configuration — 27
  - Bandgap Reference Configuration — 29
  - CMOS Reference Configuration — 32
  - Calibration Engine Configuration — 34
  - Overflow Logic Configuration — 35
  - Ring Oscillator Configuration — 36
  - Calibration Forcing Configuration — 36
  - Monitor Output Configuration — 38
  - Backend Configuration — 38
- Page 2 Registers (I2C Only) — 40
- Example Control Register Configurations — 41
  - Default Configuration — 41
  - Calibration — 42
  - Output Format — 42
  - Channel Order and Digital Frame Marker Alignment — 42

## Introduction

Each DUNE Front End Motherboard (FEMB) contains eight LArASIC front end ASICs, eight COLDADC ASICs, and two COLDATA ASICs. Each COLDADC ASIC receives input from one LArASIC front end ASIC. The input can be either single-ended or differential. All voltage inputs are sampled simultaneously. Two groups of 8 channels are multiplexed and input to two 15-stage calibrated pipelined ADCs. The ADC outputs are multiplexed onto 8 LVDS channels and sent to COLDATA for further aggregation and transmission via copper links to warm electronics located outside the cryostat. COLDATA is designed to operate at approximately 2 MSPS using a 64 MHz master clock. In DUNE, the master clock will operate at 62.5 MHz and the sample period will be 512 nsec. Rather than 500 nsec.

COLDADC is highly programable and includes two slow control interfaces (UART and "I2C").

## Block Diagram

> **Figure 1:** COLDADC_P2 Block Diagram (image not included)

## Power Domains

To minimize coupling between digital and analog circuitry, most of the COLDADC_P2 sub circuits are laid out in deep n-wells. There are four power domains, as shown in Table 1. All of the analog circuitry is powered by VDDA2P5 and resides in a single large deep n-well, connected to VSSA2P5. The digital circuitry that directly controls analog function is powered by VDDD2P5. It also resides in a single deep n-well, connected to VSSD2P5. Most of the digital circuitry is powered by VDDD1P2. It also resides in a single deep n-well, connected to VSSD1P2. The LVDS drivers and CMOS drivers and receivers are powered by VDDIO and reside in separate deep n-wells, each connected to VSSDIO. The pads, ESD protection diodes, and clamps are not in deep n-wells. The protection diodes and clamps are powered by VDDIO and connected directly to the chip substrate (VSSESD = VSSA2P5). The LQFP package has a back contact which is connected to VSSESD and should be soldered to the printed circuit board ground.

| Power Rail | Value | Units | Current Draw | Note |
|---|---|---|---|---|
| Analog Power = VDDA2P5 | 2.25 (+/- 5%) | V | TBD | VDDA2P5 is reduced by 250 mV relative to nominal for thick-oxide devices in to reduce voltage stress (hot electron effects) and increase reliability. |
| Digital ADC Power = VDDD2P5 | 2.25 (+/- 5%) | V | TBD | VDDD2P5 is used to power the digital circuits and switches internal to the ADC. VDDD2P5 is reduced by 250 mV relative to nominal to increase reliability. |
| Digital Logic Power = VDDD1P2 | 1.1 (+/- 5%). Max voltage is nominal +10% | V | TBD | VDDD1P2 is used to power the synthesized logic core. VDDD1P2 is reduced by 100 mV relative to nominal for thick-oxide devices to reduce voltage stress (hot electron effects) and increase reliability. |
| ESD Ring / CMOS I/O Power = VDDIO | 2.25 | V | TBD | VDDESD and VDDIO reduced by 250 mV relative to nominal for thick-oxide devices in to reduce voltage stress (hot electron effects) and increase reliability. |

> **Table 1:** Power Domains

## Functional Description

### Input Buffers

As shown in Figure 2, COLDADC has four possible ways to interface with LArASIC. Single-ended inputs can be buffered by single-ended to differential converters (SDCs) or applied directly to the sample-and-hold amplifiers. Similarly, differential inputs can be buffered by differential buffers (DBs) or applied directly to the sample-and-hold amplifiers.

> **Figure 2:** Input Buffer Configuration Options (image not included). Shows signal path: VIN → SDC (sdc_pd = 0) / DB (db_pd = 1) → ibuff → SHA channel, with sha_se_input = 0, VCMI reference, producing vod/vop/von outputs.

### Sample and Hold Amplifiers and Multiplexer

The Sample and Hold Amplifiers (SHAs) are organized in two groups of eight. They sample the input voltages simultaneously at a time controlled by the "2 MHz" clock from COLDATA. The internal 2 MHz clock is resynchronized to the "64" MHz clock and a synchronous "16 MHz" clock is generated and used to clock an 8-to-1 analog multiplexer that presents 8 samples in turn to each of the two ADC pipelines. If the phase of the 2 MHz clock is changed, output data will be garbled for one or two sample periods.

### Pipelined ADC and Correction Logic

A conceptual diagram of an ADC pipeline is shown in Figure 3. Each of the 15 pipeline stages contains a low-resolution 1.5-bit analog-to-digital subconverter containing two comparators, a 1.5-bit digital-to-analog subconverter that produces a voltage based on the two comparator outputs, an analog subtractor, a sample-and-hold amplifier, and an interstage 2x amplifier. Each pipeline stage has the same transfer function (shown in Figure 4). The comparator outputs determine both the digital output of the stage (W0, 0, or W2) and the voltage that is subtracted from the analog value input to the stage before the difference is amplified and input to the next stage. The 16-bit output of the pipeline is the sum of the digital outputs from each of the pipeline stages. The "stage weights" (W0 and W2) are 16-bit two's complement (signed) integers.

The output of each analog pipeline stage is 0, 1, or 2 depending on the comparator outputs. The correction logic sums the corresponding "weights" and produces a 16-bit ADC output. It is possible to test the correction logic by setting the control bit test_correction_logic in register 32 and loading 30-bit patterns into registers 33-40.

> **Figure 3:** Pipelined ADC (image not included). Each pipeline stage contains a Sample and Hold Amplifier (SHA), an Analog to Digital SubConverter (ADSC) consisting of two comparators, a Digital to Analog SubConverter (DASC) that produces a voltage based on the ADSC output, an analog subtracter, and a gain stage. Per-stage digital outputs (W2, 0, W0 selected via MUX/MUX ctrl) feed a 16-bit MUX/ADD/Reg path through stages 0, 1, 2 ... 14 to the next stage.

> **Figure 4:** ADC pipeline stage transfer function (image not included).

### Calibration Engine

The Calibration Engine allows the correction of nonlinearities caused by imperfections in the voltages that are passed from one stage to the next. These imperfections arise from errors in the analog voltage subtracted in each stage and in the gain and offset of the interstage amplifiers.

COLDADC is calibrated using a bootstrap procedure that relies on the fact that the required precision is easily satisfied by the last stages of the pipeline. The seven most significant stages are calibrated by the automated procedure. Starting with the least significant stage to be calibrated, the input to the stage being calibrated is set to the threshold levels of VR/4 and the normal comparator outputs are overridden and forced first to 1 and then to 0. The lower stages of the ADC digitize the analog value output from the stage being calibrated and the difference between the ADC output when the comparator is forced to 1 and when it is forced to 0 is calculated. These two differences (W0 expressed as a negative number and W2 expressed as a positive number) are stored and used as two of the three possible outputs of the stage being calibrated (the other possible output being 0). This procedure is then repeated for the next most significant pipeline stage until stage 0 has been calibrated.

In order to eliminate sensitivity to noise in the individual ADC conversions during calibration, each value is calculated a number of times and an average value used. The number of samples used is set by meas_cycles[3:0] in register 32.

The calibration procedure for ADC0 is started by setting bit 0 of calibrate[1:0] in register 31. Setting bit 1 of calibrate[1:0] starts the automatic calibration of ADC1. Normal ADC operation resumes as soon as the calibration procedure is completed.

The default weights (shown in the table on the right of Figure 4) are computed for an interstage gain of exactly two. If the actual interstage gain is greater than two, the digital value computed for input voltages close to the extreme values may require 17 bits. An overflow monitor is included in the correction logic that detects this condition and sets the output to the minimum or maximum ADC value as appropriate. The overflow monitor can be disabled by setting enable_overflow_mon in register 41 to 0.

It is possible to verify the automatic calibration procedure by using registers 43 – 46 to force the configuration of the pipeline. In this case, the differences and averages described above must be calculated off chip and the W0 and W2 values updated before the calibration of the next most significant pipeline stage is begun. When the calibration procedure is executed in this fashion, the overflow monitor must be disabled by setting enable_overflow_mon in register 41 to 0.

### Data Formatter

The Data Formatter receives data from the two ADC pipelines and formats it for output. Data is output using 8 LVDS pairs. Four pairs are used for data from ADC0 and four pairs are used for data from ADC1. Each pair carries data from one nibble of a 16-bit ADC value as shown in Table 2. Data is output most significant bit first using a "64" MHz clock to match the rate that analog values are presented to the input of the ADC pipelines for digitization. Output data changes value on the rising edge of DIG_CLKOUT and is latched at COLDATA on the falling edge of DIG_CLKOUT. The start of a block of data corresponding to a common sample time is indicated by DIG_FRAME. The channel order is 0 – 7 on outputs A – D and 8 – 15 on outputs E – H. If DIG_FRAME is misplaced, it can be moved in time with respect to the output data using config_start_number[4:0] in register 49 (or page 2, register 1 if I2C_UART_SEL = 0). If necessary, the order in which input channels are presented to the ADC pipelines can also be adjusted using config_SHA0_Pointer[2:0] in register 49 (or page 2, register 4 if I2C_UART_SEL = 0).

| Serial Data Output | ADC Output Nibble |
|---|---|
| DIG_OUT_A | ADC0[3:0] |
| DIG_OUT_B | ADC0[7:4] |
| DIG_OUT_C | ADC0[11:8] |
| DIG_OUT_D | ADC0[15:12] |
| DIG_OUT_E | ADC1[3:0] |
| DIG_OUT_F | ADC1[7:4] |
| DIG_OUT_G | ADC1[11:8] |
| DIG_OUT_H | ADC1[15:12] |

> **Table 2:** Relationship between output data ports and ADC outputs.

### Reference Blocks

COLDADC contains redundant circuit blocks for reference voltage and bias current generation. The control variables bgr_select in register 19 and iref_sel[1:0] in register 28 determine whether the bandgap reference block or the CMOS reference block is used (note that both control variables must be set). The CMOS reference block is designed for use with an internal reference resistor but an external resistor can also be used. It is also possible to override both reference blocks and use a simple PMOS current mirror connected directly to an external resistor. This operating mode will have significantly poorer power supply rejection and is included as part of the CMOS reference block as backup only.

#### Reference Voltages

Four reference voltages are used in COLDADC. VCMI is used as the reference voltage (either in the input buffers or in the SHAs if the input buffers are bypassed) when single ended inputs are being used. It is also used by the SHAs to precharge the output stage of the SHAs while the inputs are being sampled. VCMO defines the "zero" value for the pipeline ADCs. It is the common mode voltage for the output of the differential input buffers and of the SHAs. VREFN and VREFP are the negative and positive rails of the pipeline ADCs. The nominal values for the various reference voltages are summarized in Table 3.

| Reference Name | Value | Units | Description |
|---|---|---|---|
| VREFP | 1.95 | V | ADC positive reference voltage |
| VREFN | 0.45 | V | ADC negative reference voltage |
| VCMI | 0.9 | V | Common-mode input voltage. Used in input buffer and SHA. |
| VCMO | 1.2 | V | ADC Core Common-mode voltage. Also used in SHA. |

> **Table 3:** Nominal reference voltages. Note that VR in Figure 4 is VR = (VREFP-VREN)/2 + VCMO.

The BJT-based reference requires filter capacitors at the output of the reference (before the buffers). The CMOS-based reference does not require filter capacitors. If operation of the ADC with external references is desired, the two reference generators can be powered down and references defined off chip can be introduced into the circuit through dedicated pads prior to the ADC reference buffers. The output of the MUX goes to buffers that drive the ADC reference voltage inputs.

#### Reference Currents

The input buffers require two current sources (both nominally 200 µA). Control bits in register 0 (ibuff_ctrl[3:0]) select which reference block sources the currents and which set of input buffers receives the currents. The current magnitudes are controlled separately depending on the current source.

Each bank of 8 SHAs and each pipeline ADC requires a 50 µA current sink. The voltage reference buffer block is implemented in two sections, one for channels 0 – 7 and one for channels 8 – 15. Each block requires a 250 µA current sink. There are no control bits associated with the current sinks.

The SHA bias circuit uses its 50 µA current sink to produce 8 independent current sources. The magnitude of these current sources are controlled using control bits in registers 4 – 7. The currents for SHA0 and SHA7 share a control variable (sha0_bias[2:0]). Similarly the magnitude of the bias current for SHA1 and SHA8 is controlled by sha7_bias[2:0], and so on. By default all of the SHA bias currents are equal. Since SHA7 can be much slower than SHA0, power can be saved by reducing the current to some of the SHAs.

The ADC bias circuit uses a 50 µA current sink and produces a single bias current for the 14 interstage amplifiers (OP amps) in the pipeline (the least significant pipeline stage does not include an OP amp). The magnitude of the OP amp bias current for both ADC pipelines controlled by adc_bias[2:0] in register 8.

Finally, the voltage reference buffer circuits use a 250 µA current sink and produce current sources for the reference voltage buffer amplifiers. These are controlled by a single control variable, ref_bias[2:0], in register 23.

#### Bandgap Reference

The bandgap reference block uses two diode connected vertical pnp transistors with different current densities to create a reference voltage (VBGR) that depends only weakly on the bias voltage and on temperature. This voltage is used to generate a unit current that is used by digital to analog converters to create programmable reference voltages and currents. The four reference voltages are controlled by variables in registers 10 – 14 and may be set in 8 mV steps.

In addition to the current sources and sinks described above, the bandgap reference block creates two nominally 200 µA current sources that are used by amplifiers in the digital to analog converters that produce the reference voltages. The magnitude of these currents may be adjusted using control variables in registers 17 and 18.

The magnitude of the currents provided to the input buffers may be adjusted using control variables in registers 15 and 16.

#### CMOS Reference

The CMOS reference block depends on a master bias current whose accuracy is expected to be poor relative to the bandgap voltage used by the bandgap reference block. For this reason, trimming bits are included to be used in conjunction with a current monitor output to allow the user to set the master bias current to 50 µA. The trimming bits (vt_ref_trim_ctrl[2:0] in register 28) allow the CMOS reference bias current to be adjusted in steps of 5 µA.

The voltages produced by the CMOS reference block are directly proportional to the bias voltage (VDDA2P5) and are controlled by variables in registers 24 – 27. The four reference voltages may be set in 8.8 mV steps. The currents provided to the input buffers are controlled by variables in registers 29 and 30.

### Control Interface

All COLDADC_P2 control I/O uses CMOS signals and is in the VDDIO domain. The logic levels are 1 = 2.25V and 0 = 0V.

Most of the COLDADC_P2 configuration registers can be read or written using either a custom UART or an I2C-like interface. To use the UART, I2C_UART_SEL (pad a, pin b) must be connected to 2.25V. To use the I2C interface, I2C_UART_SEL must be connected to 0V. The UART interface can be used to read or write all registers in the configuration memory. It cannot access the "page 2" back end control registers. For this reason, if U2C_UART_SEL is connected to 2.25V, the page 2 back end control registers are disabled, and back end functions are controlled by variables in registers 48 – 50.

Both control interfaces use a chip address that is set using wire bond pads I2C_ADD_0 – I2C_ADD_3 (or package pins I2C_ADD<0> – I2C_ADD<3>). As above, 2.25V = 1 and 0V = 0.

#### I2C

The "I2C-like" interface implemented in COLDADC_P2 is similar to classical, single-master I2C with no clock extension. The major difference is motivated by the fact that the DUNE I2C communications must travel over long cables between the WIB and the FEMBs. Consequently, for these signals, canonical I2C signaling is replaced by LVDS. However, LVDS is not amenable to bidirectional communication, so canonical I2C's bidirectional SDA (Serial Data) line is replaced by two data lines, one from Warm to Cold (SDA_w2c) and one from Cold to Warm (SDA_c2w). In order to reduce power dissipation on the FEMBs, CMOS signaling rather than LVDS is used for I2C communication on the FEMB.

Other differences between DUNE I2C and canonical I2C are that DUNE I2C does not include block transfers, and it uses a 3-word protocol rather than a 2-word protocol. DUNE I2C commands are composed of three bytes of information input serially to the chip on I2C_SDA_w2c. Nine clock pulses are issued for each byte. The first 8 pulses are used to shift data either into or out of the ASIC. The I2C interface acknowledges the transmission by raising the I2C_SDA_c2w line on the ninth clock. The rising edges of data on both SDA lines are roughly in time with the rising clock edges. Data should be latched at its destination using the falling edge of the I2C_SCL clock. Bytes are shifted in most significant bit first. The first byte includes the chip address (4 bits), the register page address (3 bits), and a single bit that is set to 0 for a write command and 1 for a read command. The second byte is the 8-bit register address. For a read command, the contents of the addressed register are read out on the I2C_SDA_c2w line during the third byte. For a read command, the contents of the I2C_SDA_w2c line are unimportant during the third byte. For a write command, the third byte is the data to be written and it is presented to the chip on the I2C_SDA_w2c line. The Soft Reset command has the format of a Write to chip address 0, register page 0, register address 6: ([00000000][00000110]). The contents of the third byte are unimportant. The Soft Reset restores all page 2 control registers to their default values. It does not affect the registers in the configuration memory (page 1 registers).

The 64 MHz clock is required for the I2C interface to work; internal state machines run on the 64 MHz clock. The I2C_SCL frequency must be between ~0.5 MHz and 2 MHz. If the chip address does not match the address set by I2C_ADD_0 – I2C_ADD_3, the response on I2C_SDA_c2w will be 0x5A. The figures below illustrate I2C communications.

> **Figure 5:** I2C write format; this example is write(chip 4, page 1); register 9; 0x52. (image not included). Signals: I2C_SCL, I2C_SDA_w2c (byte 1 = 0 1 0 0 0 0 1 0, byte 2 = 0 0 00 10 01, byte 3 = 0 1 01 0 01 0), I2C_SDA_c2w (ACK on each ninth clock).

> **Figure 6:** I2C read format; this example is read(chip 4, page 1); register 9. The response is 0x52. (image not included). Signals: I2C_SCL, I2C_SDA_w2c (byte 1 = 0 1 0 0 0 0 1 1, byte 2 = 0 0 001 0 01), I2C_SDA_c2w (ACKs and response 0 1 01 00 1 0).

In order to simplify the logic used to relay I2C information through COLDATA data concentrator chips on the DUNE FEMBs, a chip addressing convention (shown below) has been established. The I2C interface in COLDADC_P2 will not read or write page 2 registers unless the COLDADC_P2 chip address is 01xx or 10xx. However, the page 1 registers can be written and read using the I2C interface for all possible chip addresses.

| Chip Address | Assignment |
|---|---|
| 0000 – 0001 | Unused |
| 0010 | "Bottom" COLDATA |
| 0011 | "Top" COLDATA |
| 01xx (xx = 00,01,10,11) | COLDADCs attached to COLDATA_BOT |
| 10xx (xx = 00,01,10,11) | COLDADCs attached to COLDATA_TOP |
| 11xx (xx = 00,01,10,11) | Unused |

> **Table 4:** COLDATA I2C chip address convention.

#### UART

COLDADC_P2 includes a simple custom Universal Asynchronous Receiver/Transmitter (UART). The UART uses a single CMOS pin for input (UART_RX) and a single CMOS pin for output (UART_TX). The UART operates with a 22-bit word length, an 8-bit address space and an 8-bit data payload. The UART bits are summarized in Table 5.

| Bit Range | Contents | Comment |
|---|---|---|
| [0] | WRB | 1 to write, 0 to read |
| [4:1] | Chip ID | Shared with I2C bus |
| [12:5] | Data | 8-bit data payload |
| [20:13] | Address | 8-bit address |
| [21] | Parity | 0 if number of 1s in bits [20:0] is odd (odd parity). Ignored for write operations. |

> **Table 5:** UART bit definitions.

When a UART transaction is requested externally (by shifting bits into the UART_RX pin) the first bit in the UART word is the WRB indicator. When WRB is high, a write is being requested and the payload byte will be written to the memory location contained in the address byte. When WRB is low, a read is being requested and the payload byte located in the memory location contained in the address byte will be sent out the UART_TX pin.

The logical interface of the PHY is shown in Figure 7. When idle, the UART_TX output is high. The first bit of a UART transaction is a start bit (always a low bit), and the last is a stop bit (always a high bit). The data bits are sent LSB-first.

> **Figure 7:** UART output word including start and stop bits (image not included). START BIT (low), then 22 data bits sent LSB→MSB, then STOP BIT (high).

The UART is internally oversampled by a factor of 16 to guard against triggering of a transaction by noise on the UART_RX pin. The timing diagram for the UART is shown in Figure 8. The UART is clocked with the ADC input clock (which is generated internal to the Cold ADC). Therefore, UART data should be sent to Cold ADC at approximately 1 MHz (assuming a 64 MHz master chip clock). The output data on UART_TX is clocked using the internal 16 MHz clock. This means the transmit frequency will be slightly less than 1 MHz if the 64 MHz clock is actually 62.5 MHz as planned.

> **Figure 8:** UART timing diagram (image not included). Rx UART input shows Start bit, Bit 0, Bit 1, Bit 2; ADC Clock (16 MHz nominal) provides 16X oversampling.

### Power On Reset

The power on reset circuit is intended to initialize all control variables to their default values. The POR_NAND input will disable the power on reset circuit if tied to 0V. An analog pad (POR_SF) is included for debugging purposes. The power on reset circuit will not operate properly if the rise time of VDDA2P5 is longer than ~1 msec.

### Process Monitor

COLDADC_P2 contains a process monitor that is intended to help characterize the process variations associated with different wafers and different fabrication lots. The process monitor is a ring oscillator comprising a chain of 40 inverters and one NAND gate followed by a divide-by-32 stage (to reduce the frequency that must be driven off-chip). The ring oscillator is powered by VDDD1P2 and enabled by enable_ringosc in register 42. By default, the ring oscillator is off. Table 6 shows the expected oscillation frequency as a function of process corner and temperature. The expected current consumption is shown in Table 7.

| Process Corner | -200 C | 27 C |
|---|---|---|
| Slow-Slow | 18.4 MHz | 16.1 MHz |
| Typical-Typical | 24.2 MHz | 18.9 MHz |
| Fast-Fast | 34.9 MHz | 22.5 MHz |

> **Table 6:** Oscillation Frequency

| | -200 C | 27 C |
|---|---|---|
| Average | 397 µA | 325 µA |
| Peak | 982 µA | 650 µA |

> **Table 7:** Average and peak current drawn by ring oscillator.

## Wire Bonding Pad and Package Pin List

The COLDADC_P2 die size is 6860 microns by 7610 microns. There are 178 wire bond pads, 47 on the left and right sides (inputs from LArASIC and ADC outputs), and 42 on the top and bottom. The low profile quad flat package has 128 pins, 32 on each side, and a back-side contact. The LQFP package is 14 mm by 14 mm and 1.6 mm high. Figure 9 shows the wire bonding pad numbering. Table 8 lists the package pin numbers as well as the pad numbers.

> **Figure 9:** COLDADC_P2 wire bonding pad frame (image not included). Pad numbering runs 1–178 around the die. Left side (pads 1–47): INP[15], INN[15], VSSA2P5, INP[14], INN[14], VSSA2P5 ... down through INP[0], INN[0] (pads at index 1, 10, 20, 30, 40, 50 marked). Bottom edge (pads ~48–84): VDDA2P5/VSSA2P5 power groups, then AUX_ISINK, AUX_VOLTAGE, AUX_ISOURCE, VREF_EXT, VREF_DECOUPLE, RBIAS_CMOS, VREFP, VREFN, VCMI, VCMO, VSSA2P5, ADC_TEST_IN_P, ADC_TEST_IN_N, VSSA2P5, VOLTAGE_MONITOR, CURRENT_MONITOR (indices 60, 70, 80 marked). Right side (down from pad 170 at top toward 90): DIGITAL_MUX_OUT_P/N, VDDIO/VSSIO, VSSA2P5, CLK_64MHZ_P/N, VSSA2P5, CLK_2MHZ_P/N, VDDIO, VSSIO, DIG_CLKOUT_P/N, VSSA2P5, DIG_FRAME_P/N, VSSA2P5, DIG_OUTA..DIG_OUTH P/N pairs each separated by VSSA2P5, VDDIO, VSSIO (indices 130, 120, 110, 100, 90 marked). Top edge: MASTER_RESET, UART_TX, UART_RX, I2C_UART_SEL, I2C_SDA_C2W, I2C_SDA_W2C, I2C_SCL, I2C_ADD_0..3, RO_OUT, CHIP_ACTIVE, VSSA2P5, POR_SF, POR_NAND. Note: there is a gap between pads 152 & 153; this feature can be used to orient the bare die.

| Pad # | Pad Name | Pin # | Pin Name | Comment |
|---|---|---|---|---|
| 1 | INP[15] | 1 | INP<15> | |
| 2 | INN[15] | 2 | INN<15> | |
| 3 | VSSA2P5 | | VSSESD | Down bond |
| 4 | INP[14] | 3 | INP<14> | |
| 5 | INN[14] | 4 | INN<14> | |
| 6 | VSSA2P5 | | VSSESD | Down bond |
| 7 | INP[13] | 5 | INP<13> | |
| 8 | INN[13] | 6 | INN<13> | |
| 9 | VSSA2P5 | | VSSESD | Down bond |
| 10 | INP[12] | 7 | INP<12> | |
| 11 | INN[12] | 8 | INN<12> | |
| 12 | VSSA2P5 | | VSSESD | Down bond |
| 13 | INP[11] | 9 | INP<11> | |
| 14 | INN[11] | 10 | INN<11> | |
| 15 | VSSA2P5 | | VSSESD | Down bond |
| 16 | INP[10] | 11 | INP<10> | |
| 17 | INN[10] | 12 | INN<10> | |
| 18 | VSSA2P5 | | VSSESD | Down bond |
| 19 | INP[9] | 13 | INP<9> | |
| 20 | INN[9] | 14 | INN<9> | |
| 21 | VSSA2P5 | | VDDESD | Down bond |
| 22 | INP[8] | 15 | INP<8> | |
| 23 | INN[7] | 16 | INN<8> | |
| 24 | VSSA2P5 | | VSSESD | Down bond |
| 25 | INP[7] | 17 | INP<7> | |
| 26 | INN[7] | 18 | INN<7> | |
| 27 | VSSA2P5 | | VSSESD | Down bond |
| 28 | INP[6] | 19 | INP<6> | |
| 29 | INN[6] | 20 | INN<6> | |
| 30 | VSSA2P5 | | VSSESD | Down bond |
| 31 | INP[5] | 21 | INP<5> | |
| 32 | INN[5] | 22 | INN<5> | |
| 33 | VSSA2P5 | | VSSESD | Down bond |
| 34 | INP[4] | 23 | INP<4> | |
| 35 | INN[4] | 24 | INN<4> | |
| 36 | VSSA2P5 | | VSSESD | Down bond |
| 37 | INP[3] | 25 | INP<3> | |
| 38 | INN[3] | 26 | INN<3> | |
| 39 | VSSA2P5 | | VSSESD | Down bond |
| 40 | INP[2] | 27 | INP<2> | |
| 41 | INN[2] | 28 | INN<2> | |
| 42 | VSSA2P5 | | VSSESD | Down bond |
| 43 | INP[1] | 29 | INP<1> | |
| 44 | INN[1] | 30 | INN<1> | |
| 45 | VSSA2P5 | | VSSESD | Down bond |
| 46 | INP[0] | 31 | INP<0> | |
| 47 | INN[0] | 32 | INN<0> | |
| 48 | VDDA2P5 | 33 | VDDA2P5 | |
| 49 | VSSA2P5 | 34 | VSSA2P5 | |
| 50 | VDDA2P5 | 35 | VDDA2P5 | |
| 51 | VDDA2P5 | | VDDA2P5 | Double bond to #35 |
| 52 | VSSA2P5 | 36 | VSSA2P5 | |
| 53 | VSSA2P5 | | VSSA2P5 | Double bond to #36 |
| 54 | VDDA2P5 | 37 | VDDA2P5 | |
| 55 | VDDA2P5 | | VDDA2P5 | Double bond to #37 |
| 56 | VSSA2P5 | 38 | VSSA2P5 | |
| 57 | VSSA2P5 | | VSSA2P5 | Double bond to #38 |
| 58 | VDDD2P5 | 39 | VDDD2P5 | |
| 59 | VSSD2P5 | 40 | VSSD2P5 | |
| 60 | VDDD2P5 | 41 | VDDD2P5 | |
| 61 | VDDD2P5 | | VDDD2P5 | Double bond to #41 |
| 62 | VSSD2P5 | 42 | VSSD2P5 | |
| 63 | VSSD2P5 | | VSSD2P5 | Double bond to #42 |
| 64 | VSSA2P5 | 43 | VSSA2P5 | |
| 65 | VDDA2P5 | 44 | VDDA2P5 | |
| 66 | VDDA2P5 | | VDDA2P5 | Double bond to #44 |
| 67 | VSSA2P5 | 45 | VSSA2P5 | |
| 68 | VSSA2P5 | | VSSA2P5 | Double bond to #45 |
| 69 | AUX_ISINK | 46 | AUX_ISINK | Also called aux 2 |
| 70 | AUX_VOLTAGE | 47 | AUX_VOLTAGE | Also called aux 1 |
| 71 | AUX_ISOURCE | 48 | AUX_ISOURCE | Also called aux 3 |
| 72 | VREF_EXT | 49 | VREF_EXT | |
| 73 | VREF_DECOUPLE | 50 | VREF_DECOUPLE | |
| 74 | RBIAS_CMOS | 51 | RBIAS_CMOS | |
| 75 | VREFP | 52 | VREFP | |
| 76 | VREFN | 53 | VREFN | |
| 77 | VCMI | 54 | VCMI | |
| 78 | VCMO | 55 | VCMO | |
| 79 | VSSA2P5 | 56 | VSSA2P5 | |
| 80 | ADC_TEST_IN_P | 57 | ADC_TEST_IN_P | |
| 81 | ADC_TEST_IN_N | 58 | ADC_TEST_IN_N | |
| 82 | VSSA2P5 | 59 | VSSA2P5 | |
| 83 | VOLTAGE_MONITOR | 60 | VOLTAGE_MONITOR | |
| 84 | CURRENT_MONITOR | 61 | CURRENT_MONITOR | |
| 85 | unconnected | | no name | |
| 86 | VSSA2P5 | 62 | VSSESD | |
| 87 | VSSA2P5 | | VSSESD | Double bond to #62 |
| 88 | VDDD1P2 | 63 | VDDD1P2 | |
| 89 | VSSD1P2 | 64 | VSSD1P2 | |
| 90 | VSSIO | 65 | VSSIO | |
| 91 | VDDIO | 66 | VDDIO | |
| 92 | DIG_OUTH_N | 67 | DIG_OUTH_N | |
| 93 | DIG_OUTH_P | 68 | DIG_OUTH_P | |
| 94 | VSSA2P5 | | VSSESD | Down bond |
| 95 | DIG_OUTG_N | 69 | DIG_OUTG_N | |
| 96 | DIG_OUTG_P | 70 | DIG_OUTG_P | |
| 97 | VSSA2P5 | | VSSESD | Down bond |
| 98 | DIG_OUTF_N | 71 | DIG_OUTF_N | |
| 99 | DIG_OUTF_P | 72 | DIG_OUTF_P | |
| 100 | VSSA2P5 | | VSSESD | Down bond |
| 101 | DIG_OUTE_N | 73 | DIG_OUTE_N | |
| 102 | DIG_OUTE_P | 74 | DIG_OUTE_P | |
| 103 | VSSA2P5 | | VSSESD | Down bond |
| 104 | DIG_OUTD_N | 75 | DIG_OUTD_N | |
| 105 | DIG_OUTD_P | 76 | DIG_OUTD_P | |
| 106 | VSSA2P5 | | VSSESD | Down bond |
| 107 | DIG_OUTC_N | 77 | DIG_OUTC_N | |
| 108 | DIG_OUTC_P | 78 | DIG_OUTC_P | |
| 109 | VSSA2P5 | | VSSESD | Down bond |
| 110 | DIG_OUTB_N | 79 | DIG_OUTB_N | |
| 111 | DIG_OUTB_P | 80 | DIG_OUTB_P | |
| 112 | VSSA2P5 | | VSSESD | Down bond |
| 113 | DIG_OUTA_N | 81 | DIG_OUTA_N | |
| 114 | DIG_OUTA_P | 82 | DIG_OUTA_P | |
| 115 | VSSA2P5 | | VSSESD | Down bond |
| 116 | DIG_FRAME_N | 83 | DIG_FRAME_N | |
| 117 | DIG_FRAME_P | 84 | DIG_FRAME_P | |
| 118 | VSSA2P5 | | VSSESD | Down bond |
| 119 | DIG_CLKOUT_N | 85 | DIG_CLKOUT_N | |
| 120 | DIG_CLKOUT_P | 86 | DIG_CLKOUT_P | |
| 121 | VSSIO | 87 | VSSIO | |
| 122 | VDDIO | 88 | VDDIO | |
| 123 | CLK_2MHZ_N | 89 | CLK_2MHZ_N | |
| 124 | CLK_2MHZ_P | 90 | CLK_2MHZ_P | |
| 125 | VSSA2P5 | | VSSESD | Down bond |
| 126 | CLK_64MHZ_N | 91 | CLK_64MHZ_N | |
| 127 | CLK_64MHZ_P | 92 | CLK_64MHZ_P | |
| 128 | VSSA2P5 | | VSSESD | Down bond |
| 129 | VSSIO | 93 | VSSIO | |
| 130 | VSSIO | 94 | VSSIO | |
| 131 | VSSIO | | VSSIO | Double bond to #94 |
| 132 | VDDIO | | VDDIO | Double bond to #95 |
| 133 | VDDIO | 95 | VDDIO | |
| 134 | VDDIO | 96 | VDDIO | |
| 135 | DIGITAL_MUX_OUT_N | | | not connected to pin |
| 136 | DIGITAL_MUX_OUT_P | | | not connected to pin |
| 137 | POR_NAND | 97 | POR_NAND | |
| 138 | POR_SF | | | not connected to pin |
| 139 | VSSA2P5 | | VSSESD | Down bond |
| 140 | CHIP_ACTIVE | 98 | CHIP_ACTIVE | |
| 141 | RO_OUT | 99 | RO_OUT | Ring Oscillator Out |
| 142 | I2C_ADD_3 | 100 | I2C_ADD<3> | |
| 143 | I2C_ADD_2 | 101 | I2C_ADD<2> | |
| 144 | I2C_ADD_1 | 102 | I2C_ADD<1> | |
| 145 | I2C_ADD_0 | 103 | I2C_ADD<0> | |
| 146 | I2C_SCL | 104 | I2C_SCL | |
| 147 | I2C_SDA_W2C | 105 | I2C_SDA_W2C | |
| 148 | I2C_SDA_C2W | 106 | I2C_SDA_C2W | |
| 149 | I2C_UART_SEL | 107 | I2C_UART_SEL | Pull High to use UART |
| 150 | UART_RX | 108 | UART_RX | |
| 151 | UART_TX | 109 | UART_TX | |
| 152 | MASTER_RESET | 110 | MASTER_RESET | Resets Config Memory |
| 153 | VSSA2P5 | 111 | VSSESD | |
| 154 | VSSD1P2 | 112 | VSSD1P2 | |
| 155 | VDDD1P2 | 113 | VDDD1P2 | |
| 156 | VSSD1P2 | 114 | VSSD1P2 | |
| 157 | VSSD1P2 | | VSSD1P2 | Double bond to #114 |
| 158 | VDDD1P2 | 115 | VDDD1P2 | |
| 159 | VDDD1P2 | | VDDD1P2 | Double bond to #115 |
| 160 | VSSD1P2 | 116 | VSSD1P2 | |
| 161 | VDDD1P2 | 117 | VDDD1P2 | |
| 162 | VSSA2P5 | 118 | VSSESD | |
| 163 | VSSD2P5 | 119 | VSSD2P5 | |
| 164 | VSSD2P5 | | VSSD2P5 | Double bond to #119 |
| 165 | VDDD2P5 | 120 | VDDD2P5 | |
| 166 | VDDD2P5 | | VDDD2P5 | Double bond to #120 |
| 167 | VSSD2P5 | 121 | VSSD2P5 | |
| 168 | VDDD2P5 | 122 | VDDD2P5 | |
| 169 | VSSA2P5 | 123 | VSSA2P5 | |
| 170 | VSSA2P5 | | VSSESD | Double bond to #123 |
| 171 | VDDA2P5 | 124 | VDDA2P5 | |
| 172 | VDDA2P5 | | VDDA2P5 | Double bond to #124 |
| 173 | VSSA2P5 | 125 | VSSA2P5 | |
| 174 | VSSA2P5 | | VSSESD | Double bond to #125 |
| 175 | VDDA2P5 | 126 | VDDA2P5 | |
| 176 | VDDA2P5 | | VDDA2P5 | Double bond to #126 |
| 177 | VSSA2P5 | 127 | VSSA2P5 | |
| 178 | VDDA2P5 | 128 | VDDA2P5 | |

> **Table 8:** Wirebond Pad and Package Pin List

Note: The first COLDADC_P2 chips packaged (by ASE with labels including "DUNE") had pads 170, 172, 174, and 176 unbonded. The parts from the first 4 wafers of the engineering run were packaged by Greatek (GTK) and will be labeled simply "COLDADC" (without serial numbers). These parts have pads 170, 172, 174, and 176 bonded as indicated above.

## Configuration Memory

The configuration memory holds the pipeline stage weights (W0 and W2) and a number of control registers (the "page 1 registers"). The control registers are 8-bit registers while the pipeline stage weights (and pipeline gains and offsets) are 16-bit numbers. The memory is accessed one byte at a time. 16-bit numbers are stored in two consecutive memory locations, with low order 8 bits in an address that is one less than the high order 8 bits. A block diagram of the configuration memory is shown in Figure 10. The configuration memory can be accessed using either the UART or the I2C interface. If the I2C interface is used, the page number needs to be set = 1.

> **Figure 10:** Configuration Memory (image not included). CONFIGURATION INTERFACE connects to a Cold ADC External Interface (Slow I/O). Three register files: REGISTER FILE ADC0 (w0[0:15], w2[0:15]), REGISTER FILE ADC1 (w0[0:15], w2[0:15]), and REGISTER FILE CONFIG (Config bits, 128 8-bit registers).

The memory map for the configuration memory is shown in Table 9.

| Address Range (Hexadecimal) | Contents | Notes |
|---|---|---|
| FF-80 | Configuration Bits | See section on configuration settings. |
| 7F-7E | ADC1 Offset | |
| 7D-60 | ADC1, W2 | |
| 5F-5E | ADC1 Gain | |
| 5D-40 | ADC1, W0 | |
| 3F-3E | ADC0 Offset | |
| 3D-20 | ADC0, W2 | |
| 1F-1E | ADC0, Gain | |
| 1D-00 | ADC0, W0 | |

> **Table 9:** Configuration Memory Map

With this memory map, the address of a particular element can be assembled using the table below.

| Bit | [7] | [6] | [5] | [4:1] | [0] |
|---|---|---|---|---|---|
| Contents | config flag | which ADC | which weight | stage address | which byte |
| | 0 = Weights | 0 = ADC0 | 0 = W0 | 0 = Most significant | 0 = least significant byte |
| | 1 = Control registers | 1 = ADC1 | 1 = W1 | | |

> **Table 10:** Configuration Memory Address

The stage weights are 16-bit numbers and hence each occupies two memory locations. The memory address for a stage weight can be constructed by setting bit 7 = 0, bit 6 = 0 for ADC0 or 1 for ADC1, bit 5 = 0 for W0 or 1 for W1, bits [4:1] = pipeline stage number (0000 for the first pipeline stage and 1111 for the last pipeline stage), and bit 0 = 0 for the least significant byte or 1 for the most significant byte. The control registers can be addressed by setting bit 7 = 1 and bits [6:0] = the register number. That is, the address of each control register is the register number + 128.

The default stage weights are given in Table 11.

| ADC Stage | W0 | W2 | ADC Stage | W0 | W2 |
|---|---|---|---|---|---|
| 0 | 0xC000 | 0x4000 | 7 | 0xFF80 | 0x0080 |
| 1 | 0xE000 | 0x2000 | 8 | 0xFFC0 | 0x0040 |
| 2 | 0xF000 | 0x1000 | 9 | 0xFFE0 | 0x0020 |
| 3 | 0xF800 | 0x0800 | 10 | 0xFFF0 | 0x0010 |
| 4 | 0xFC00 | 0x0400 | 11 | 0xFFF8 | 0x0008 |
| 5 | 0xFE00 | 0x0200 | 12 | 0xFFFC | 0x0004 |
| 6 | 0xFF00 | 0x0100 | 13 | 0xFFFE | 0x0002 |
| | | | 14 | 0xFFFF | 0x0001 |

> **Table 11:** Default ADC pipeline stage weights.

## Page 1 Control Registers

### Input Buffer Configuration

**Register 0 (0x80) — Default = 0xA3**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ibuff_sdc_pd | 0 → Power up single-to-differential converter in the input buffer; 1 → Power down and bypass of single-to-differential converter in the Input Buffer. | [0] | 0b1 |
| ibuff_diff_pd | 0 → Power up differential buffer; 1 → Power down and bypass of differential buffer in the Input buffer. Note: When powering down both single ended and differential input buffers, it is necessary to turn all ibuff bias currents down to minimum value. | [1] | 0b1 |
| ibuff_ctrl[3:0] | Control of current multiplexer. BJT or CMOS reference. Directs current to SDC or DB: ibuff_ctrl[0] = 1 directs current from Bandgap Reference to input buffers; ibuff_ctrl[1] = 1 directs current from CMOS Reference to input buffers; ibuff_ctrl[2] = 1 directs currents to single ended input buffers (SDC); ibuff_ctrl[3] = 1 directs currents to differential input buffers (DB). | [7:4] | 0xA |

Care should be taken not to power up both the single-to-differential converter and the differential buffers. In the case when both the single-to-differential converter and the differential buffer are bypassed care must be taken to set the configuration bit sha_se_input (in register 4) high if the input to Cold ADC is single-ended (and a conversion to differential in the SHA is desired).

### Sample and Hold (SHA) Amplifier Configuration

**Register 1 (0x81) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| freeze_sha[1:0] | 0 → normal operation; 1 → freezes SHA output multiplexer. Bit 0 corresponds to ADC0 and bit 1 corresponds to ADC1 | [1:0] | 0x0 |
| freeze_select0[2:0] | Selects which SHA is connected to ADC0 when frozen. 000 = SHA0, 001 = SHA1, etc. | [4:2] | 0x0 |
| freeze_select1[2:0] | Selects which SHA is connected to ADC1 when frozen. 000 = SHA0 (channel 8), 001 = SHA1 (channel 9), etc. | [7:5] | 0x0 |

**Register 2 (0x82) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha_pd_0 | Power down SHAs associated with ADC0. 0 → normal operation; Any other value → power down SHAs | [0] | 0x0 |

**Register 3 (0x83) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha_pd_1 | Power down SHAs associated with ADC1. 0 → normal operation; Any other value → power down SHAs | [0] | 0x0 |

**Register 4 (0x84) — Default = 0x33**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha0_bias | Bias adjustment for SHA0. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [2:0] | 0x3 |
| sha_se_input | 0 → SHA input is treated as fully differential; 1 → SHA input is treated as single-ended | [3] | 0x0 |
| sha1_bias | Bias adjustment for SHA1. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [6:4] | 0x3 |

**Register 5 (0x85) — Default = 0x33**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha2_bias | Bias adjustment for SHA2. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [2:0] | 0x3 |
| sha3_bias | Bias adjustment for SHA3. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [6:4] | 0x3 |

**Register 6 (0x86) — Default = 0x33**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha4_bias | Bias adjustment for SHA4. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [2:0] | 0x3 |
| sha5_bias | Bias adjustment for SHA5. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [6:4] | 0x3 |

**Register 7 (0x87) — Default = 0x33**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| sha6_bias | Bias adjustment for SHA6. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [2:0] | 0x3 |
| sha7_bias | Bias adjustment for SHA7. SHA bias current is nominally 80 µA – 10 µA *sha0_bias[2:0] | [6:4] | 0x3 |
| sha_early_clks | Enables clocks that rise one 64 MHz clock cycle early | [7] | 0x0 |

When the SHA is frozen, the ADC will oversample the SHA output by a factor of 8. This may be useful in some applications. Note that each SHA has an independent bias adjustment word (both SHAs corresponding to a different ADC share this word). Independent control may be useful to optimize power consumption since each SHA has different settling requirements.

### Pipeline ADC Configuration

**Register 8 (0x88) — Default = 0x0B**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| adc_bias[2:0] | Bias adjustment for OP Amp diff pair. Nominal for warm is 011, nominal for cold is 101. Cheng-Ju used 011 for all temps. ADC bias current is nominally 80 µA – 10 µA *adc_bias[2:0]. | [2:0] | 0b011 |
| nonov_ctrl[1:0] | Allows adjustment of non-overlap time of ADC clocks. Use to adjust timing across temperature. | [4:3] | 0b01 |
| edge_select | Chooses edge of master clock to re-time data. 0 → nominal edge; 1 → 180 out of phase in case of gross clock skew errors | [5] | 0 |

**Register 9 (0x89) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| adc_pd[1:0] | 0 → normal operation; 1 → power down ADC. bit [0] corresponds to ADC0 and bit [1] corresponds to ADC1. When powering down an ADC, be sure to power down all corresponding SHAs (e.g. if you set adc_pd[0] to 1, also set sha_pd_0 to 0xFF) | [1:0] | 0b00 |
| adc_disable_gb | 0 → normal operation; 1 → Gain boosting amplifiers in the ADC MDACs disabled (powered down with Hi-Z output) | [2] | 0 |
| adc_output_format | Chooses format of ADC output codes. 0 → two's complement; 1 → offset binary | [3] | 0 |
| adc_sync_mode | 0 → normal operation; 1 → send out known analog pattern for synchronization. The pattern is from SHA0 through SHA7: (VREF, VCMO, -VREF, VCMO, VCMO, VCMO, VCMO, VCMO) | [4] | 0 |
| adc_test_mode | 0 → normal operation (ADC input is SHA output); 1 → ADC converts signal applied to ADC_TEST_INPUT_{P/N} pads (SHA is bypassed) | [5] | 0 |
| adc_output_select | Selects what ADC output is sent off-chip. This can be useful in evaluating the performance of the calibration. 00 or 11 → calibrated ADC data; 01 → uncalibrated ADC data; 10 → raw ADC0 decisions; 11 → raw ADC1 decisions | [7:6] | 0 |

### Bandgap Reference Configuration

**Register 10 (0x8A) — Default = 0xF1**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vrefp_ctrl[7:0] | Settings to generate VREFP. vrefp = 1.87 + (ioffset - idac)*40k where idac = 0.2 µA * (257 - vrefp_ctrl). Default VREFP is 1.95 V. | [7:0] | 0xF1 |

**Register 11 (0x8B) — Default = 0x29**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vrefn_ctrl[7:0] | Settings to generate VREFN. vrefn = 1.87 + (ioffset - idac)*40k where idac = 0.2 µA * (257 - vrefn_ctrl). Default VREFN is 0.45 V. | [7:0] | 0x29 |

**Register 12 (0x8C) — Default = 0x8D**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vcmo_ctrl[7:0] | Settings to generate VCMO. vcmo = 1.87 + (ioffset - idac)*40k where idac = 0.2 µA * (257 - vcmo_ctrl). Default VCMO is 1.2 V. | [7:0] | 0x8D |

**Register 13 (0x8D) — Default = 0x65**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vcmi_ctrl[7:0] | Settings to generate VCMI. vcmi = 1.87 + (ioffset - idac)*40k where idac = 0.2 µA * (257 - vcmi_ctrl). Default VCMI is 0.9 V. | [7:0] | 0x65 |

**Register 14 (0x8E) — Default = 0x55**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vrefp_offset[1:0] | Adjusts ioffset for VREFP DAC. ioffset = 0 → 9.5 pA, 1 → 6.3 µA, 2 → 9.5 µA, 3 → 12.6 µA | [1:0] | 0b01 |
| vrefn_offset[1:0] | Adjusts ioffset for VREFN DAC. ioffset = 0 → 9.5 pA, 1 → 6.3 µA, 2 → 9.5 µA, 3 → 12.6 µA | [3:2] | 0b01 |
| vcmo_offset[1:0] | Adjusts ioffset for VCMO DAC. ioffset = 0 → 9.5 pA, 1 → 6.3 µA, 2 → 9.5 µA, 3 → 12.6 µA | [5:4] | 0b01 |
| vcmi_offset[1:0] | Adjusts ioffset for VCMI DAC. ioffset = 0 → 9.5 pA, 1 → 6.3 µA, 2 → 9.5 µA, 3 → 12.6 µA | [7:6] | 0b01 |

**Register 15 (0x8F) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ibuff0_ctrl[7:0] | 200 µA nominal current source for input buffer. Current is 2 µA (257 – i_buff0_ctrl). | [7:0] | 0xFF |

**Register 16 (0x90) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ibuff1_ctrl[7:0] | 200 µA nominal current source for input buffer. Current is 2 µA (257 – i_buff0_ctrl). | [7:0] | 0xFF |

**Register 17 (0x91) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| i_vdac_0_ctrl[7:0] | 200 µA nominal current source for VDAC. Current is 2 µA (257 – i_vdac_0_ctrl). | [7:0] | 0xFF |

**Register 18 (0x92) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| i_vdac_1_ctrl[7:0] | 200 µA nominal current source for VDAC. Current is 2 µA (257 – i_vdac_1_ctrl). | [7:0] | 0xFF |

**Register 19 (0x93) — Default = 0x04**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| external_reference | 0 → internal references used; 1 → external references used | [0] | 0 |
| external_bgr | 0 → internal bandgap reference used; 1 → external bandgap reference used | [1] | 0 |
| bgr_select | Selects which circuit is internal voltage references. 0 → BJT-based reference; 1 → CMOS-based reference | [2] | 1 |

**Register 20 (0x94) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ref_monitor[7:0] | Low byte for reference monitor block control. Each control bit is active high. bit[0] → VREF (250 mV) on aux1; bit[1] → VREFN_BJT_EXT on aux1; bit[2] → VREFP_BJT_EXT on aux1; bit[3] → VCMI_BJT_EXT on aux1; bit[4] → VCMO_BJT_EXT on aux1; bit[5] → Isource_vdac0 on aux3; bit[6] → Isource_vdac1 on aux3; bit[7] → Isource_ibuff0 on aux3 | [7:0] | 0x00 |

**Register 21 (0x95) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ref_monitor[15:8] | High byte for reference monitor block control. Each control bit is active high. Byte is pre-decoded so each bit corresponds to a different control. It is the user's responsibility to ensure only one bit for each aux pad is high at a time. bit[8] → Isource_ibuff1 on aux3; bit[9] → Isink_adc1 (50 µA) on aux2; bit[10] → Isink_adc0 (50 µA) on aux2; bit[11] → Isink_sha1 (50 µA) on aux2; bit[12] → Isink_sha0 (50 µA) on aux2; bit[13] → Isink_refbuffers_0 (250 µA) on aux2; bit[14] → Isink_refbuffers_1 (250 µA) on aux2; bit[15] → VBGR (1.2 V) on aux1 | [7:0] | 0x00 |

**Register 22 (0x96) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ref_powerdown[7:0] | Power down low byte for reference blocks. 0 → normal operation; 1 → power down. bit[0] → vref_bjt_ext; bit[1] → vrefn_bjt_ext; bit[2] → vrefp_bjt_ext; bit[3] → vcmi_bjt_ext; bit[4] → vcmo_bjt_ext; bit[5] → ibias_200u_source_bjt_ibuff1; bit[6] → ibias_200u_source_bjt_ibuff0; bit[7] → ibias_200u_source_bjt_vdac1 | [7:0] | 0xFF |

**Register 23 (0x97) — Default = 0x2F**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ref_powerdown[11:8] | Power down high nibble for reference blocks. 0 → normal operation; 1 → power down. bit[8] → ibias_200u_source_bjt_vdac0; bit[9] → all adc + sha bjt currents; bit[10] → both refbuffer_bjt currents; bit[11] → singled-ended amp bias (internal to BJT-based bias block) | [3:0] | 0xF |
| ref_bias[2:0] | Bias adjustment for ADC reference buffers. Bias current is nominally 400 µA – 50 µA *ref_bias[2:0]. Note: ref_bias controls the magnitude of the current used by the ADC reference buffers independent of whether the Bandgap reference block or the CMOS reference block is being used. | [6:4] | 0b010 |

### CMOS Reference Configuration

**Register 24 (0x98) — Default = 0xDF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vrefp_ctrl_cmos[7:0] | Setting for VREFP (in case CMOS reference is desired). Output is (ctrl /255) *VDDA2P5 V. Active if bgr_select = 1. Set to 0 if unused. | [7:0] | 0xDF |

**Register 25 (0x99) — Default = 0x33**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vrefn_ctrl_cmos[7:0] | Setting for VREFN (in case CMOS reference is desired). Output is (ctrl /255) * VDDA2P5 V. Active if bgr_select = 1. Set to 0 if unused. | [7:0] | 0x33 |

**Register 26 (0x9A) — Default = 0x89**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vcmo_ctrl_cmos[7:0] | Setting for VCMO (in case CMOS reference is desired). Output is (ctrl /255) * VDDA2P5 V. Active if bgr_select = 1. Set to 0 if unused. | [7:0] | 0x89 |

**Register 27 (0x9B) — Default = 0x67**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vcmi_ctrl_cmos[7:0] | Setting for VCMI (in case CMOS reference is desired). Output is (ctrl /255) * VDDA2P5 V. Active if bgr_select = 1. Set to 0 if unused. | [7:0] | 0x67 |

**Register 28 (0x9C) — Default = 0x15**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| iref_sel[1:0] | Choose where chip bias currents generated by the CMOS reference generator come from. 00 → Turn off bias current (bias currents come from BJT-based reference in this case); 01 → CMOS reference with internal R; 10 → CMOS reference with external R; 11 → plan B reference (external R directly connected to PMOS current source) | [1:0] | 0b01 |
| vt_iref_trim_ctrl[2:0] | Trim for vt-referenced currents. Nominally the vt-reference current will be 70µA - 5 µA * vt_iref_trim_ctrl[2:0], although the constant term will vary a lot with process shifts. Control is active low. | [4:2] | 0b101 |
| vt_kickstart | Forces CMOS reference away from zero-current state. To kickstart the CMOS reference, set vt_kickstart → 1 and then immediately return it to vt_kickstart → 0. Hopefully you will never have to do this. | [5] | 0 |

**Register 29 (0x9D) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ibuff0_cmos[5:0] | Bias current setting for nominal 200 µA source for the input buffers. Current is 512 µA - ibuff0_cmos<5:0>*8 µA. | [5:0] | 0xFF |

**Register 30 (0x9E) — Default = 0xFF**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| ibuff1_cmos[5:0] | Bias current setting for nominal 200 µA source for the input buffers. Current is 512 µA - ibuff1_cmos<5:0>*8 µA. | [5:0] | 0xFF |

### Calibration Engine Configuration

**Register 31 (0x9F) — Default = 0x0**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| calibrate[1:0] | Triggers calibration. Must return to 0 before another calibration can be started. 0 → normal operation; 1 → Initiate calibration sequence. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [1:0] | 0b00 |
| load_cal_defaults | Restores calibration weights to default state. 0 → normal operation; 1 → zero weights. Default weights are loaded when load_cal_defaults is set back to 0. | [2] | 0 |
| load_config_defaults | Restores ADC configuration to default state. Configuration will only respond to write commands when bit = 0. 0 → normal operation; 1 → restore configuration settings to default | [3] | 0 |

**Register 32 (0xA0) — Default = 0x7F**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| meas_cycles[3:0] | Number of ADC samples taken for each measurement. Number of samples is 2^(meas_cycles) so the maximum setting is 2^15. | [3:0] | 0xF |
| (unused) | Bits [6:4] are unused (were originally cal_stages[2:0]) | [6:4] | 0b111 |
| test_correction_logic | Puts correction logic into test mode. Test data is stored in configuration registers 33 through 40. 0 → normal operation; 1 → set test data through correction logic. The test uses a 30-bit decision vector, with one {MSB,LSB} pair per stage. In test word, Bit[14] corresponds to stage 0, bit [0] corresponds to stage 14. Bit[15] is ignored. The test data is included in configuration registers | [7] | 0 |

**Register 33 (0xA1) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_lsb0[7:0] | LSBs (low byte) for correction logic test word, ADC0. | [7:0] | 0 |

**Register 34 (0xA2) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_lsb0[14:8] | LSBs (high byte) for correction logic test word, ADC0. | [6:0] | 0 |

**Register 35 (0xA3) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_msb0[7:0] | MSBs (low byte) for correction logic test word, ADC0. | [7:0] | 0 |

**Register 36 (0xA4) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_msb0[14:8] | MSBs (high byte) for correction logic test word, ADC0. | [6:0] | 0 |

**Register 37 (0xA5) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_lsb1[7:0] | LSBs (low byte) for correction logic test word, ADC1. | [7:0] | 0 |

**Register 38 (0xA6) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_lsb1[14:8] | LSBs (high byte) for correction logic test word, ADC1. | [6:0] | 0 |

**Register 39 (0xA7) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_msb1[7:0] | MSBs (low byte) for correction logic test word, ADC1. | [7:0] | 0 |

**Register 40 (0xA8) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| test_msb1[14:8] | MSBs (high byte) for correction logic test word, ADC1. | [6:0] | 0 |

### Overflow Logic Configuration

**Register 41 (0xA9) — Default = 0x01**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| enable_overflow_mon | Enables overflow correction logic if set = 1 | [0] | 1 |

### Ring Oscillator Configuration

**Register 42 (0xAA) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| enable_ringosc | Enables ring oscillator output to pad if set = 1. Ring oscillator is included as a process monitor. | [0] | 0 |

**Register 43 (0xAB) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| spare | Unused register | [7:0] | 0x00 |

### Calibration Forcing Configuration

The following registers are used to allow calibration to be done off chip. To calibrate off chip, overflow correction must be disabled (by setting enable_overflow_mon = 0) while collecting data.

**Register 44 (0xAC) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| force_enable[1:0] | Put chip into external forcing mode. 0 → normal operation; 1 → forcing mode. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [1:0] | 0 |
| stage_select[2:0] | Selects which stage is put into forcing mode. MSB is stage 0, the next most significant stage is stage 1, and so on. Ex: 000 → stage0, 110 → stage6. Setting 111 has no effect. | [4:2] | 0 |
| force_refp[1:0] | Forces conversion of positive differential reference. 0 → no force; 1 → force (VREFP-VREFN) at input. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [6:5] | 0 |

**Register 45 (0xAD) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| force_refn[1:0] | Forces conversion of negative differential reference. 0 → no force; 1 → force (VREFN-VREFP) at input. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [1:0] | 0 |
| force_cm[1:0] | Forces conversion of input common-mode reference. 0 → no force; 1 → force VCMI at input. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [3:2] | 0 |
| force_msb[1:0] | Force MSB to 1. {MSB,LSB} is stage raw digital output. 0 → force MSB to 0; 1 → force MSB to 1. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [5:4] | 0 |

**Register 46 (0xAE) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| force_lsb[1:0] | Force LSB to 1. {MSB,LSB} is stage raw digital output. 0 → force LSB to 0; 1 → force LSB to 1. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [1:0] | 0 |
| caldac_ctrl[1:0] | Choose forcing DAC setting. 0 → S0, S1 measurement; 1 → S2, S3 measurement. Bit 0 corresponds to ADC0 and Bit 1 corresponds to ADC1. | [3:2] | 0 |
| clear_regs[1:0] | Clears calibration registers. 0 → ADC0; 1 → ADC1 | [5:4] | 0 |

### Monitor Output Configuration

**Register 47 (0xAF) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| vmonitor_enable | 0 → vmonitor disabled; 1 → vmonitor enabled | [0] | 0 |
| imonitor_enable | 0 → imonitor disabled; 1 → imonitor enabled | [1] | 0 |
| vmonitor_select[2:0] | Selects internal voltage to monitor. 000 → VBGR; 001 → VCMI (before ref buffers); 010 → VCMO (before ref buffers); 011 → VREFP (before ref buffers); 100 → VREFN (before ref buffers); 101 → VBGR; 110 → VSSA; 111 → VSSA | [4:2] | 0 |
| imonitor_select[2:0] | Selects internal current to monitor. 000 → ICMOS_REF; 001 → ISHA0; 010 → IADC0; 011 → ISHA1; 100 → IADC1; 101 → IBUFF (CMOS); 110 → IREF; 111 → IREFBUFFER0. SHA current based on sha_bias0 code. Buffer current based on idiff_buff0 code. | [7:5] | 0 |

### Backend Configuration

**Register 48 (0xB0) (page 2 reg 2) — Default = 0x04**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_lvds_i_ctrl[2:0] | Sets output LVDS current. 000 → 165 µA; 001 → 440 µA; 010 → 715 µA; 011 → 990 µA; 100 → 1260 µA; 101 → 1530 µA; 110 → 1800 µA; 111 → 2070 µA | [2:0] | 0b100 |

**Register 49 (0xB1) (page 2 reg 1 / page 2 reg 4) — Default = 0x10**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_start_number[4:0] | Number of positive edges of the 64 MHz clock between the 2 MHz clock edge in the backend and the frame start marker. | [4:0] | 0x10 — NOTE: should be 0x0C |
| config_sha0_pointer | Select which SHA select signal will start a sample period | [7:5] | 0b000 |

**Register 50 (0xB2) (page 2 reg 3) — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_debug_enable | Enables observation of internal digital signals and clocks at output pins. | [0] | 0x0 |
| config_debug_select[3:0] | Selects digital signal to send to debug output. 0000 → 16 MHz ADC clock (internally generated); 0001 → 64 MHz backend clock (loopback); 0010 → 2 MHz sample clock (resampled internally); 0011 → CCW_frontEndSample; 0100 → I2C_Ack1; 0101 → I2C_Ack1; 0110 → I2C_Ack3; 0111 → I2C_softReset; 1000 → I2C_writeReq; 1001 → CCW_write_external_I2C; 1010 → CCW_read_external_I2C; 1011 → CCW_external_mode_I2C; 1100 → Parity (ADC_dataA); 1101 → Parity (ADC_dataB); 1110 → PRBS7 bitstream; 1111 → PRBS15 bitstream | [4:1] | 0b0000 |
| config_test_data_mode | (not included in page 2 reg 3) Select ADC data or test patterns. 0 → normal operation (ADC data output); 1 → test pattern output | [5] | 0 |

**Register 51 (0xB3) — Default = 0xCD**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_adc0_pattern[7:0] | Low byte of pattern representing ADC0 | [7:0] | 0xCD |

**Register 52 (0xB4) — Default = 0xAB**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_adc0_pattern[15:8] | High byte of pattern representing ADC0 | [7:0] | 0xAB |

**Register 53 (0xB5) — Default = 0x34**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_adc1_pattern[7:0] | Low byte of pattern representing ADC1 | [7:0] | 0x34 |

**Register 54 (0xB6) — Default = 0x12**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_adc1_pattern[15:8] | High byte of pattern representing ADC1 | [7:0] | 0x12 |

## Page 2 Registers (I2C Only)

**Page 2 Register 1 — Default = 0x10**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_start_number[4:0] | Number of positive edges of the 64 MHz clock between the 2 MHz clock edge in the backend and the frame start marker. | [4:0] | 0x10 — NOTE: should be 0x0C |

**Page 2 Register 2 — Default = 0x04**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_lvds_i_ctrl[2:0] | Sets output LVDS current. 000 → 165 µA; 001 → 440 µA; 010 → 715 µA; 011 → 990 µA; 100 → 1260 µA; 101 → 1530 µA; 110 → 1800 µA; 111 → 2070 µA | [2:0] | 0b100 |

**Page 2 Register 3 — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_debug_enable | Enables observation of internal digital signals and clocks at output pins. | [0] | 0x0 |
| config_debug_select[3:0] | Selects digital signal to send to debug output. 0000 → 16 MHz ADC clock (internally generated); 0001 → 64 MHz backend clock (loopback); 0010 → 2 MHz sample clock (resampled internally); 0011 → CCW_frontEndSample; 0100 → I2C_Ack1; 0101 → I2C_Ack1; 0110 → I2C_Ack3; 0111 → I2C_softReset; 1000 → I2C_writeReq; 1001 → CCW_write_external_I2C; 1010 → CCW_read_external_I2C; 1011 → CCW_external_mode_I2C; 1100 → Parity (ADC_dataA); 1101 → Parity (ADC_dataB); 1110 → PRBS7 bitstream; 1111 → PRBS15 bitstream | [4:1] | 0b0000 |

**Page 2 Register 4 — Default = 0x00**

| Control Name | Description | Bits | Default |
|---|---|---|---|
| config_sha0_pointer[2:0] | Select which SHA select signal will start a sample period | [2:0] | 0b000 |

## Example Control Register Configurations

### Default Configuration

At power up and after a hard reset, all control registers and pipeline weights are set to their default values. In this configuration COLDADC_P2 is setup for normal operation using differential inputs and bypassing the input buffers. Reference voltages and currents are provided by the CMOS reference block. Registers that require different settings at different temperatures are set to values appropriate for operation in liquid argon. The pipeline ADCs are configured to operate in the "calibrated" mode, but with default (uncalibrated) weights. The output is in the form of two's complement integers.

### Calibration

The COLDATA_P2 pipeline ADCs can be calibrated by setting calibrate[1:0] = 0b11 in register 31 (register 31 = 0x03). This will start both calibration engines. During calibration COLDADC_P2 will ignore its inputs. As soon as calibration is finished, normal operation will resume. If only one bit of calibrate is set to 1, only one of the two pipeline ADCs will be calibrated. In order to redo the calibration one must first set calibrate = 0.

### Output Format

By default, the COLDADC_P2 output is expressed as 16-bit two's complement (signed) integers. The most negative number is 0x8000 and the most positive number is 0x7FFF. If adc_output_format in register 9 is set to 1 (register 9 = 0x08), the output is expressed in offset binary format (this is done simply by complementing the most significant bit). In this case the most negative number is 0x0000 and the most positive number is 0xFFFF.

### Channel Order and Digital Frame Marker Alignment

The digital output frame marker should be aligned with the most significant bit in each nibble of information from channel 0 and channel 8. The nibble alignment can be checked by setting config_test_data_mode = 1 in register 50 (register 50 = 0x20). The data corresponding to ADC0 should then be 0xABCD and the data corresponding to ADC1 should be 0x1234. The timing of the frame marker can be adjusted using config_start_number[4:0]. NOTE: the default value of 0x10 is wrong; the correct value is 0x0C. The channel order can be verified by setting adc_sync_mode = 1 in register 9 (register 9 = 0x10). This will disable the inputs to the SHAs and instead input VREFP to SHA0 and SHA8, VREFN to SHA2 and SHA10, and VCMO to all other SHAs. The ADC value read out for channel 0 and channel 8 should be close to the maximum possible value, the value read out for channel 2 and channel 10 should be close to the most negative possible value, and all others should be close to 0 (mid-range). The only way to reliably verify that the SHAs are presented to the ADC pipelines in correct order after the input voltages are sampled is to use known waveforms at the normal chip inputs (for instance by pulsing the LArASIC that is being digitized by a COLDADC).
