# COLDATA_P3_P4/E4 (Final) Datasheet

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/datasheets/COLDATA_datasheet.pdf
> Converted: 2026-06-04 (full-text extraction)

Authors: Jim Hoff, Xiaoran Wang, David Christian, Scott Holm
Date: August 9, 2022
Revision: 1.12

This is the datasheet for the second full prototype (and final version) of COLDATA. COLDATA is a control and communications ASIC designed to control four LArASIC front end ASICs and four ColdADC ASICs and to concentrate data from four ColdADCs. It transmits data to a Warm Interface Board (WIB) over two 1.25 Gbps data links. COLDATA receives commands either from a WIB or from anther COLDATA ASIC. It either responds to commands directly (if they are intended for it) or relays the commands to their destination and responses from the destination.

## Revision History

| Revision Number | Key Changes | Drafted by | Revision Date |
|---|---|---|---|
| 1.0 | Initial draft (compiled from documents written during design and testing) | DCC | 2/22/21 |
| 1.1 | Modified table of I2C chip addresses to note that the COLDATA with address 0011 is "TOP" and must use LVDS I2C. The COLDATA with address 0010 is "BOT" and must use CMOS I2C. Added I2C relay command to description of the Fast Command Receiver. Eliminated duplicate entries for regs 33-36 (p1) | DCC | 2/23/21 |
| 1.2 | Added more detail on how to assign I2C address and modified figure. Also added a description of how to measure cable delay using the I2C_SDA echo-back feature. | DCC | 2/24/21 |
| 1.3 | Corrected the default values of regs 38&39 (p1); slightly modified table on LVDS current control | DCC | 2/25/21 |
| 1.4 | Corrected the register address for LARASIC SPI Hard Reset Control. | DCC | 2/26/21 |
| 1.5 | Corrected notes on EFUSE registers and added section on how to program EFUSE bits. Also removed FRAME-15 from register description. | DCC | 5/18/21 |
| 1.6 | Added figure of pad frame. | DCC | 5/19/21 |
| 1.7 | Fixed typo in section on determining WIB-FEMB cable transit time (2→64) | DCC | 7/14/21 |
| 1.8 | Fixed typos (62.5 bytes) | DCC | 7/20/21 |
| 1.9 | Fixed more typos (62.4→64) | DCC | 2/4/22 |
| 1.10 | Corrected bonding note for pad 187 (down bond, not double bond to pin 162) | DCC | 5/1/22 |
| 1.11 | Added missing reg #s in note on how to measure cable delay | DCC | 5/25/22 |
| 1.12 | Clarified tables of frame formats (each line is 1 or more bytes) | DCC | 8/9/22 |
| 1.12 | Rewrote section on suggested PLL Band and Serializer settings (added optimal cold band setting = 0x25) | DCC | 8/9/22 |
| 1.12 | Add note in section on I2C saying that clock must be synchronous with (falling edge) of 62.5 MHz system clock. | DCC | 8/9/22 |
| 1.12 | Changed "COLDADC" to "ColdADC" everywhere. | DCC | 8/9/22 |

## Table of Contents

- Introduction — 4
- Block Diagram — 6
- Functional Description — 6
  - DUNE I2C — 6
  - I2C Slave Cell — 8
  - I2C Relay Cell — 8
  - Fast Command Receiver — 10
  - Clock Divider — 11
  - Distributed Control Register Array — 11
  - Reset State Machine — 11
  - Power On Reset — 11
  - LArASIC SPI Interface — 11
  - LArASIC Calibrate Logic — 12
  - ColdADC Data Capture — 12
  - Data Frame Formation — 12
  - Switch Yard — 13
  - 8b10b Encoder — 13
  - Phase-Locked Loop (PLL) — 13
  - Serializer — 14
  - Line Driver — 15
  - EFUSE Bits — 15
- Power Domains — 16
- Output Data Format — 16
  - Frame-DD — 17
  - Frame-12 — 18
  - Frame-14 — 19
- Wire Bonding Pad and Package Pin List — 20
- Control Registers — 28
  - Main Page (page 0) — 28
    - Read-only Registers — 36
  - PLL, Serializer, and Output Driver Page (page 5) — 41
    - PLL Control Registers — 41
    - Serializer Control Registers — 43
    - Line Driver Control Registers — 43
  - LArASIC Control Pages (pages 1-4) — 48
- Suggested PLL, Serializer, & Line Driver Register Settings — 57
  - PLL Settings — 57
  - Serializer Settings — 57
  - Line Driver Settings — 57
    - Current-mode Driver (short cables) — 57
    - Hybrid-driver w/ warm 25m cable — 58
    - Hybrid-driver w/ warm 35m cable — 58
    - Hybrid-driver w/cold 25m cable — 59
    - Hybrid-driver w/cold 35m cable — 59
- How to Determine WIB-FEMB Cable Delay — 60
- How to Write EFUSE bits — 60

## Introduction

Each DUNE Front End Motherboard (FEMB) contains eight LArASIC front end ASICs, eight ColdADC ASICs, and two COLDATA ASICs. Each COLDATA provides clocks to four ColdADCs and relays commands to four LArASICs and four ColdADCs to set operating modes and initiate calibration procedures. Each COLDATA receives data from four ColdADCs, merges the data streams, provides 8b10b encoding, serializes the data, and transmits the data to the warm electronics over two 1.25 Gbps links. These links are driven by line drivers with programmable transmitter equalization and pre-emphasis. An I2C-like protocol is used to read and write control and configuration registers in both COLDATAs and the ColdADCs, and to download LArASIC configuration data to COLDATA. COLDATA uses a custom serial programing interface to write and read back LArASIC configuration data. The Warm Interface Board (WIB) uses LVDS signaling over a twinax cables to communicate via I2C with one COLDATA on each FEMB. Commands (register reads or writes) intended for a ColdADC or for the other COLDATA are relayed to the target ASIC.

## Block Diagram

> **Figure 1:** COLDATA Block Diagram

## Functional Description

### DUNE I2C

COLDATA's control functions use a communication protocol based on I2C. DUNE I2C is similar to classical, single-master I2C with no clock extension. The major difference is motivated by the fact that the DUNE I2C communications must travel over long cables between the WIB and the FEMBs. Consequently, for these signals, canonical I2C signaling is replaced by LVDS. However, LVDS is not amenable to bidirectional communication, so canonical I2C's bidirectional SDA (Serial Data) line is replaced by two data lines, one from Warm to Cold (SDA_w2c) and one from Cold to Warm (SDA_c2w). In order to reduce power dissipation on the FEMBs, CMOS signaling rather than LVDS is used for I2C communication on the FEMB.

Other differences between DUNE I2C and canonical I2C are that DUNE I2C does not include block transfers, and it uses a 3-word protocol rather than a 2-word protocol. DUNE I2C commands are composed of three bytes of information input serially to the chip on I2C_SDA_w2c. Nine clock pulses are issued for each byte. The first 8 pulses are used to shift data either into or out of the ASIC. The I2C interface acknowledges the transmission by raising the I2C_SDA_c2w line on the ninth clock. The rising edges of data on both SDA lines are roughly in time with the rising clock edges. Data should be latched at its destination using the falling edge of the I2C_SCL clock. Bytes are shifted in most significant bit first. The first byte includes the chip address (4 bits), the register page address (3 bits), and a single bit that is set to 0 for a write command and 1 for a read command. The second byte is the 8-bit register address. For a read command, the contents of the addressed register are read out on the I2C_SDA_c2w line during the third byte. For a read command, the contents of the I2C_SDA_w2c line are unimportant during the third byte. For a write command, the third byte is the data to be written and it is presented to the chip on the I2C_SDA_w2c line. The Soft Reset command has the format of a Write to chip address 0, register page 0, register address 6: ([00000000][00000110]). The contents of the third byte are unimportant. The Soft Reset restores all COLDATA registers to their default values. It does not reset the PLL or interrupt any of the clocks.

The 62.5 MHz clock provided by the WIB to the FEMB must be present at the COLDATA for the I2C interface to work; internal state machines run on the 62.5 MHz clock. The I2C_SCL frequency must be between ~0.5 MHz and 2 MHz. If the chip address is not recognized, the response on I2C_SDA_c2w will be 0x5A. The figures below illustrate I2C communications.

Note: System tests have revealed that all edges of I2C_SCL and I2C_SDA_w2c must occur in time with a falling edge of the 62.5 MHz clock. If this timing constraint is not respected, occasional errors occur, especially in communications to a ColdADC. It is not clear whether this constraint is required by the I2C Relay Cell (described below) or by the I2C logic of the ColdADC.

> **Figure 2:** I2C write format; this example is write(chip 4, page 1); register 9; 0x52. Byte 1 = `0 1 0 0 0 0 1 0`, Byte 2 = `0 0 00 10 01`, Byte 3 = `0 1 01 0 01 0`; each byte followed by an ACK on I2C_SDA_c2w.

> **Figure 3:** I2C read format; this example is read(chip 4, page 1); register 9. The response is 0x52. Byte 1 = `0 1 0 0 0 0 1 1`, Byte 2 = `0 0 001 0 01` on I2C_SDA_w2c; response byte `0 1 01 00 1 0` on I2C_SDA_c2w; each byte followed by an ACK.

The operation of each of the COLDATA circuit blocks is described below.

### I2C Slave Cell

The I2C Slave Cell responds to commands addressed to this COLDATA, writing and reading local registers.

### I2C Relay Cell

The I2C relay cell can be connected either to LVDS lines to receive I2C commands from the WIB or to CMOS lines to receive I2C commands from the other COLDATA ASIC on the FEMB. If the pad labeled "I2C_LVDS1_CMOS0_MODE" is connected to VDDIO, then the LVDS lines are used. If it connected to ground, then the CMOS lines are used.

The I2C Relay Cell relays the I2C_SCL and I2C_SDA_w2c signals to COLDATA's internal I2C Slave Cell. It also drives them as CMOS signals off chip so they can be connected to ColdADCs and potentially to another COLDATA. If the chip address in the first word of the I2C communication is the address of this COLDATA, then the I2C_SDA_c2w (reply) signal from the internal I2C Slave is connected to the external (LVDS or CMOS) I2C_SDA_c2w signal. If the chip address in the first word of the I2C communication is the address of one of the ColdADCs connected to this COLDATA, then the I2C (relayed) SDA_c2w signal from the appropriate ColdADC is connected to the external I2C_SDA_c2w signal. If the chip address in the first word of the I2C communication is the address of the other COLDATA or one of the ColdADCs connected to the other COLDATA, then the I2C (relayed) SDA_c2w signal from the other COLDATA is connected to the external I2C_SDA_c2w signal.

In order to facilitate the relay logic, the COLDATA and ColdADCs are required to follow the following chip address naming convention:

| Chip Address | Assignment |
|---|---|
| 0000 – 0001 | Unused |
| 0010 | "Bottom" COLDATA (must use CMOS I2C) |
| 0011 | "Top" COLDATA (must use LVDS I2C) |
| 01xx (xx = 00,01,10,11) | ColdADCs attached to COLDATA_BOT |
| 10xx (xx = 00,01,10,11) | ColdADCs attached to COLDATA_TOP |
| 11xx (xx = 00,01,10,11) | Unused |

> **Table 1:** I2C Chip Addressing Convention

Note that the COLDATA ASIC with I2C address = 0011 must use the LVDS I2C I/O lines. In this document, that COLDATA is also referred to as the "Top" COLDATA. The COLDATA ASIC with I2C address = 0010 must use the CMOS I2C I/O lines. This COLDATA is also referred to as the "Bottom" COLDATA. The COLDATA I2C address is set using the I/O line called CHIP_ID_0 (pad 149/package pin 131). This line is pulled up internally. To assign I2C address = 0010, CHIP_ID_0 should be connected to ground. To assign I2C address = 0011, CHIP_ID_0 should be left floating.

The figure below illustrates the I2C connections allowing the WIB to read and write registers in 2 COLDATAs and 8 ColdADCs.

> **Figure 4:** COLDATA I2C Relay interconnections

### Fast Command Receiver

Fast commands are formatted as 8-bit words. All legal fast commands are DC balanced. Fast command and 62.5 MHz clock rising edges are equal time. Fast command bits are captured on the negative edge of the 62.5 MHz clock & shifted into a register on the next positive edge.

> **Figure 5:** Fast Commands are latched on the falling edge of the 62.5 MHz clock.

The legal fast commands are:

- Alert = 1111_0000 (synchronize)
- Idle = 1010_1010
- Edge = 1110_0001 (move edge of 2 MHz clock to next rising edge of 62.5 MHz clock)
- Sync = 1110_0010 (zero timestamp)
- Act = 1110_0100 (perform command stored in Act Command Register)
- Reset = 1110_1000 (Resets COLDATA)

Act Command register (loaded via I2C):

- Idle = 0000_0000 (no action)
- LArASIC_PULSE = 0000_0001 (act to start calibration sequence; act again to stop)
- Save Timestamp = 0000_0010
- Save Status = 0000_0011
- Clear Saves = 0000_0100
- Reset ColdADCs = 0000_0101
- Reset LArASICs = 0000_0110 (Reset LArASICs using the LARASIC_RESET pad)
- SPI Reset = 0000_0111 (Reset LArASICs using the SPI interface)
- Program LArASICs = 0000_1000 (Download the stored daisy chain bits to LArASICs using SPI)
- Relay I2C_SDA = 0000_1001 (Echo I2C_SDA_W2C back to WIB on I2C_SDA_C2W if and only if all three I2C_Relay_Code registers are set)

The Alert command is used to synchronize the Fast Command Receiver with the sender. In principle it is only necessary to issue the Alert command once, but it may be prudent to precede each command (or group of commands) with one or two Alert commands.

### Clock Divider

The ColdADC ASIC requires two clocks to function – "2 MHz" and 62.5 MHz. The Clock Divider creates the "2 MHz" clock by dividing the 62.5 MHz clock received from the WIB by 32. This means that the "2 MHz" clock frequency is actually 1.953125 MHz and that ColdADC will sample its analog inputs every 512 ns rather than every 500 ns as would be the case with a 2 MHz clock. Because ColdADC was initially specified for use with a 2 MHz sampling clock, the clocks input to ColdADC from COLDATA are named "2 MHz" and "64 MHz." The rising edge of the "2 MHz" clock occurs at a rising edge of the 62.5 MHz clock. The Fast Command "Edge" allows the rising edge of the "2 MHz" Clock to be adjusted so that it is in time with a specific rising edge of the 62.5 MHz clock.

### Distributed Control Register Array

The registers accessible by I2C are distributed across the ASIC wherever they are needed. For example, many are located in the SPI Interface to the LARASICs. More are located in the serializers, etc. The Distributed Control Register Array is included in the block diagram to show that the Data_w2c, Data_c2w, Page_Addr and Reg_Addr buses and the Write_Enable and Soft_Reset signals are routed throughout the ASIC.

### Reset State Machine

When the COLDATA Reset command is received, it starts a Reset State Machine that resets the entire chip in a prescribed order starting with the PLL. The same sequence is started by the Power On Reset circuit, in response to a Fast Command:Reset, and if the COLDATA Reset pad is pulled to ground.

### Power On Reset

The power on reset circuit is supplied by VDDCORE. It includes a Schmitt trigger for hysteresis and is internally gated to a test pad (inside the main pad ring) that allows the circuit to be disabled if tied to VSS. The length of time that reset is asserted when the power is turned on depends on the rise time of VDDCORE and on temperature. Simulations indicate that the duration of the reset signal is at least 8 microseconds at room temperature and 0.6 milliseconds at liquid argon temperature. The power on reset circuit starts the reset state machine.

### LArASIC SPI Interface

LArASIC uses a custom Serial Peripheral Interface (SPI) for its configuration bits. The interface has four signals: SCK (Serial Clock), SDO (Serial Data Out), SDI (Serial Data In) and CS (Chip Select) in an SPI-like configuration. The interface also implements certain actions like Soft Reset and Hard Reset depending on the state of the four signals. The configuration bits are arranged as one large daisy chain that cannot be read out non-destructively. Instead, to ensure transmission of any new configuration, data must be transmitted twice and read back on the second transmission.

The LArASIC SPI Interface cell implements all the special functions of the LArASIC Interface including Soft Reset and Hard Reset. It uses a group of 8-bit I2C Control Registers (part of the Distributed Control Register Array in the Block Diagram) that collectively hold the entire LArASIC SPI daisy chain. Finally, it contains a state machine that when ordered will download the daisy chain bits into LArASIC twice, read back the second transmission and compare the bits read back with the bits transmitted.

### LArASIC Calibrate Logic

The gain of each LArASIC/ColdADC channel can be calibrated by injecting test pulses into the LArASIC analog front end and recording the resulting ADC values as a function of the amplitude of the test pulses. This can be done either with a signal input to the TEST pin of LArASIC or using the LArASIC internal DAC and a sequence of {SCK,CS} transitions. The LArASIC internal pulser can be controlled using the LArASIC Calibrate Logic block. Certain physical factors of the test pulses like the channel number and the signal magnitude are pre-programmed on LArASIC by downloading values through the SPI interface. Other timing factors, like the timing of the rising edge, the length of time to the falling edge and the length of time to the next rising edge are pre-programmed on COLDATA by downloading values through its I2C interface. Finally, an ACT signal is downloaded to COLDATA through the Fast Command Receiver that tells COLDATA to enter the Calibrate mode. Thereafter, Calibrate Strobe signals that obey the timing constraints are output to the LArASIC chips using the {SCK,CS} lines where they generate test pulses that obey the physical constraints downloaded to LArASIC. These Calibrate Strobes continue until a second Calibrate command is sent to COLDATA via the Fast Command Receiver taking COLDATA out of Calibrate mode.

### ColdADC Data Capture

Each ColdADC outputs 256 bits of data every "2 MHz" period (512 ns). The interface between ColdADC and COLDATA includes a frame start signal, a data output clock, and 8 data output lines, all LVDS. ColdADC Data Capture has the job of grabbing whole 256-bit data frames and passing them forward to the Data Frame Formation block.

### Data Frame Formation

Every rising edge of the 2MHz clock, the Data Frame Formation block packs data from two ColdADC Data Capture blocks into fragments of the final data frame. As described below, three different frame formats are defined. Fragments for all three formats are prepared in this circuit block. Two checksums are also calculated for each frame fragment, one for each 16-channel block of data from an individual ColdADC. The checksums are simple 8-bit sums (mod 256) of the bytes making up the frame fragment.

### Switch Yard

In the Switch Yard, the two data frame fragments of the currently-selected frame format are merged, a header is added (consisting of an identifying first word < 3 and a timestamp), and a trailer is added to create a 64-byte packet. The Switch Yard also contains a FIFO in which data crosses from the 2 MHz clock domain to the clock domain defined by the serializer. At the output of this FIFO, 9-bit words are output to the pipeline stage. For data bytes, the "extra" bit is set to 0. For characters that will be output as 8b10b control characters (the first word and the trailer words), the "extra" bit is set to 1. If the complete data frame is output in a time less than one 2 MHz clock period, then idle characters are output. If the entire data frame is not output in one 2 MHz clock period, then the data frame is truncated.

### 8b10b Encoder

This block implements standard 8b10b encoding. Encoding can also be switched off to facilitate debugging. In this case, the two high order bits are set to 1 for control characters and the two high order bits are set to 0 for data bytes. The option is also provided to output a pseudo-random bit stream (either PRBS-7 or PRBS-15), ignoring the input data, or to output a continuous sequence of K.28.5 comma characters.

### Phase-Locked Loop (PLL)

The Phase-Locked Loop (PLL) uses a single-path architecture. It uses the 62.5 MHz clock received from the WIB and produces a phase-locked 2.5 GHz output clock. A block diagram of the PLL is shown in Figure 6. The PLL was designed before the speed of the output links was decided. Since a speed of 1.25 Gbps was chosen, the PLL also includes a divider that produces a single 1.25 GHz clock. This clock is input to both serializer blocks.

> **Figure 6:** The PLL consists of a Phase and Frequency Detector (PFD), a Charge Pump, a Low Pass Filter (LPF), a Voltage-Controlled Oscillator (VCO), and a Divider. (Diagram shows CKREF and CKFB into the PFD producing UP/DOWN signals to the charge pump (ICP) and LPF (R, C1, C2) producing VCTL, which tunes the VCO varactors and capacitor bank (x32, x16, x8, x4, x2, …, x1) to generate CKOUT; a /40 Divider closes the feedback loop.)

The phase and frequency differences between the reference clock (CKref) and the feedback clock (CKfb) generates UP and DOWN signals that drive the charge pump (shown in Figure 6) to charge or discharge the low pass filter. The control voltage (VCTL) developed at the output of the low pass filter tunes the varactors in the VCO, and thus the phase and frequency of CKout. The charge pump current and the capacitance in the LC-based VCO are programmable to compensate for process and temperature-dependent variations. The bandwidth of the PLL is designed to be 1.5 MHz. The inductor in the VCO has an inductance of 1.4 nH and a quality factor of 14, and the KVCO is set to be ~100 MHz/Volt.

> **Figure 7:** PLL Charge Pump: controlled by UP and DN (DOWN) signals produced by the Phase and Frequency Detector. (Shows Vdd supply, sel-controlled Vbp/Vbn bias, UP and DN switch banks, Vcm and Icp nodes.)

### Serializer

A block diagram of the serializer is shown below. In the normal 10-bit mode, incoming parallel data at 125 MHz is input to two 5:1 multiplexers, whose output is then input to a 2:1 multiplexer, registered by a D flip-flop, and output to a line driver. The 625 MHz and 125 MHz clocks required by the multiplexers are produced in each serializer. The 125 MHz clock is also output to the Switch Yard, which provides data to the serializer. An 8-bit mode is included for debugging purposes. In 8-bit mode, parallel data is input at 156.25 MHz and the first multiplexer stage operates as two 4:1 multiplexers.

> **Figure 8:** Serializer

### Line Driver

The 1.25 Gbps hybrid-mode line driver is designed with current-mode transmitter equalization and voltage-mode pre-emphasis to drive 25-35 meter long twin-axial cables. The current-mode transmitter equalization circuit uses a finite impulse response (FIR) filter to distort the data pulse and compensate for the large frequency-dependent signal loss over a long twinax cable with low dynamic power consumption. The voltage-mode main driver and pre-emphasis circuit uses source-series-terminated (SST) output stages to provide a large output voltage swing and low static power consumption.

The line-driver is highly programmable and can also be operated in a pure current-mode or a pure voltage-mode.

### EFUSE Bits

COLDATA includes 32 bits of non-volatile memory that can be "written" by burning fuse links and can be copied to registers than are accessible via the I2C interface. These bits can be used to assign a serial number to each COLDATA ASIC.

## Power Domains

COLDATA includes five power domains as shown in the table below.

| Name | Voltage | Usage |
|---|---|---|
| VDDIO | 2.25 V | All I/O except to/from LArASICs |
| VDD_LArASIC | 1.8 V | I/O to/from LArASICs |
| VDDCORE | 1.1 V | Core digital logic |
| VDDD | 1.1 V | Digital logic in PLL, serializers, and line drivers |
| VDDA | 1.1 V | PLL analog circuits |

> **Table 2:** COLDATA Power Domains

## Output Data Format

COLDATA uses 8b10b encoding. The comma character K.28.5 is used to establish link synchronization and the comma characters K.28.1 and K.28.5 are used to maintain link synchronization. The comma character K.28.7 is not used. K.28.1 is the idle character and is inserted into the output data stream if no data is available for transmission.

Three types of data frames are defined. These are called Frame-DD, Frame-12, and Frame-14. The data frames all have similar format: {start of frame, timestamp, ADC data, trailer}. All of the data frames contain 64 bytes of information. The start of frame characters for each format are given in the table below.

| Frame Name | Start of Frame Characters |
|---|---|
| FRAME-DD | K.28.1, K.28.0 |
| FRAME-12 | K.28.1, K.28.2 |
| FRAME-14 | K.28.1, K.28.3 |

> **Table 3:** Output data frame types

Since the ADC sampling period is 512 ns, the bandwidth required to transmit the frame data is exactly 1.25 Gbps, which is the nominal link speed. If the ADC sampling rate is slightly greater than nominal, or if the link speed is slightly lower than nominal, then some frames will be truncated by one byte. For this reason, the trailer of each frame time contains at least two comma characters.

### Frame-DD

Frame-DD (Dummy Data) is intended to be used to debug link problems. It has very similar format to Frame-12 in that the "ADC values" are 12-bit numbers, but rather than real ADC data, it contains "dummy" data. Each line in the table below represents one (or more) bytes.

| Field |
|---|
| K.28.1 |
| K.28.0 |
| Test Start/Timestamp[15:8] (2 bytes) |
| Timestamp[7:0] |
| Fake ADC1[23:0] = [23,22,…,1,0] (16 12-bit values packed into 24 bytes) |
| Fake ADC2[23:0] = [23,22,…,1,0] (16 12-bit values packed into 24 bytes) |
| Checksum 1 = Sum_mod256(Fake ADC1) = 0x14 |
| Checksum 2 = Sum_mod256(Fake ADC2) = 0x14 |
| 10xK.28.5 (10 bytes) |

> **Table 4:** Frame DD

### Frame-12

Frame-12 is used for 12-bit ADC data. Each line in the table below represents one (or more) bytes.

| Field |
|---|
| K.28.1 |
| K.28.2 |
| Test Start/Timestamp[15:8] (2 bytes) |
| Timestamp[7:0] |
| ADC1[23:0] (16 12-bit values packed into 24 bytes) |
| ADC2[23:0] (16 12-bit values packed into 24 bytes) |
| Checksum 1 = Sum_mod256(ADC1) |
| Checksum 2 = Sum_mod256(ADC2) |
| 10xK.28.5 (10 bytes) |

> **Table 5:** Frame 12

In Frame 12, ADC data is packed as shown in the figure below.

> **Figure 9:** ADC data packing for Frame-12

### Frame-14

Frame-14 is used for 14-bit ADC data. Each line in the table below represents one (or more) bytes.

| Field |
|---|
| K.28.1 |
| K.28.3 |
| Test Start/Timestamp[15:8] (2 bytes) |
| Timestamp[7:0] |
| ADC1[27:0] (16 14-bit values packed into 27 bytes) |
| ADC2[27:0] (16 14-bit values packed into 27 bytes) |
| Checksum 1 = Sum_mod256(ADC1) |
| Checksum 2 = Sum_mod256(ADC2) |
| 2xK.28.5 (2 bytes) |

> **Table 6:** Frame 14

In Frame-14, ADC data is packed as shown in the figure below.

> **Figure 10:** ADC data packing for Frame-14

## Wire Bonding Pad and Package Pin List

The COLDATA die size is 7730 microns by 7730 microns. The chip has five power domains and one common ground (Vss). There are 248 wire bond pads, 62 on each side of the chip. The low profile quad flat package has 216 pins, 54 on each side, and a back-side contact. The back-side contact should be connected to the substrate potential (Vss). The LQFP package is 24 mm by 24 mm and 1.4 mm high. Figure 11 shows the wire bond pad numbering. Table 7 lists the package pin numbers as well as the pad numbers.

> **Figure 11:** COLDATA_P3 wire bonding pad frame; features noted can be used to orient the bare die. Features marked on the die include the VCO inductor (not visible in COLDATA_P3), an unused internal bonding pad, and a small logo.

| Pad # | Pad Name | Pin # | Pin Name | Comment |
|---|---|---|---|---|
| 1 | ADC2_DIG_OUTB_P | 1 | ADC2_DIG_OUTB_P | |
| 2 | ADC2_DIG_OUTB_N | 2 | ADC2_DIG_OUTB_N | |
| 3 | VSS | 3 | VSS | |
| 4 | ADC2_DIG_OUTC_P | 4 | ADC2_DIG_OUTC_P | |
| 5 | ADC2_DIG_OUTC_N | 5 | ADC2_DIG_OUTC_N | |
| 6 | VSS | | VSS | Downbond |
| 7 | ADC2_DIG_OUTD_P | 6 | ADC2_DIG_OUTD_P | |
| 8 | ADC2_DIG_OUTD_N | 7 | ADC2_DIG_OUTD_N | |
| 9 | VDDIO | 8 | VDDIO | |
| 10 | ADC2_DIG_OUTE_P | 9 | ADC2_DIG_OUTE_P | |
| 11 | ADC2_DIG_OUTE_N | 10 | ADC2_DIG_OUTE_N | |
| 12 | VSS | 11 | VSS | |
| 13 | ADC2_DIG_OUTF_P | 12 | ADC2_DIG_OUTF_P | |
| 14 | ADC2_DIG_OUTF_N | 13 | ADC2_DIG_OUTF_N | |
| 15 | VSS | | VSS | Downbond |
| 16 | ADC2_DIG_OUTG_P | 14 | ADC2_DIG_OUTG_P | |
| 17 | ADC2_DIG_OUTG_N | 15 | ADC2_DIG_OUTG_N | |
| 18 | VSS | | VSS | Downbond |
| 19 | ADC2_DIG_OUTH_P | 16 | ADC2_DIG_OUTH_P | |
| 20 | ADC2_DIG_OUTH_N | 17 | ADC2_DIG_OUTH_N | |
| 21 | VDDIO | 18 | VDDIO | |
| 22 | ADC2_DIG_FRAME_P | 19 | ADC2_DIG_FRAME_P | |
| 23 | ADC2_DIG_FRAME_N | 20 | ADC2_DIG_FRAME_N | |
| 24 | VSS | 21 | VSS | |
| 25 | ADC2_DIG_CLKOUT_P | 22 | ADC2_DIG_CLKOUT_P | |
| 26 | ADC2_DIG_CLKOUT_N | 23 | ADC2_DIG_CLKOUT_N | |
| 27 | VDDCORE | 24 | VDDCORE | |
| 28 | VSS | 25 | VSS | |
| 29 | VDDIO | 26 | VDDIO | |
| 30 | ADC3_CLK_62.5MHZ_N | 27 | ADC3_CLK_62.5MHZ_N | |
| 31 | ADC3_CLK_62.5MHZ_P | 28 | ADC3_CLK_62.5MHZ_P | |
| 32 | VSS | 29 | VSS | |
| 33 | ADC3_CLK_2MHZ_N | 30 | ADC3_CLK_2MHZ_N | |
| 34 | ADC3_CLK_2MHZ_P | 31 | ADC3_CLK_2MHZ_P | |
| 35 | VDDIO | 32 | VDDIO | |
| 36 | ADC3_DIG_OUTA_P | 33 | ADC3_DIG_OUTA_P | |
| 37 | ADC3_DIG_OUTA_N | 34 | ADC3_DIG_OUTA_N | |
| 38 | VSS | 35 | VSS | |
| 39 | ADC3_DIG_OUTB_P | 36 | ADC3_DIG_OUTB_P | |
| 40 | ADC3_DIG_OUTB_N | 37 | ADC3_DIG_OUTB_N | |
| 41 | VSS | | VSS | Downbond |
| 42 | ADC3_DIG_OUTC_P | 38 | ADC3_DIG_OUTC_P | |
| 43 | ADC3_DIG_OUTC_N | 39 | ADC3_DIG_OUTC_N | |
| 44 | VSS | | VSS | Downbond |
| 45 | ADC3_DIG_OUTD_P | 40 | ADC3_DIG_OUTD_P | |
| 46 | ADC3_DIG_OUTD_N | 41 | ADC3_DIG_OUTD_N | |
| 47 | VDDIO | 42 | VDDIO | |
| 48 | ADC3_DIG_OUTE_P | 43 | ADC3_DIG_OUTE_P | |
| 49 | ADC3_DIG_OUTE_N | 44 | ADC3_DIG_OUTE_N | |
| 50 | VSS | 45 | VSS | |
| 51 | ADC3_DIG_OUTF_P | 46 | ADC3_DIG_OUTF_P | |
| 52 | ADC3_DIG_OUTF_N | 47 | ADC3_DIG_OUTF_N | |
| 53 | VSS | | VSS | Downbond |
| 54 | ADC3_DIG_OUTG_P | 48 | ADC3_DIG_OUTG_P | |
| 55 | ADC3_DIG_OUTG_N | 49 | ADC3_DIG_OUTG_N | |
| 56 | VSS | | VSS | Downbond |
| 57 | ADC3_DIG_OUTH_P | 50 | ADC3_DIG_OUTH_P | |
| 58 | ADC3_DIG_OUTH_N | 51 | ADC3_DIG_OUTH_N | |
| 59 | VDDIO | 52 | VDDIO | |
| 60 | ADC3_DIG_FRAME_P | 53 | ADC3_DIG_FRAME_P | |
| 61 | ADC3_DIG_FRAME_N | 54 | ADC3_DIG_FRAME_N | |
| 62 | VSS | | VSS | Downbond |
| 63 | ADC3_DIG_CLKOUT_P | 55 | ADC3_DIG_CLKOUT_P | |
| 64 | ADC3_DIG_CLKOUT_N | 56 | ADC3_DIG_CLKOUT_N | |
| 65 | VDDCORE | 57 | VDDCORE | |
| 66 | VDDCORE | | VDDCORE | Doublebond to #57 |
| 67 | VSS | 58 | VSS | |
| 68 | VSS | | VSS | Doublebond to #58 |
| 69 | ADC4_CLK_62.5MHZ_P | 59 | ADC4_CLK_62.5MHZ_P | |
| 70 | ADC4_CLK_62.5MHZ_N | 60 | ADC4_CLK_62.5MHZ_N | |
| 71 | VDDIO | 61 | VDDIO | |
| 72 | ADC4_CLK_2MHZ_P | 62 | ADC4_CLK_2MHZ_P | |
| 73 | ADC4_CLK_2MHZ_N | 63 | ADC4_CLK_2MHZ_N | |
| 74 | VSS | 64 | VSS | |
| 75 | ADC4_DIG_OUTA_P | 65 | ADC4_DIG_OUTA_P | |
| 76 | ADC4_DIG_OUTA_N | 66 | ADC4_DIG_OUTA_N | |
| 77 | VDDIO | 67 | VDDIO | |
| 78 | ADC4_DIG_OUTB_P | 68 | ADC4_DIG_OUTB_P | |
| 79 | ADC4_DIG_OUTB_N | 69 | ADC4_DIG_OUTB_N | |
| 80 | VSS | | VSS | Downbond |
| 81 | ADC4_DIG_OUTC_P | 70 | ADC4_DIG_OUTC_P | |
| 82 | ADC4_DIG_OUTC_N | 71 | ADC4_DIG_OUTC_N | |
| 83 | VSS | | VSS | Downbond |
| 84 | ADC4_DIG_OUTD_P | 72 | ADC4_DIG_OUTD_P | |
| 85 | ADC4_DIG_OUTD_N | 73 | ADC4_DIG_OUTD_N | |
| 86 | VDDIO | 74 | VDDIO | |
| 87 | ADC4_DIG_OUTE_P | 75 | ADC4_DIG_OUTE_P | |
| 88 | ADC4_DIG_OUTE_N | 76 | ADC4_DIG_OUTE_N | |
| 89 | VSS | 77 | VSS | |
| 90 | ADC4_DIG_OUTF_P | 78 | ADC4_DIG_OUTF_P | |
| 91 | ADC4_DIG_OUTF_N | 79 | ADC4_DIG_OUTF_N | |
| 92 | VSS | | VSS | Downbond |
| 93 | ADC4_DIG_OUTG_P | 80 | ADC4_DIG_OUTG_P | |
| 94 | ADC4_DIG_OUTG_N | 81 | ADC4_DIG_OUTG_N | |
| 95 | VSS | | VSS | Downbond |
| 96 | ADC4_DIG_OUTH_P | 82 | ADC4_DIG_OUTH_P | |
| 97 | ADC4_DIG_OUTH_N | 83 | ADC4_DIG_OUTH_N | |
| 98 | VDDIO | 84 | VDDIO | |
| 99 | ADC4_DIG_FRAME_P | 85 | ADC4_DIG_FRAME_P | |
| 100 | ADC4_DIG_FRAME_N | 86 | ADC4_DIG_FRAME_N | |
| 101 | VSS | 87 | VSS | |
| 102 | ADC4_DIG_CLKOUT_P | 88 | ADC4_DIG_CLKOUT_P | |
| 103 | ADC4_DIG_CLKOUT_N | 89 | ADC4_DIG_CLKOUT_N | |
| 104 | VDDCORE | 90 | VDDCORE | |
| 105 | VDDCORE | | VDDCORE | Doublebond to #90 |
| 106 | VSS | 91 | VSS | |
| 107 | VSS | | VSS | Doublebond to #91 |
| 108 | LARASIC1_SDO | 92 | LARASIC1_SDO | |
| 109 | LARASIC1_CS | 93 | LARASIC1_CS | |
| 110 | LARASIC1_SCK | 94 | LARASIC1_SCK | |
| 111 | LARASIC1_SDI | 95 | LARASIC1_SDI | |
| 112 | LARASIC2_SDO | 96 | LARASIC2_SDO | |
| 113 | LARASIC2_CS | 97 | LARASIC2_CS | |
| 114 | LARASIC2_SCK | 98 | LARASIC2_SCK | |
| 115 | LARASIC2_SDI | 99 | LARASIC2_SDI | |
| 116 | LARASIC3_SDO | 100 | LARASIC3_SDO | |
| 117 | LARASIC3_CS | 101 | LARASIC3_CS | |
| 118 | LARASIC3_SCK | 102 | LARASIC3_SCK | |
| 119 | LARASIC3_SDI | 103 | LARASIC3_SDI | |
| 120 | LARASIC4_SDO | 104 | LARASIC4_SDO | |
| 121 | LARASIC4_CS | 105 | LARASIC4_CS | |
| 122 | LARASIC4_SCK | 106 | LARASIC4_SCK | |
| 123 | LARASIC4_SDI | 107 | LARASIC4_SDI | |
| 124 | LARASIC_RESET | 108 | LARASIC_RESET | |
| 125 | VSS | 109 | VSS | |
| 126 | VSS | | VSS | Doublebond to #109 |
| 127 | VDD_LARASIC | 110 | VDD_LARASIC | |
| 128 | VDD_LARASIC | | VDD_LARASIC | Doublebond to #110 |
| 129 | I2C_CMOS_SDA_C2W | 111 | I2C_CMOS_SDA_C2W | |
| 130 | I2C_COLDATA_SCL | 112 | I2C_COLDATA_SCL | |
| 131 | I2C_COLDATA_SDA_W2C | 113 | I2C_COLDATA_SDA_W2C | |
| 132 | I2C_CMOS_SCL | 114 | I2C_CMOS_SCL | |
| 133 | I2C_CMOS_SDA_W2C | 115 | I2C_CMOS_SDA_W2C | |
| 134 | I2C_COLDATA_SDA_C2W | 116 | I2C_COLDATA_SDA_C2W | |
| 135 | VSS | 117 | VSS | |
| 136 | I2C_ADC_1_SDA_C2W | 118 | I2C_ADC_1_SDA_C2W | |
| 137 | I2C_ADC_2_SDA_C2W | 119 | I2C_ADC_2_SDA_C2W | |
| 138 | I2C_ADC_3_SDA_C2W | 120 | I2C_ADC_3_SDA_C2W | |
| 139 | I2C_ADC_4_SDA_C2W | 121 | I2C_ADC_4_SDA_C2W | |
| 140 | I2C_LVDS1_CMOS0_MODE | 122 | I2C_LVDS1_CMOS0_MODE | |
| 141 | VDDIO | 123 | VDDIO | |
| 142 | FMB_CONTROL_0 | 124 | FMB_CONTROL_0 | |
| 143 | FMB_CONTROL_1 | 125 | FMB_CONTROL_1 | |
| 144 | FMB_CONTROL_2 | 126 | FMB_CONTROL_2 | |
| 145 | FMB_CONTROL_3 | 127 | FMB_CONTROL_3 | |
| 146 | FMB_CONTROL_4 | 128 | FMB_CONTROL_4 | |
| 147 | ADC_MASTER_RESET | 129 | ADC_MASTER_RESET | |
| 148 | PAD_RESET | 130 | PAD_RESET | COLDATA RESET |
| 149 | CHIP_ID_0 | 131 | CHIP_ID_0 | |
| 150 | I2C_LVDS_SCL_P | 132 | I2C_LVDS_SCL_P | |
| 151 | I2C_LVDS_SCL_N | 133 | I2C_LVDS_SCL_N | |
| 152 | VSS | | VSS | Downbond |
| 153 | I2C_LVDS_SDA_W2C_P | 134 | I2C_LVDS_SDA_W2C_P | |
| 154 | I2C_LVDS_SDA_W2C_N | 135 | I2C_LVDS_SDA_W2C_N | |
| 155 | VSS | 136 | VSS | |
| 156 | I2C_LVDS_SDA_C2W_N | 137 | I2C_LVDS_SDA_C2W_N | |
| 157 | I2C_LVDS_SDA_C2W_P | 138 | I2C_LVDS_SDA_C2W_P | |
| 158 | VDDIO | 139 | VDDIO | |
| 159 | FASTCOMMAND_IN_P | 140 | FASTCOMMAND_IN_P | |
| 160 | FASTCOMMAND_IN_N | 141 | FASTCOMMAND_IN_N | |
| 161 | VSS | | VSS | Downbond |
| 162 | EFUSE_DOUT | 142 | EFUSE_DOUT | |
| 163 | EFUSE_SCLK | 143 | EFUSE_SCLK | |
| 164 | EFUSE_PGM | 144 | EFUSE_PGM | |
| 165 | EFUSE_DIN | 145 | EFUSE_DIN | |
| 166 | EFUSE_CSB | 146 | EFUSE_CSB | |
| 167 | EFUSE_VDDQ | 147 | EFUSE_VDDQ | |
| 168 | CLK_62.5MHZ_SYS_P | 148 | CLK_62.5MHZ_SYS_P | |
| 169 | CLK_62.5MHZ_SYS_N | 149 | CLK_62.5MHZ_SYS_N | |
| 170 | VSS | 150 | VSS | |
| 171 | VSS | | VSS | Doublebond to 150 |
| 172 | VDDCORE | 151 | VDDCORE | |
| 173 | VDDCORE | 152 | VDDCORE | |
| 174 | VDDD | 153 | VDDD | |
| 175 | VDDD | 154 | VDDD | |
| 176 | SEROUTP1 | 155 | SEROUTP1 | |
| 177 | SEROUTN1 | 156 | SEROUTN1 | |
| 178 | VSS | 157 | VSS | |
| 179 | VSS | | VSS | Doublebond to #157 |
| 180 | VDDD | 158 | VDDD | |
| 181 | VSS | | VSS | Downbond |
| 182 | VDDD | 159 | VDDD | |
| 183 | VDDD | | VDDD | Doublebond to #159 |
| 184 | SEROUTN2 | 160 | SEROUTN2 | |
| 185 | SEROUTP2 | 161 | SEROUTP2 | |
| 186 | VSS | 162 | VSS | |
| 187 | VSS | | VSS | Downbond |
| 188 | LOCK | 163 | LOCK | |
| 189 | VSS | 164 | VSS | |
| 190 | VDDD | 165 | VDDD | |
| 191 | ATO | 166 | ATO | |
| 192 | VCEXT | 167 | VCEXT | |
| 193 | VDDA | 168 | VDDA | |
| 194 | VDDA | 169 | VDDA | |
| 195 | VDDA | 170 | VDDA | |
| 196 | VSS | 171 | VSS | |
| 197 | VDDA | 172 | VDDA | |
| 198 | VSS | 173 | VSS | |
| 199 | VSS | | VSS | Doublebond to pin #173 |
| 200 | VDDIO | 174 | VDDIO | |
| 201 | ADC1_CLK_62.5MHZ_P | 175 | ADC1_CLK_62.5MHZ_P | |
| 202 | ADC1_CLK_62.5MHZ_N | 176 | ADC1_CLK_62.5MHZ_N | |
| 203 | VSS | 177 | VSS | |
| 204 | ADC1_CLK_2MHZ_P | 178 | ADC1_CLK_2MHZ_P | |
| 205 | ADC1_CLK_2MHZ_N | 179 | ADC1_CLK_2MHZ_N | |
| 206 | VDDIO | 180 | VDDIO | |
| 207 | ADC1_DIG_OUTA_P | 181 | ADC1_DIG_OUTA_P | |
| 208 | ADC1_DIG_OUTA_N | 182 | ADC1_DIG_OUTA_N | |
| 209 | VSS | 183 | VSS | |
| 210 | ADC1_DIG_OUTB_P | 184 | ADC1_DIG_OUTB_P | |
| 211 | ADC1_DIG_OUTB_N | 185 | ADC1_DIG_OUTB_N | |
| 212 | VSS | | VSS | Downbond |
| 213 | ADC1_DIG_OUTC_P | 186 | ADC1_DIG_OUTC_P | |
| 214 | ADC1_DIG_OUTC_N | 187 | ADC1_DIG_OUTC_N | |
| 215 | VSS | | VSS | Downbond |
| 216 | ADC1_DIG_OUTD_P | 188 | ADC1_DIG_OUTD_P | |
| 217 | ADC1_DIG_OUTD_N | 189 | ADC1_DIG_OUTD_N | |
| 218 | VDDIO | 190 | VDDIO | |
| 219 | ADC1_DIG_OUTE_P | 191 | ADC1_DIG_OUTE_P | |
| 220 | ADC1_DIG_OUTE_N | 192 | ADC1_DIG_OUTE_N | |
| 221 | VSS | 193 | VSS | |
| 222 | ADC1_DIG_OUTF_P | 194 | ADC1_DIG_OUTF_P | |
| 223 | ADC1_DIG_OUTF_N | 195 | ADC1_DIG_OUTF_N | |
| 224 | VSS | | VSS | Downbond |
| 225 | ADC1_DIG_OUTG_P | 196 | ADC1_DIG_OUTG_P | |
| 226 | ADC1_DIG_OUTG_N | 197 | ADC1_DIG_OUTG_N | |
| 227 | VSS | | VSS | Downbond |
| 228 | ADC1_DIG_OUTH_P | 198 | ADC1_DIG_OUTH_P | |
| 229 | ADC1_DIG_OUTH_N | 199 | ADC1_DIG_OUTH_N | |
| 230 | VDDIO | 200 | VDDIO | |
| 231 | ADC1_DIG_FRAME_P | 201 | ADC1_DIG_FRAME_P | |
| 232 | ADC1_DIG_FRAME_N | 202 | ADC1_DIG_FRAME_N | |
| 233 | VSS | 203 | VSS | |
| 234 | ADC1_DIG_CLKOUT_P | 204 | ADC1_DIG_CLKOUT_P | |
| 235 | ADC1_DIG_CLKOUT_N | 205 | ADC1_DIG_CLKOUT_N | |
| 236 | VDDCORE | 206 | VDDCORE | |
| 237 | VDDCORE | | VDDCORE | Doublebond to pin #206 |
| 238 | VSS | 207 | VSS | |
| 239 | VSS | | VSS | Doublebond to pin #207 |
| 240 | VDDIO | 208 | VDDIO | |
| 241 | ADC2_CLK_62.5MHZ_P | 209 | ADC2_CLK_62.5MHZ_P | |
| 242 | ADC2_CLK_62.5MHZ_N | 210 | ADC2_CLK_62.5MHZ_N | |
| 243 | VSS | 211 | VSS | |
| 244 | ADC2_CLK_2MHZ_P | 212 | ADC2_CLK_2MHZ_P | |
| 245 | ADC2_CLK_2MHZ_N | 213 | ADC2_CLK_2MHZ_N | |
| 246 | VDDIO | 214 | VDDIO | |
| 247 | ADC2_DIG_OUTA_P | 215 | ADC2_DIG_OUTA_P | |
| 248 | ADC2_DIG_OUTA_N | 216 | ADC2_DIG_OUTA_N | |

> **Table 7:** Wirebond Pad and Package Pin List

## Control Registers

ALL of the following tables represent registers (sometimes more than one – e.g. anything going to an ADC1PAGE can also be found on an ADC2PAGE, etc.) physically located inside COLDATA. Each table shows the chip address, page address and register address necessary to reach that register. So, for example, to reach the LVDS Current Set register, a user would use either COLDATA_TOP or COLDATA_BOT for the chip address in Word 1 of the I2C transfer; the user would use MAINPAGE for the page address in Word 1 of the I2C transfer; the user would use LVDS_CURRENT_SET_REG as the register address in Word 2 of the I2C transfer; and, finally the user would put whatever data was desired to be written in Word 3 of the I2C transfer. Under both an I2C read and an I2C write, the data currently contained in the register will be output from SDA_c2w during Word 3. Using binary, the transfer would be either (Word 1) 00110000 (Word 2) 00010001 (Word 3) DDDDDDDD or (Word 1) 00100000 (Word 2) 00010001 (Word 3) DDDDDDDD depending on which chip (COLDATA_TOP or COLDATA_BOT) the user was trying to reach.

### Main Page (page 0)

Main Page registers control the overall function of the chip. They control the current through driving pads, the FRAME created by COLDATA, the transmission of clocks to ColdADC, etc.

#### ADC Frame Configure – Register 1 (0x1)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FRAMECONFIGREG (8'b0000_0001) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [1:0] |

Description: This register contains frame type for outputting ADC data.

| Bit Pattern | Command | Action |
|---|---|---|
| 2'b00 | FRAME12 | Default |
| 2'b01 | FRAME14 | |
| 2'b11 | FRAMEDD | Dummy Data |

#### 8b10b Bypass and Flow Control Register – Register 3 (0x3)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | BYPASS8B10BREG (8'b0000_0011) |
| Default Value | 8'b0010_1000 |
| Significant Bits | All |

Description: This register controls the flow of data to the SMU Serializer. It selects whether or not 8b10 will be engaged or bypassed, whether the FIFO data will be output or not, and whether the Synchronizing Comma character will be output.

| Bit | Action |
|---|---|
| 0 | 1 - Bypass 8b10b encoder for Serial Output 1; 0 – Enable 8b10b encoder for Serial Output 1 |
| 1 | 1 - Bypass 8b10b encoder for Serial Output 2; 0 – Enable 8b10b encoder for Serial Output 2 |
| 2:3 | (00) Unencoded PRBS7 -> Serial Output 1; (01) Unencoded PRBS15 -> Serial Output 1; (10) Unencoded K_28_5 -> Encoder -> Serial Output 1; (11) Unencoded outFIFO1 data -> Encoder -> Serial Output 1 |
| 4:5 | (00) Unencoded PRBS7 -> Serial Output 2; (01) Unencoded PRBS15 -> Serial Output 2; (10) Unencoded K_28_5 -> Encoder -> Serial Output 2; (11) Unencoded outFIFO1 data -> Encoder -> Serial Output 2 |
| 6 | 1 – Present Data to Serializer 1 MSB to LSB; 0 – Present Data to Serializer 1 LSB to MSB |
| 7 | 1 – Present Data to Serializer 2 MSB to LSB; 0 – Present Data to Serializer 2 LSB to MSB |

Note: When 8b10b encoding is used, bits 6 and 7 should be OFF (LSB to MSB). If 8b10b encoding is turned off (for debugging), bits 6 and 7 should be ON (MSB to LSB).

#### LVDS Current Set – Register 17 (0x11)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | LVDS_CURRENT_SET_REG (8'b0001_0001) |
| Default Value | 8'b0000_0010 |
| Significant Bits | [2:0] |

Description: This register controls the current through the LVDS drivers of the IO pads. They work as follows:

| [2] | [1] | [0] | Iout +/- | VOD, 100 Ohm load |
|---|---|---|---|---|
| 0 | 0 | 0 | 2 mA | ±200mV |
| 1 | 0 | 0 | 4 mA | ±400mV |
| 0 | 1 | 0 | 4 mA | ±400mV |
| 1 | 1 | 0 | 6 mA | ±600mV |
| 0 | 0 | 1 | 4 mA | ±400mV |
| 1 | 0 | 1 | 6 mA | ±600mV |
| 0 | 1 | 1 | 6 mA | ±600mV |
| 1 | 1 | 1 | 8 mA | ±800mV |

#### FUSE_COMMAND – Register 31 (0x1F)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FUSE_COMMAND (8'b0001_1111) |
| Default Value | 0x0 |
| Significant Bits | [1:0] |

Description: If bit 0 of FUSE_COMMAND is 0, then writing a 1 to bit 0 will disconnect the EFUSE circuitry from the pads and copy the contents of the EFUSE bits to the read-only EFUSE I2C registers described below. If bit 1 of FUSE_COMMAND is 0, then writing a 1 to bit 1 will connect the EFUSE circuitry to the pads. If FUSE_COMMAND=0 and 0x3 is written, these two actions will occur one after the other (the pads will be disconnected, the contents of the EFUSE bits copied to the I2C registers, and the pads reconnected to the EFUSE circuitry). The pads are also connected to the EFUSE circuitry after a COLDATA reset or an I2C soft reset.

#### FASTACT Command – Register 32 (0x20)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ACTCOMMANDREG (8'b0010_0000) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register contains the specific command to be executed by the appearance of the FASTACT command on the Fast Command Stream.

| Bit Pattern | Command | Action |
|---|---|---|
| 8'b0000_0000 | FASTACT_IDLE_COMMAND | Do nothing |
| 8'b0000_0001 | FASTACT_LARASIC_CAL_COMMAND | Toggle the Start or Ending of LARASIC Calibrate signals |
| 8'b0000_0010 | FASTACT_SAVE_TIMESTAMP_COMMAND | Save the current timestamp for readout via I2C |
| 8'b0000_0011 | FASTACT_SAVE_STATUS_COMMAND | Save the various status bits for readout via I2C |
| 8'b0000_0100 | FASTACT_CLEAR_SAVES_COMMAND | Clear the saved status bits |
| 8'b0000_0101 | FASTACT_ColdADC_RESET_COMMAND | Reset the ColdADCs via the ColdADC_MASTER_RESET pad |
| 8'b0000_0110 | FASTACT_LARASIC_RESET_COMMAND | Reset the LARASICs via the LARASIC_RESET pad |
| 8'b0000_0111 | FASTACT_LARASIC_SPIRST_COMMAND | Reset the LARASICs via the LARASIC SPI interface |
| 8'b0000_1000 | FASTACT_LARASIC_PROG_COMMAND | Download the stored daisy chain bits to the LARASICs via the SPI interface |
| 8'b0000_1001 | FASTACT_WIB_RELAY_COMMAND | Connect I2C_SDA_W2C to I2C_SDA_C2W if Regs 43-45 (0x2B-0x2D) all = 1. I2C_SDA_W2C will be echoed back on I2C_SDC_C2W for 2 microseconds when a FASTACT is issued. This sequence will be ignored by the Bottom COLDATA_P3. |

#### LARASIC Data Feed Count – Register 37 (0x25)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | REG_LARASIC_DATAFEEDCNT (8'b0010_0101) |
| Default Value | 8'b0010_0000 |
| Significant Bits | [7:0] |

Description: This register controls the duration in units of 62.5MHz Clock periods of the width of the LArASIC programming half period. Output data changes at the beginning of each bit period. The SCK remains low for ½ of the Data Feed Count. Then the SCK goes high and remains high for Data Feed Count 62.5MHz clock periods. Then the SCK goes low again and remains so for another ½ of the Data Feed Count. Therefore, by default, each bit period is 2 x 32 x 16ns = 1024 ns or about 1 MHz.

NOTE: There is a bug in COLDATA_P3 that means the LArASIC programming SCK remains high for only 1 62.5 MHz clock tick. The time SCK remains low is controlled by REG_LARASIC_DATAFEEDCNT.

#### Front-end Mother Board Control – Register 38 (0x26)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | REG_FMB_CONTROL_WORD (8'b0010_0101) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [4:0] |

Description: This register controls the DC-type level signals for the Front-end Mother Board (pads FMB_CONTROL_N (bit N)).

#### Front-end Mother Board Control – Register 39 (0x27)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | REG_FMB_TRISTATE_WORD (8'b0010_0101) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [4:0] |

Description: This register controls whether the DC-type level signals for the Front-end Mother Board (pads FMB_CONTROL_N (bit N)) are available at the pads, or tristated.

#### LARASIC Master Reset Count – Register 40 (0x28)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | REG_LARASIC_RST_COUNT (8'b0010_0110) |
| Default Value | 8'b0010_0000 |
| Significant Bits | All |

Description: This register controls the duration of the LARASIC Master Reset, the single-ended signal that resets all of the LARASICs through the LARASIC_Reset Pad. When the FASTACT_Command register has been set to FASTACT_LARASIC_RESET and then the FASTACT command has been given through the Fast Command, the LARASIC_Reset Pad will drop to ZERO for a number of 62.5MHz counts equal to the contents of this LARASIC Master Reset Counter register. With the default setting, the LArASIC pad reset is 512 ns long.

#### ColdADC Master Reset Count – Register 41 (0x29)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | REG_ADC_RST_COUNT (8'b0010_0111) |
| Default Value | 8'b0010_0000 |
| Significant Bits | All |

Description: This register controls ADC Master Reset, the single-ended signal that resets all of the ColdADCs through the ADC_MASTER_RESET Pad. When the FASTACT_Command register has been set to FASTACT_ColdADC_RESET and then the FASTACT command has been given through the Fast Command, the ADC_MASTER_RESET Pad will drop to ZERO for a number of 62.5MHz counts equal to the contents of this ColdADC Master Reset Counter register. With the default value, the ColdADC reset will be 512 ns long.

#### ColdADC 2MHz Clock Control Register – Register 42 (0x2A)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ADCCLKCTRLREG (8'b0010_1010) |
| Default Value | 8'b1111_1111 |
| Significant Bits | All |

Description: This register gates the 62.5MHz and 2MHz clock signals sent to each ColdADC. If a particular bit is a ONE, that clock is enabled. Note that the clocks are all also gated by the Core Run signal, so the clocks are all zero when COLDATA is resetting.

| Bit Number | ADC | Clock |
|---|---|---|
| 0 | ADC1 | 62.5MHz |
| 1 | ADC1 | 2MHz |
| 2 | ADC2 | 62.5MHz |
| 3 | ADC2 | 2MHz |
| 4 | ADC3 | 62.5MHz |
| 5 | ADC3 | 2MHz |
| 6 | ADC4 | 62.5MHz |
| 7 | ADC4 | 2MHz |

#### I2C_RelayCode_1 – Register 43 (0x2B)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | WIB_FEEDBACK_CODE_REG_1 (8'b0010_1011) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register must be set to 8'b1011_0010 before issuing the FASTACT_WIB_RELAY_COMMAND or I2C_SDA_W2C will not be relayed back on I2C_SDA_C2W.

#### I2C_RelayCode_2 – Register 44 (0x2C)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | WIB_FEEDBACK_CODE_REG_2 (8'b0010_1100) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register must be set to 8'b1011_0010 before issuing the FASTACT_WIB_RELAY_COMMAND or I2C_SDA_W2C will not be relayed back on I2C_SDA_C2W.

#### I2C_RelayCode_3 – Register 45 (0x2D)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | WIB_FEEDBACK_CODE_REG_3 (8'b0010_1101) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register must be set to 8'b1011_0010 before issuing the FASTACT_WIB_RELAY_COMMAND or I2C_SDA_W2C will not be relayed back on I2C_SDA_C2W.

#### Read-only Registers

Two groups of page 0 registers cannot be written to using the I2C interface. One group is associated with the EFUSE bits that can be burned during acceptance testing. The EFUSE bits are intended to hold the serial number assigned during testing. The second group of read-only registers includes two status registers and one register that can be loaded with the current timestamp in response to a fast command.

##### EFUSE Register 0 – Register 24 (0x18)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FUSE_REG_0 (8'b0001_1000) |
| Default Value | 0 |
| Significant Bits | All |

Description: After FUSE_COMMAND (described above) has been used to save the contents of the EFUSE bits, this register will contain chipNumber[7:0] (see section on How to Write EFUSE bits).

##### EFUSE Register 1 – Register 25 (0x19)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FUSE_REG_1 (8'b0001_1001) |
| Default Value | 0 |
| Significant Bits | All |

Description: After FUSE_COMMAND (described above) has been used to save the contents of the EFUSE bits, this register will contain chipNumber[15:8] (see section on How to Write EFUSE bits).

##### EFUSE Register 2 – Register 26 (0x1A)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FUSE_REG_2 (8'b0001_1010) |
| Default Value | 0 |
| Significant Bits | All |

Description: After FUSE_COMMAND (described above) has been used to save the contents of the EFUSE bits, this register will contain chipNumber[23:16] (see section on How to Write EFUSE bits).

##### EFUSE Register 3 – Register 27 (0x1B)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | FUSE_REG_3 (8'b0001_1011) |
| Default Value | 0 |
| Significant Bits | All |

Description: After FUSE_COMMAND (described above) has been used to save the contents of the EFUSE bits, the most significant bit of this register will be set=1 and the low order 7 bits will contain chipNumber[30:24] (see section on How to Write EFUSE bits).

##### Fast ACT TStamp Register 1 – Register 33 (0x21)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ACTTSTAMPREG (8'b0010_0001) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [7:0] |

Description: When a FASTACT_SAVE_TIMESTAMP_COMMAND is issued, the low order 8 bits of the timestamp will be loaded into this register.

##### Fast ACT TStamp Register 2 – Register 34 (0x22)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ACTTSTAMPREG2 (8'b0010_0010) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [6:0] |

Description: When a FASTACT_SAVE_TIMESTAMP_COMMAND is issued, the high order 7 bits of the timestamp will be loaded into this register.

##### Fast ACT Status Register 1 – Register 35 (0x23)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ACTSTATUSREG (8'b0010_0011) |
| Default Value | 8'b0000_0000 |
| Significant Bits | [7:0] |

Description: If the FastAct Command is set to FASTACT_SAVE_STATUS_COMMAND (8'b0000_0011), then whenever the FastAct Command is received through the FastCommand serial interface, this register will be updated with the latest status for the following bits:

| Bit | Action |
|---|---|
| 0 | status_Heartbeat – Should always be a zero if the FastCommand Serial Interface is working properly. Once an alert is given (8'b1111_0000), thereafter all FastCommands including Idles should end in 0 (except for FastCommand Edge Now). Status_Heartbeat simply latches bit 0 of every command word. |
| 1 | status_Heartbeat_perpetual – if Status_Heartbeat was ever a 1, status_Heartbeat_perpetual will remain a 1 unless an I2C Soft Reset is given or a FastAct Command is given with the FastAct Command set to FASTACT_CLEAR_SAVES. |
| 2:5 | N/A |
| 6 | Interface_LOCK – this should be identical to the LOCK pad in the SMU section |
| 7 | CORE_RUN – this indicates that the COLDATA Reset state machine has completed and the chip is in a Run Mode. |

##### FASTACT Status Register #2 – Register 36 (0x24)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | MAINPAGE (3'b000) |
| Register Address | ACTSTATUSREG2 (8'b0010_0100) |
| Default Value | N/A (READ ONLY) |
| Significant Bits | All |

Description: If the FastAct Command is set to FASTACT_SAVE_STATUS_COMMAND (8'b0000_0011), then whenever the FastAct Command is received through the FastCommand serial interface, this register will be updated with the latest status for the following bits:

| Bit | Action |
|---|---|
| 0 | LARASIC1 Comparison Done (1=Done, 0=Working) |
| 1 | LARASIC1 Programming Comparison Result (1=Match, 0=Did Not Match) |
| 2 | LARASIC2 Comparison Done (1=Done, 0=Working) |
| 3 | LARASIC2 Programming Comparison Result (1=Match, 0=Did Not Match) |
| 4 | LARASIC3 Comparison Done (1=Done, 0=Working) |
| 5 | LARASIC3 Programming Comparison Result (1=Match, 0=Did Not Match) |
| 6 | LARASIC4 Comparison Done (1=Done, 0=Working) |
| 7 | LARASIC4 Programming Comparison Result (1=Match, 0=Did Not Match) |

### PLL, Serializer, and Output Driver Page (page 5)

#### PLL Control Registers

##### CONFIG_PLL_ICP – Register 64 (0x40)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_ICP (8'b0100_0000) |
| Default Value | 3'b011 |
| Significant Bits | [2:0] |

Description: Charge Pump Current Register: Sets the PLL charge pump current Icp=(ICP[2:0]+1)*100 μA.

##### CONFIG_PLL_BAND – Register 65 (0x41)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_BAND (8'b0100_0001) |
| Default Value | 6'b10_0000 |
| Significant Bits | [5:0] |

Description: VCO Coarse Tune Band Register: Sets the PLL VCO digital switched capacitor array code. Oscillation frequency increases with BAND code.

##### CONFIG_PLL_LPFR – Register 66 (0x42)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_LPFR (8'b0100_0010) |
| Default Value | 2'b10 |
| Significant Bits | [1:0] |

Description: Loop Filter Resistor Register: Sets the PLL analog loop filter resistor value. Rlpf=10/11/12/14 kΩ for LPFR[1:0]=2'b00/01/10/11 respectively.

##### CONFIG_PLL_ATO – Register 67 (0x43)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_ATO (8'b0100_0011) |
| Default Value | 2'b10 |
| Significant Bits | [1:0] |

Description: Analog Test Output Register: Sets the PLL analog output test selection control.
- ATO[1:0]=2'b00 : Vbpchp (Charge pump bias voltage)
- ATO[1:0]=2'b01: Vctl (PLL loop control voltage)
- ATO[1:0]=2'b10/11 ( No outputs)

##### CONFIG_PLL_PDCP – Register 68 (0x44)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_PDCP (8'b0100_0100) |
| Default Value | 1'b0 |
| Significant Bits | [0] |

Description: Charge Pump Power Down Register: Power down the charge pump bias block and force charge pump outputting high-Z, Active High.

##### CONFIG_PLL_OPEN – Register 69 (0x45)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_PLL_OPEN (8'b0100_0101) |
| Default Value | 1'b0 |
| Significant Bits | [0] |

Description: Open PLL Loop Register: To open the PLL loop for testing, Active High.

#### Serializer Control Registers

##### CONFIG_SER_MODE – Register 70 (0x46)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_SER_MODE (8'b0100_0110) |
| Default Value | 1'b1 |
| Significant Bits | [0] |

Description: Serializer Mode Register: Sets the mode of the serializer. MODE=1'b0: 8:1 Serializer; MODE=1'b1: 10:1 Serializer.

##### CONFIG_SER_INV_SER_CLK – Register 71 (0x47)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_SER_INV_SER_CLK (8'b0100_0111) |
| Default Value | 1'b0 |
| Significant Bits | [0] |

Description: Serializer 125MHz Clock Inverse: Invert the edge of the serializer output 125MHz clock.

#### Line Driver Control Registers

##### CONFIG_DRV_VMBOOST – Register 72 (0x48)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_VMBOOST (8'b0100_1000) |
| Default Value | 3'b011 |
| Significant Bits | [2:0] |

Description: Voltage Mode Boost Register: Program the strength of the voltage mode pre-emphasis (max=111).

##### CONFIG_DRV_VMDRIVER – Register 73 (0x49)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_VMDRIVER (8'b0100_1001) |
| Default Value | 3'b111 |
| Significant Bits | [2:0] |

Description: Voltage Mode Driver Register: Program the strength of the voltage mode driver (max=111).

##### CONFIG_DRV_SELPRE – Register 74 (0x4A)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_SELPRE (8'b0100_1010) |
| Default Value | 4'b0000 |
| Significant Bits | [3:0] |

Description: Pre-tap Selection Register: Program the coefficient of the pre-tap.

##### CONFIG_DRV_SELPST1 – Register 75 (0x4B)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_SELPST1 (8'b0100_1011) |
| Default Value | 4'b0010 |
| Significant Bits | [3:0] |

Description: Post-tap1 Selection Register: Program the coefficient of the post-tap1.

##### CONFIG_DRV_SELPST2 – Register 76 (0x4C)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_SELPST2 (8'b0100_1100) |
| Default Value | 3'b000 |
| Significant Bits | [2:0] |

Description: Post-tap2 Selection Register: Program the coefficient of the post-tap2.

##### CONFIG_DRV_SELCM_MAIN – Register 77 (0x4D)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_SELCM_MAIN (8'b0100_1101) |
| Default Value | 4'b0000 |
| Significant Bits | [3:0] |

Description: Main tap Selection Register: Program the coefficient of the main tap.

##### CONFIG_DRV_ENABLE_CM – Register 78 (0x4E)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_ENABLE_CM (8'b0100_1110) |
| Default Value | 1'b1 |
| Significant Bits | [0] |

Description: Enable CM Equalization Register: Enable or disable the current mode equalization.

##### CONFIG_DRV_INVERSE_CLK – Register 79 (0x4F)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_INVERSE_CLK (8'b0100_1111) |
| Default Value | 1'b0 |
| Significant Bits | [0] |

Description: Inverse Clock Register: Invert the raising/falling edge of the clock.

##### CONFIG_DRV_DELAYSEL – Register 80 (0x50)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_DELAYSEL (8'b0101_0000) |
| Default Value | 3'b000 |
| Significant Bits | [2:0] |

Description: Pre-Emphasis Width Selection Register: Program the width of the pre-emphasis pulse.

##### CONFIG_DRV_DELAY_CS – Register 81 (0x51)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_DELAY_CS (8'b0101_0001) |
| Default Value | 4'b1111 |
| Significant Bits | [3:0] |

Description: Current-Starving Register: Program the current of the delay cell.

##### CONFIG_DRV_CML – Register 82 (0x52)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_CML (8'b0101_0010) |
| Default Value | 1'b0 |
| Significant Bits | [0] |

Description: CML Driver Register: Program back to CML driver without pre-emphasis.

##### CONFIG_DRV_BIAS_CML_INTERNAL – Register 83 (0x53)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_BIAS_CML_INTERNAL (8'b0101_0011) |
| Default Value | 1'b1 |
| Significant Bits | [0] |

Description: BIAS_CML Internal Selection: Select the internal BIAS_CML.

##### CONFIG_DRV_BIAS_CS_INTERNAL – Register 84 (0x54)

| Field | Value |
|---|---|
| Chip Address(es) | COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010) |
| Page Address | SMUPAGE (3'b101) |
| Register Address | REG_CONFIG_DRV_BIAS_CS_INTERNAL (8'b0101_0100) |
| Default Value | 1'b1 |
| Significant Bits | [0] |

Description: BIAS_CS Internal Selection: Select the internal BIAS_CS.

### LArASIC Control Pages (pages 1-4)

Pages 1-4 contain identical registers that control interactions with LArASIC chips. Page 1 has control registers for LArASIC1, which is connected to ColdADC1. Page 2 has control registers for LArASIC2, which is connected to ColdADC2, and so on.

For all registers in this section, the Chip Address(es) is COLDATA_TOP or COLDATA_BOT (4'b0011 or 4'b0010), and the Page Address is ADC1PAGE or ADC2PAGE or ADC3PAGE or ADC4PAGE (3'b001 or 3'b010 or 3'b011 or 3'b100).

#### LARASIC Calibrate: Sample Periods Per Calibrate Strobe – Register 6 (0x6)

| Field | Value |
|---|---|
| Register Address | SAMPLES_PER_CALIB (8'b0000_0110) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register is a Calibration control register. It sets the number of strobe-free 2MHz Clock periods after a Calibration strobe has ended before another Calibration strobe can be raised.

#### LARASIC Calibrate: 62.5MHz Periods After Sample Start to Start of Calibrate Strobe – Register 7 (0x7)

| Field | Value |
|---|---|
| Register Address | CALIB_CLKPER_AFTER_SAMP (8'b0000_0111) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register is a Calibration control register. It sets the number 62.5MHz Clock periods after the start of a Sample Period (rising edge of 2MHz Clock) that must occur before a Calibration strobe can be raised.

#### LARASIC Calibrate: Duration of the Calibrate Strobe in 62.5MHz Periods – Register 8 (0x8)

| Field | Value |
|---|---|
| Register Address | CALIB_STROBE_WIDTH_UPPER (8'b0000_1000) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register is the upper 8 bits of a calibration control register. It sets the duration of the Calibrate Strobe counted in 62.5MHz Clock periods.

#### LARASIC Calibrate: Duration of the Calibrate Strobe in 62.5MHz Periods – Register 9 (0x9)

| Field | Value |
|---|---|
| Register Address | CALIB_STROBE_WIDTH_LOWER (8'b0000_1001) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register is the lower 8 bits of a calibration control register. It sets the duration of the Calibrate Strobe counted in 62.5MHz Clock periods.

#### LARASIC SPI Hard Reset Control: Duration of Hard Reset – Register 11 (0xB)

| Field | Value |
|---|---|
| Register Address | HARD_RESET_COUNT (8'b0000_1011) |
| Default Value | 8'b0000_0000 |
| Significant Bits | All |

Description: This register is a Calibration control register. It sets the duration of the SPI Hard Reset counted in 62.5MHz Clock periods.

#### LARASIC Programming Configuration Data Registers – Registers 128-145 (0x80-0x91)

These 18 registers collectively hold the LArASIC SPI daisy chain bits [143:0]. For each, the Default Value is 8'b0000_0000 and the Significant Bits are All.

| Register | Hex | Register Name | Bits |
|---|---|---|---|
| 128 | 0x80 | LARASIC_1 | Byte 1 (Most Significant): Bits 143 to 136 |
| 129 | 0x81 | LARASIC_2 | Byte 2: Bits 135 to 128 |
| 130 | 0x82 | LARASIC_3 | Byte 3: Bits 127 to 120 |
| 131 | 0x83 | LARASIC_4 | Byte 4: Bits 119 to 112 |
| 132 | 0x84 | LARASIC_5 | Byte 5: Bits 111 to 104 |
| 133 | 0x85 | LARASIC_6 | Byte 6: Bits 103 to 96 |
| 134 | 0x86 | LARASIC_7 | Byte 7: Bits 95 to 88 |
| 135 | 0x87 | LARASIC_8 | Byte 8: Bits 87 to 80 |
| 136 | 0x88 | LARASIC_9 | Byte 9: Bits 79 to 72 |
| 137 | 0x89 | LARASIC_10 | Byte 10: Bits 71 to 64 |
| 138 | 0x8A | LARASIC_11 | Byte 11: Bits 63 to 56 |
| 139 | 0x8B | LARASIC_12 | Byte 12: Bits 55 to 48 |
| 140 | 0x8C | LARASIC_13 | Byte 13: Bits 47 to 40 |
| 141 | 0x8D | LARASIC_14 | Byte 14: Bits 39 to 32 |
| 142 | 0x8E | LARASIC_15 | Byte 15: Bits 31 to 24 |
| 143 | 0x8F | LARASIC_16 | Byte 16: Bits 23 to 16 |
| 144 | 0x90 | LARASIC_17 | Byte 17: Bits 15 to 8 |
| 145 | 0x91 | LARASIC_18 | Byte 18 (Least Significant): Bits 7 to 0 |

## Suggested PLL, Serializer, & Line Driver Register Settings

### PLL Settings

The default PLL band setting (REG_CONFIG_PLL_BAND) of 0x20 will work both warm and cold. However, the mid point of the range of values for the band setting is 0x25 for cold operation and 0x26 for warm operation. REG_CONFIG_PLL_BAND = 0x25 is suggested.

### Serializer Settings

The default serializer settings will work both warm and cold.

### Line Driver Settings

#### Current-mode Driver (short cables)

| Register | Hex | Binary |
|---|---|---|
| CONFIG_DRV_VMBOOST | 0x0 | 3'b000 |
| CONFIG_DRV_VMDRIVER | 0x0 | 3'b000 |
| CONFIG_DRV_SELPRE | 0x0 | 4'b0000 |
| CONFIG_DRV_SELPST1 | 0x0 | 4'b0000 |
| CONFIG_DRV_SELPST2 | 0x0 | 3'b000 |
| CONFIG_DRV_SELCM_MAIN | 0xF | 4'b1111 |
| CONFIG_DRV_ENABLE_CM | 0x1 | 1'b1 |
| CONFIG_DRV_INVERSE_CLK | 0x0 | 1'b0 |
| CONFIG_DRV_DELAYSEL | 0x0 | 3'b000 |
| CONFIG_DRV_DELAY_CS | 0xF | 4'b1111 |
| CONFIG_DRV_CML | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CML_INTERNAL | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CS_INTERNAL | 0x1 | 1'b1 |

#### Hybrid-driver w/ warm 25m cable

| Register | Hex | Binary |
|---|---|---|
| CONFIG_DRV_VMBOOST | 0x7 | 3'b111 |
| CONFIG_DRV_VMDRIVER | 0x7 | 3'b111 |
| CONFIG_DRV_SELPRE | 0x1 | 4'b0001 |
| CONFIG_DRV_SELPST1 | 0xA | 4'b1010 |
| CONFIG_DRV_SELPST2 | 0x1 | 3'b001 |
| CONFIG_DRV_SELCM_MAIN | 0x0 | 4'b0000 |
| CONFIG_DRV_ENABLE_CM | 0x1 | 1'b1 |
| CONFIG_DRV_INVERSE_CLK | 0x0 | 1'b0 |
| CONFIG_DRV_DELAYSEL | 0x0 | 3'b000 |
| CONFIG_DRV_DELAY_CS | 0xF | 4'b1111 |
| CONFIG_DRV_CML | 0x0 | 1'b0 |
| CONGIF_DRV_BIAS_CML_INTERNAL | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CS_INTERNAL | 0x1 | 1'b1 |

#### Hybrid-driver w/ warm 35m cable

| Register | Hex | Binary |
|---|---|---|
| CONFIG_DRV_VMBOOST | 0x7 | 3'b111 |
| CONFIG_DRV_VMDRIVER | 0x7 | 3'b111 |
| CONFIG_DRV_SELPRE | 0x2 | 4'b0010 |
| CONFIG_DRV_SELPST1 | 0xC | 4'b1100 |
| CONFIG_DRV_SELPST2 | 0x1 | 3'b001 |
| CONFIG_DRV_SELCM_MAIN | 0x0 | 4'b0000 |
| CONFIG_DRV_ENABLE_CM | 0x1 | 1'b1 |
| CONFIG_DRV_INVERSE_CLK | 0x0 | 1'b0 |
| CONFIG_DRV_DELAYSEL | 0x0 | 3'b000 |
| CONFIG_DRV_DELAY_CS | 0xF | 4'b1111 |
| CONFIG_DRV_CML | 0x0 | 1'b0 |
| CONGIF_DRV_BIAS_CML_INTERNAL | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CS_INTERNAL | 0x1 | 1'b1 |

#### Hybrid-driver w/cold 25m cable

| Register | Hex | Binary |
|---|---|---|
| CONFIG_DRV_VMBOOST | 0x3 | 3'b011 |
| CONFIG_DRV_VMDRIVER | 0x7 | 3'b111 |
| CONFIG_DRV_SELPRE | 0x0 | 4'b0000 |
| CONFIG_DRV_SELPST1 | 0x2 | 4'b0010 |
| CONFIG_DRV_SELPST2 | 0x0 | 3'b000 |
| CONFIG_DRV_SELCM_MAIN | 0x0 | 4'b0000 |
| CONFIG_DRV_ENABLE_CM | 0x1 | 1'b1 |
| CONFIG_DRV_INVERSE_CLK | 0x0 | 1'b0 |
| CONFIG_DRV_DELAYSEL | 0x0 | 3'b000 |
| CONFIG_DRV_DELAY_CS | 0xF | 4'b1111 |
| CONFIG_DRV_CML | 0x0 | 1'b0 |
| CONGIF_DRV_BIAS_CML_INTERNAL | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CS_INTERNAL | 0x1 | 1'b1 |

#### Hybrid-driver w/cold 35m cable

| Register | Hex | Binary |
|---|---|---|
| CONFIG_DRV_VMBOOST | 0x3 | 3'b011 |
| CONFIG_DRV_VMDRIVER | 0x7 | 3'b111 |
| CONFIG_DRV_SELPRE | 0x0 | 4'b0000 |
| CONFIG_DRV_SELPST1 | 0x5 | 4'b0101 |
| CONFIG_DRV_SELPST2 | 0x2 | 3'b010 |
| CONFIG_DRV_SELCM_MAIN | 0x0 | 4'b0000 |
| CONFIG_DRV_ENABLE_CM | 0x1 | 1'b1 |
| CONFIG_DRV_INVERSE_CLK | 0x0 | 1'b0 |
| CONFIG_DRV_DELAYSEL | 0x0 | 3'b000 |
| CONFIG_DRV_DELAY_CS | 0xF | 4'b1111 |
| CONFIG_DRV_CML | 0x0 | 1'b0 |
| CONGIF_DRV_BIAS_CML_INTERNAL | 0x1 | 1'b1 |
| CONGIF_DRV_BIAS_CS_INTERNAL | 0x1 | 1'b1 |

## How to Determine WIB-FEMB Cable Delay

If a specific series of commands is issued, then for approximately sixty-four microseconds, the input to the TOP COLDATA (I2C address = 0011) on the LVDS I2C input data line (I2C_LVDS_SDA_W2C) will be connected directly to the LVDS I2C output data line (I2C_LVDS_SDA_C2W). If the WIB issues a single pulse or a pulse train on I2C_LVDS_SDA_W2C while this connection is made, it will be possible to determine the time it takes for a signal from the WIB to reach the FEMB and return. The time delay inside COLDATA will be negligible.

The commands required are:

- All three WIB_FEEDBACK_CODE_REGs (page 0, regs 43, 44, & 45 = 0x2B, 0x2C, & 0x2D) must be set to 8'b1011_0010 (0xB2);
- ACTCOMMANDREG (page 0, reg 32 = 0x20) must be set to 8'b0000_1001 (0x09);
- A Fast Command FASTACT must be issued.

After the FASTACT command, I2C_SDA_W2C will be echoed back on I2C_SDC_C2W for approximately sixty-four microseconds. If another FASTACT command is issued before the two microseconds is up, the echo back will end after the second FASTACT command.

If this series of commands is issued to the BOTTOM COLDATA, it will be ignored.

## How to Write EFUSE bits

The EFUSE bits are intended to contain a unique chip number. Package pins 143-147 (pads 163-167) are used to burn the EFUSE bits. By convention EFUSE bit 0 is expected to be set = 1 to indicate that the EFUSE bits have been burned. The 31 bit chip number is then burned into EFUSE bits 1-31. The EFUSE bits can be copied into I2C read-only registers using the FUSE_COMMAND register. The procedure to program the EFUSE bits is illustrated in the figure below. COLDATA must be powered normally and the 62.5 MHz clock must be running in order for the EFUSE bits to be burned.

> **Figure 12:** EFUSE Programming. EFUSE_VDDQ is the fuse-burning voltage and should be set to 2.5V (2.4-2.6V). The total time that EFUSE_VDDQ is on should be less than 1 second. The EFUSE control signals are 1.1V CMOS signals. EFUSE_SCLK should be held high for 5 microseconds for each bit to be programmed.
