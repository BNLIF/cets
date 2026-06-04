# LArASIC P5 Datasheet

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/datasheets/LArASIC_datasheet.pdf
> Converted: 2026-06-04 (full-text extraction)

Authors:
- Dr. Venkata Narasimha Manyam
- Dr. Giovanni Pinaroli
- Dr. Grzegorz Deptuch

| Revision Number | Change Description | Author | Revision Date |
|---|---|---|---|
| 1.0 | Initial draft based on LArASIC P4 datasheet and with new modifications | VNM | Apr, 2021 |

## LArASIC

LArASIC is a programmable, full-functionality 16-channel front-end ASIC in 180 nm CMOS designed for the Deep Underground Neutrino Experiment (DUNE) single-phase (SP) liquid argon (LAr) time-projection chamber (TPC). It is capable of performing a low-noise, highly-linear charge amplification by a factor of up to 320x, higher-order shaping with a charge to voltage conversion, ac/dc coupling along with high-performance buffering in each channel. Signals can be read out using direct outputs of the shaping amplifiers, single-ended output buffers, or single-to-differential converting output buffers. It is designed and optimized to operate at the cryogenic temperature of 87 K, reliably for over 20 years of the experiment's lifetime. A simplified block diagram is as shown in Fig. 1

> **Figure 1:** Simplified block diagram of LArASIC. Shows Global and Channel Registers, 6-b Pulser, and Analog Monitor at top. Each channel (I0~I15) feeds a CA (charge amplifier) → Shaper → AC/DC → Buffer → outputs OP0~OP15 / ON0~ON15. CH0 is highlighted. A "Bias module with BGR and Temp. Sensor" sits at the bottom.

The ASIC is programmable with a total of 1024 different configurations possible for each channel's gain, peaking time, baseline selection, adaptive-reset quiescent currents, ac/dc coupling and single-ended (SE) or single-ended-to-differential conversion (SEDC) buffer enable. With I0~I15 inputs the ASIC makes the analog amplitudes available at the pins OP0~OP15 with SEDC disabled and OP0~OP15 as well as ON0~ON15 when SEDC is enabled. When the SEDC is selected, the outputs ON0~N15 are set in the high impedance state. The ASIC has in total 144 configuration register bits, 2 global and 16 channel registers each 8 bit long. All the required bias voltages are generated internally, on-chip using BJT bandgap reference. The output of the shaper or buffers (OP for SEDC) or temperature can be observed through the analog monitor output.

A simplified block diagram of the LArASIC channel is as shown in Fig. 2. The charge input to the LARASIC is amplified with the help of a dual-stage charge amplifier, with a gain of 20 and the selectable gain from the {3/5/9/16} set for the 1st and 2nd stage, respectively.

> **Figure 2:** A simplified block diagram of LArASIC channel.

A 5th order shaping amplifier with complex conjugate poles converts the charge to voltage and performs shaping to maximize the SNR. The output of the shaper can be accessed with DC or AC coupling with 100 μs HPF time-constant. The buffer block consists of selectable single-ended (SE) or single-ended-to-differential conversion (SEDC) buffer capable of driving subsequent COLDADC stage.

A brief synopsis along with specifications of the LArASIC are summarized in Table 1. The power consumption of the various subsystems of LArASIC is summarized in Table 2.

### Table 1. LArASIC specifications and functionality

| Parameter | Value |
|---|---|
| Technology | 180 nm CMOS – 1-poly, 6-metal, MiM cap, silicide block resistors |
| Supply Voltage | 1.8 V |
| Temperature Range | 77 – 300 K (-196 – 27 °C) optimized for 87k (-186 °C) |
| Max Single-Ended Output Swing | 1.4 V peak to peak (low level 0.2 – high level 1.6 V) |
| Gain Selection (mV/fC) | 4.7 / 7.8 / 14 / 25 |
| Full-Scale Input Charge (fC) | 300 / 180 / 100 / 56 |
| Baseline selection | 200 mV (collection mode); 900 mV (induction/non-collection mode) |
| Charge Preamplifier Polarity | Negative (collection mode); Both (induction/non-collection mode) |
| Adaptive-Reset Current Selection (nA) | 0.1 / 0.5 / 1 / 5 |
| Shaper Peaking Time Selection (µs) | 0.5 / 1 / 2 / 3 (given as 5% rise to peak time) |
| Output Coupling | AC (100 μs HPF time-constant); DC |
| Output Selection | Shaper / SE buffer / SEDC buffer |
| Total Channel Settings | 1024 |
| Integrated Test Charge Injection Cap. | 200 fF |
| Temperature Sensor | 0.8728 V @ 25°C + 2.868 mV/°C |
| Integrated Pulse Generator | 6-bit DAC based (with optional slope matching with Ch0 gain) |
| Configuration Control | SPI interface with 144 register bits |

The gain selection and full-scale input charge correspond column-by-column as follows:

| Gain Selection (mV/fC) | 4.7 | 7.8 | 14 | 25 |
|---|---|---|---|---|
| Full-Scale Input Charge (fC) | 300 | 180 | 100 | 56 |

### Table 2. Summary of LArASIC power consumption

| Category | Item | Power |
|---|---|---|
| Channels | without buffer | ~ 6 mW/ch |
| Channels | with single-ended buffer | ~ 10 mW/ch |
| Channels | with differential buffer | ~ 12 mW/ch |
| Channel subsystems | Input MOSFET | ~ 3.9 mW |
| Channel subsystems | Charge Amp. | ~ 0.8 mW |
| Channel subsystems | Shaper | ~ 1 mW |
| Channel subsystems | SE buffer | ~ 4 mW |
| Channel subsystems | SEDC buffer | ~ 6 mW |
| Common Circuitry | | ~ 4 mW |
| Total Power Consumption | without buffer | ~ 100 mW |
| Total Power Consumption | with single-ended buffer | ~ 164 mW |
| Total Power Consumption | with differential buffer | ~ 196 mW |

### Updates to this version:

- RQI subtraction in CA2n disconnected for guaranteed functionality at cold
- SEDC stability and CM noise rejection improved with modifications to the CMFB circuit along with addition of RC filter on each channel's common-mode reference (VOCM)
- Charge injection DAC linearity improved along with optional slope matching with Ch0 gain
- Soft connected Vsso to Vss internally to remove body biasing while improving substrate noise rejection. Hence, Vsso pads (41, 42, 79 and 80) are now Vss

## LArASIC Layout and Packaging

The top-level layout with pad information and bonding diagrams are shown in Fig. 3 and Fig. 4, respectively. LArASIC has in total of 100 pads and will be packaged in the LQFP128 package. Table 3 presents layout and pad information and Table 4 presents the pin and pad list of LArASIC, respectively.

> **Figure 3:** LArASIC P5 layout with I/O pad names.

### Table 3. Layout and pad information

| Parameter | Value |
|---|---|
| Layout size | 7.28 x 5.7 mm² |
| Die cut size | 7.4 x 5.9 mm² |
| Pad count | 100 |
| Pad size | 78.04 x 78.04 µm² |
| Pad pitch | 192 µm (left side), 157.36 µm (right side) and 292.32 µm (top/bottom) |

### Table 4. Information of pads and pins of LArASIC

| Num. Pins/Pads | Pin Num. | Pad Num. | Signal Name | In/Out | Description |
|---|---|---|---|---|---|
| 4 | 7, 8, 25, 26 | 1, 2, 19, 20 | VDDP (3, 2, 1, 0) | | Analog supply for the 1st stage of the charge amplifiers: +1.8V. VDDP0 (ch0~ch3), VDDP1 (ch4~ch7), VDDP2 (ch8~ch11), VDDP3 (ch12~ch15) |
| 21 | 37, 38, 41, 45, 46, 49, 50, 57, 58, 103, 104, 107, 108, 111, 112, 115, 116, 119, 120, 123, 124 | 21, 22, 25, 29, 30, 33, 34, 41, 42, 79, 80, 83, 84, 87, 88, 91, 92, 95, 96, 99, 100 | VSS | | Analog ground: 0 V |
| 16 | 39, 40, 43, 44, 47, 48, 51, 52, 109, 110, 113, 114, 117, 118, 121, 122 | 23, 24, 27, 28, 31, 32, 35, 36, 85, 86, 89, 90, 93, 94, 97, 98 | VDD | | Analog supply: +1.8 V |
| 4 | 59, 60, 101, 102 | 43, 44, 77, 78 | VDDO | | Analog supply for output buffer: +1.8 V |
| 16 | 9~24 | 3~18 | Charge Inputs I (15~0) | In | DC or AC coupled charge input from the detector. ESD protected (mild) |
| 32 | 65~96 | 45~76 | O(0~15){N, P} | Out | Channel analog output, ex., O5N and O5P are channel 5 outputs. ESD protected |
| 1 | 42 | 26 | VBGR | | Bandgap reference monitor. ~1.18V at room temp |
| 1 | 53 | 37 | SDI | In | CMOS level. Digital serial data input. ESD protected |
| 1 | 54 | 38 | CK | In | CMOS level. Clock for shift registers. ESD protected |
| 1 | 55 | 39 | CS | In | CMOS level. On the falling edge of CS, data is latched into the shift registers. ESD protected |
| 1 | 56 | 40 | RST | In | CMOS level. Global active low reset. ESD protected |
| 1 | 105 | 81 | SDO | Out | CMOS level. The output of the shift register. Tri-stated with CS. ESD protected |
| 1 | 106 | 82 | TEST | In | Test pulse input. DAC output, Monitor output. ESD protected |
| 100 | | | Total pins/pads | | |

> **Figure 4:** Bonding diagram in the LQFP128 package.

Package details:

- **Package Name:** LQFP128
- **Package Cavity Size:** 9.5 x 9.5 mm²
- **Downbond-to-substrate package-pin numbers:** 37, 41, 45, 49, 112, 116, 120, 124
- **Min. bond pad size X:** 78.04 µm
- **Min. bond pad size Y:** 78.04 µm
- **Min. pad pitch:** 157.36 µm
- **Min. pad spacing:** 79.32 µm

## Configuration Registers

The ASIC has two 8-bit global shift registers and sixteen channel shift registers (each 8-bits long). The ASIC has four global configuration inputs: Clock (CK), Chip Select (CS), Reset (RST), and Serial Data Input (SDI); and one global configuration output: Serial Data Output (SDO). The serial data map is shown in Fig. 5.

> **Figure 5:** Serial data map. SDI feeds, in order: Global Reg. 2 → Global Reg. 1 → Ch0 Reg. → Ch1 Reg. → Ch2 Reg. → ... → Ch15 Reg. → SDO. Each register block is driven by CK, CS, RST.

> **Figure 6:** A depiction of clock and other control signals along with power-on-reset (POR) and smart-reset (iRST) signals at room and cold temperatures. Transient response plot (captured Thu Apr 8 13:49:30 2021) showing signals /Vdd, /ck, /cs, /rst, POR, iRST, iSCK, iTCK, each plotted from -0.1 to 1.9 V over time 0.0–10.0 ms, for corners TSMC_v12_25 (room) and TSMC_v12_m189 (cold).

There are three ways to generate reset signal (iRST), whose example is also depicted in Fig. 6.:

1. Firstly, the reset (iRST) is automatically generated when the chip powers-up, known as power-on-reset (POR)
2. With the reset pin (RST), reset signal can be sent from outside
3. A Reset, known as smart-reset is also generated internally with a CS pulse if CK is kept high. The duration of the reset is from the falling-edge of CS to the falling edge of CK.

Also shown in Fig. 6 is an example of the internal signals iSCK and iTCK, which are CS-controlled configuration clock and CS-controlled test pulse clock, respectively. The test pulse clock is needed for the internal pulser as explained later in the Pulser Section.

An 8-bit shift register, and the register map is as shown in Fig. 7. As shown in Fig. 8, the 8-bit register subsystem consists of 8 D flip-flops on the bottom and 8 D flip-flops on the top, in total 16 D flip-flops are present. The outputs of first 8 D flip-flops are s0*, s1*, …, s7* are available only internally. The outputs of the other 8 are s0, s1, …, s7, which are the main outputs are available at the configuration pins.

> **Figure 7:** An 8-bit shift register and register map.

> **Figure 8:** Register subsystem with 16 D flip-flops.

As shown in Fig. 9, at the falling edge of each CK, the configuration data (sdi) is serially shifted into the first group of 8 internal shift registers (s0*, s1*, …, s7*). At the falling edge of CS, the data is latched from the shift registers to the configuration pins (s0, s1, …, s7). Edges on CS should not coincide with CK to setup-time violation. The output of each shift register is serially available through its SDO pin, which is a buffered version of s7*.

The shift register mechanism is as explained below:

- Data is shifted into the load shift register on the rising edge of CK while CS is high.
- The MSB is shifted into position s0* on the first rising edge of CK.
- The LSB is shifted into position s0* on the 8th rising edge of CK.
- The MSB is shifted out of SDO on the 9th rising edge of CK.
- The LSB is shifted out of SDO on the 16th rising edge of CK.

NOTE: The default value of each register is 000.

> **Figure 9:** A depiction of SPI configuration mechanism along with various control signals. Transient response plot (captured Mon Apr 12 12:48:44 2021) showing /sdi, /ck, /cs, internal taps /I15/s0*–/I15/s7*, and latched outputs /s0–/s7 and /sdo over time 5.0–15.0 ms.

### Global Register Configuration:

The main global register depicted as Global Reg. 1 in Fig. 5 is as shown in Fig. 10. Apart from that, another 8-bit global configuration register is depicted as Global Reg. 2 in Fig. 5 is used for the DAC control and is explained later in the DAC section.

The first bit of the global register (Global Reg. 1) is unused and is reserved and hence depicted as RES. Bit STB sets Channel 0 to monitor either the analog channel signal or the temperature/bandgap reference (dedicated by bit STB1). Bit SLK sets the leakage current of each channel to either 100 pA or 500 pA. Bit SLKH increases the leakage current by a factor 10. It is summarized as shown in Table 5.

> **Figure 10:** The main Global register of LArASIC. Bit order LSB → MSB: SGP, SDD, SDC, SLKH, S16, STB, STB1, SLK.

### Table 5. Global register description

| Global Register Bit | Name | Description |
|---|---|---|
| 0 | SGP | Bit used to disable DAC gain matching with the gain setting of Ch0 (SG0, SG1). 0 – enabled; 1 – disabled. Explained further in the DAC section. |
| 1 | SDD | Bit used to enable SEDCs in all channels. 0 – disabled; 1 – enabled. Explained further in the buffer control section. |
| 2 | SDC | Output coupling. 0 – dc coupling; 1 – ac coupling |
| 3 | SLKH | Reset Quiescent Current (RQI) increases by a factor of 10. 0 – disabled; 1 – enabled |
| 4 | S16 | Enable high filter in ch15 (16th channel). 0 – disabled; 1 – enabled |
| 5 | STB | 0 – Monitor analog channel signal; 1 – Monitor temperature or bandgap reference. |
| 6 | STB1 | 0 – Monitor temperature; 1 – Monitor bandgap reference. |
| 7 | SLK | Reset Quiescent Current (RQI) setting. 0 – 500 pA RQI; 1 – 100 pA RQI |

### Channel Register Configuration:

Each channel register has 8 bits: STS, SNC, SG0, SG1, ST0, ST1, SDC, and SDF as depicted in Fig. 11.

- STS enables the 200 fF test capacitor individually for each channel. The analog test pulse can be applied through pin TEST. The pin can be terminated (50 Ohm) when not connected to a pulse generator.
- SNC selects the baseline to either 200 mV (for a unipolar pulse in collecting mode) or 900 mV (for a bipolar pulse in induction/non-collecting mode).
- The channel gain can be independently adjusted to 4.7, 7.8, 14, or 25 mV/fC, through two dedicated bits (SG0 and SG1).
- The peaking time of each channel can be set independently to 0.5, 1, 2, or 3 µs through two dedicated bits (ST0 and ST1).
- SDF sets the output buffer to either selected or bypassed (also powered down).

> **Figure 11:** Channel register present in each of the LArASIC channel. Bit order LSB → MSB: STS, SNC, SG0, SG1, ST0, ST1, SMN, SDF.

Table 6. summarizes channel register settings.

### Table 6. Channel register description and possible configurations

| Channel Register Bit | Name | Description |
|---|---|---|
| 0 | STS | Test capacitance. 0 – disabled; 1 – enabled |
| 1 | SNC | Baseline selection. 0 – 900 mV (for non-collecting mode); 1 – 200 mV (for collecting mode). |
| 2:3 | SG (0,1) | Gain selection. 00 – 14 mV/fC; 10 – 25 mV/fC; 01 – 7.8 mV/fC; 11 – 4.7 mV/fC |
| 4:5 | ST (0,1) | Peak time selection. 00 – 1.0 µs; 10 – 0.5 µs; 01 – 3 µs; 11 – 2 µs |
| 6 | SMN | Output monitor enable. 0 – monitor disabled; 1 – monitor enabled: channel output routed to Test pad. Conflict configurations exist and are discussed in the DAC section. |
| 7 | SDF | Explained in the next section (Buffer Control Configuration) |

### Buffer Control Configuration:

With the addition of single-ended-to-differential conversion (SEDC) buffer (starting with LArASIC P4) in addition to the pre-existing single-ended (SE) buffer, the buffer control configuration mechanism is as depicted in Fig. 12. and the corresponding three possible scenarios are shown in Table 7.

> **Figure 12:** Depiction of buffer control configuration. Shaper → AC/DC → switch SW (Out_SH, position 1) feeds; path 2 → SE Buf → Out_SE; path 3 → SEDC Buf → OutP_SEDC / OutN_SEDC each through a 165 Ohm resistor. SMN selects the monitor (OM). Outputs OutP and OutN.

### Table 7. Buffer control configuration for the three different scenarios

| Scenario | SDD (Global reg.) | SDF (Channel Reg.) | SW | Power Down | OutP | OutN |
|---|---|---|---|---|---|---|
| 1 | 0 | 0 | Close | SE & SEDC | Out_SH | High Z |
| 2 | 0 | 1 | Open | SEDC | Out_SE | High Z |
| 3 | 1 | X | Open | SE | OutP_SEDC | OutN_SEDC |

## On-Chip DAC and Pulse Generator

The ASIC contains a 6-bit Current Scaling DAC and a pulse generator for the test and calibration of the front-end channels.

In LArASIC P5 the DAC gain is matched to the gain setting of Ch0 (SG0, SG1), which can be overridden with SGP global register bit as shown in Table 8.

### Table 8. Pulser DAC programmability

| SGP (Global bit) | Channel 0 Register SG0 | Channel 0 Register SG1 | Gain Selection (mV/fC) |
|---|---|---|---|
| 0 | 0 | 0 | 14 |
| 0 | 1 | 0 | 25 |
| 0 | 0 | 1 | 7.8 |
| 0 | 1 | 1 | 4.7 |
| 1 | X | X | 4.7 |

The specifications of the DAC are as shown in Table 9 and as follows:

- Power: 1 mW
- Temperature Range: 27 °C to -200 °C
- Settling time: < 130 ns
- Target Linearity: < + 0.1 %

### Table 9. Pulser DAC specifications for the four gain settings

| Parameter | | | | |
|---|---|---|---|---|
| Full-Scale Input Charge (fC) | 300 | 180 | 100 | 56 |
| Gain each stage (mV/fC) | 4.7 | 7.8 | 14 | 25 |
| Injected Charge | 238 | 180 | 100 | 56 |
| Peak to Peak Voltage | 1.2 | 0.9 | 0.5 | 0.28 |
| RFS (kΩ) | 10 | 7.68 | 4.27 | 2.39 |

Where RFS is the resistor used to program the gain.

Global register 2 is added before the first one to provide the inputs for the DAC as depicted in Fig. 13

> **Figure 13:** Global register 2 used for DAC control. Bit order LSB → MSB: SDAC0, SDAC1, SDAC2, SDAC3, SDAC4, SDAC5, SDACSW1, SDACSW2.

- **sdac0 ~ sdac5:** 6-bit input to the DAC where sdac0 is the LSB and sdac5 is the MSB
- **sdacsw1:** 0 – test input to the channels is disconnected from the external test pin. 1 – test input to the channels is connected to the external test pin.
- **sdacsw2:** 0 – test input to the channels is disconnected from the DAC output. 1 – test input to the channels is connected to the DAC output.

Do not use SMN with SDACSW1 and/or SDACSW2 high. Do not enable more than one monitor at a time. The following are the conflict configurations:

1. SMN+SDACSW1 – will short the channel output with the injection input
2. SMN+SDACSW1+SDACSW2 – will short the channel output with the DAC output

The output of the DAC is fed to a pulse generator that is controlled by CK clock input to generate the output voltage pulse. Rising edge of clock injects positive charge while falling edge injects negative. The scheme is as shown in Fig. 14.

> **Figure 14:** On-chip DAC and pulse generator.

Fig. 15 shows typical DAC output characteristic at room and cold temperatures.

> **Figure 15:** DAC output characteristic at room and cold temperatures.

> **Figure 16:** Simulated outputs (shaper, outP, outN) for all the four peaking time settings in induction mode (left) with 900 mV baseline, and collection mode (right) with 200 mV baseline. Load = 20 pF || 250 kΩ, temperature = 77K, Cdet = 150 pF. Channel settings: RQI = 500 pA (SLK = 0, SLKH = 0), SEDC enabled (SDD = 1), gain = 14 mV/fC (SG = 00), DC coupling (SDC = 0). (Left plot captured Tue Sep 1 22:31:30 2020; right plot captured Tue Sep 1 20:56:04 2020.)

Fig. 17 shows the expected ENC.

> **Figure 17:** Simulated ENC of the channel without SE or SEDC Buffers. The ENC with SE or SEDC stays same. Load = 20 pF || 250 kΩ, temperature = 77K, Cdet = 150 pF. Channel settings: gain = 14 mV/fC (SG = 00), DC coupling (SDC = 0). ENC values from the plots:
>
> | RQI / Peaking time | 0.5 µs (100 pA) | 1 µs (500 pA) | 2 µs (1 nA) | 3 µs (5 nA) |
> |---|---|---|---|---|
> | ENC (e-) for 200 mV BL | 553.1 | 421.9 | 368.3 | 371 |
> | ENC (e-) for 900 mV BL | 556.2 | 423.2 | 368.7 | 371.5 |

Simulations of the channel linearity are presented in Fig. 18 and Fig. 19 for the channel with SE buffer and SEDC buffer, respectively. Triangular charge input pulses mimicking the physics signals are used for the simulation, example input and output plots are shown in Fig. 20.

> **Figure 18:** Typical corner simulation of dynamic nonlinearity of channel with SE buffer for the peaking time of 2µs at 25 ℃ with BSIM4.5 models (top) and -189 ℃ with PSP models (bottom). Load = 20 pF || 250 kΩ, Cdet = 150 pF. Channel settings: RQI = 500 pA (SLK = 0, SLKH = 0), SE enabled (SDD = 0, SDF = 1), gain = 14 mV/fC (SG = 00), DC coupling (SDC = 0)

> **Figure 19:** Typical corner simulation of dynamic nonlinearity of channel with SEDC buffer for the peaking time of 2µs at 25 ℃ with BSIM4.5 models (top) and -189 ℃ with PSP models (bottom). Load = 20 pF || 250 kΩ, Cdet = 150 pF. Channel settings: RQI = 500 pA (SLK = 0, SLKH = 0), SE enabled (SDD = 1, SDF = X), gain = 14 mV/fC (SG = 00), DC coupling (SDC = 0).

> **Figure 20:** Example of input and output signals for measuring the linearity of the FE.

## Appendix A: Pin and Pad Information

### Table 10. Left side package pins and silicon pads information

| Pad Number | Pad Name | X Center (µm) | Y Center (µm) | Pin Number | Pin Name | Comments |
|---|---|---|---|---|---|---|
| 1 | VDDP3 | 39.02 | 5047.665 | 7 | VDDP3 | |
| 2 | VDDP2 | 39.02 | 4855.665 | 8 | VDDP2 | |
| 3 | I15 | 39.02 | 4663.665 | 9 | I15 | |
| 4 | I14 | 39.02 | 4471.665 | 10 | I14 | |
| 5 | I13 | 39.02 | 4279.665 | 11 | I13 | |
| 6 | I12 | 39.02 | 4087.665 | 12 | I12 | |
| 7 | I11 | 39.02 | 3895.665 | 13 | I11 | |
| 8 | I10 | 39.02 | 3703.665 | 14 | I10 | |
| 9 | I9 | 39.02 | 3511.665 | 15 | I9 | |
| 10 | I8 | 39.02 | 3319.665 | 16 | I8 | |
| 11 | I7 | 39.02 | 2643.715 | 17 | I7 | |
| 12 | I6 | 39.02 | 2451.715 | 18 | I6 | |
| 13 | I5 | 39.02 | 2259.715 | 19 | I5 | |
| 14 | I4 | 39.02 | 2067.715 | 20 | I4 | |
| 15 | I3 | 39.02 | 1875.715 | 21 | I3 | |
| 16 | I2 | 39.02 | 1683.715 | 22 | I2 | |
| 17 | I1 | 39.02 | 1491.715 | 23 | I1 | |
| 18 | I0 | 39.02 | 1299.715 | 24 | I0 | |
| 19 | VDDP1 | 39.02 | 1107.715 | 25 | VDDP1 | |
| 20 | VDDP0 | 39.02 | 915.715 | 26 | VDDP0 | |

### Table 11. Bottom side package pins and silicon pads information

| Pad Number | Pad Name | X Center (µm) | Y Center (µm) | Pin Number | Pin Name | Comments |
|---|---|---|---|---|---|---|
| 21 | VSS | 227.445 | 39.02 | 37 | VSS | Downbond-to-substrate |
| 22 | VSS | 519.765 | 39.02 | 38 | VSS | |
| 23 | VDD | 812.085 | 39.02 | 39 | VDD | |
| 24 | VDD | 1104.405 | 39.02 | 40 | VDD | |
| 25 | VSS | 1396.725 | 39.02 | 41 | VSS | Downbond-to-substrate |
| 26 | VBGR | 1689.045 | 39.02 | 42 | VBGR | |
| 27 | VDD | 1981.365 | 39.02 | 43 | VDD | |
| 28 | VDD | 2273.685 | 39.02 | 44 | VDD | |
| 29 | VSS | 2566.005 | 39.02 | 45 | VSS | Downbond-to-substrate |
| 30 | VSS | 2858.325 | 39.02 | 46 | VSS | |
| 31 | VDD | 3150.645 | 39.02 | 47 | VDD | |
| 32 | VDD | 3442.965 | 39.02 | 48 | VDD | |
| 33 | VSS | 3735.285 | 39.02 | 49 | VSS | Downbond-to-substrate |
| 34 | VSS | 4027.605 | 39.02 | 50 | VSS | |
| 35 | VDD | 4319.925 | 39.02 | 51 | VSS | |
| 36 | VDD | 4612.245 | 39.02 | 52 | VDD | |
| 37 | SDI | 4904.565 | 39.02 | 53 | SDI | |
| 38 | CK | 5196.885 | 39.02 | 54 | CK | |
| 39 | CS | 5489.205 | 39.02 | 55 | CS | |
| 40 | RST | 5781.525 | 39.02 | 56 | RST | |
| 41 | VSS | 6073.845 | 39.02 | 57 | VSS | |
| 42 | VSS | 6366.165 | 39.02 | 58 | VSS | |
| 43 | VDDO | 6658.485 | 39.02 | 59 | VDDO | |
| 44 | VDDO | 6950.805 | 39.02 | 60 | VDDO | |

### Table 12. Right side package pins and silicon pads information

| Pad Number | Pad Name | X Center (µm) | Y Center (µm) | Pin Number | Pin Name | Comments |
|---|---|---|---|---|---|---|
| 45 | O0N | 7240.11 | 414.5 | 65 | O0N | |
| 46 | O0P | 7240.11 | 571.86 | 66 | O0P | |
| 47 | O1N | 7240.11 | 729.22 | 67 | O1N | |
| 48 | O1P | 7240.11 | 886.58 | 68 | O1P | |
| 49 | O2N | 7240.11 | 1043.94 | 69 | O2N | |
| 50 | O2P | 7240.11 | 1201.3 | 70 | O2P | |
| 51 | O3N | 7240.11 | 1358.66 | 71 | O3N | |
| 52 | O3P | 7240.11 | 1516.02 | 72 | O3P | |
| 53 | O4N | 7240.11 | 1673.38 | 73 | O4N | |
| 54 | O4P | 7240.11 | 1830.74 | 74 | O4P | |
| 55 | O5N | 7240.11 | 1988.1 | 75 | O5N | |
| 56 | O5P | 7240.11 | 2145.46 | 76 | O5P | |
| 57 | O6N | 7240.11 | 2302.82 | 77 | O6N | |
| 58 | O6P | 7240.11 | 2460.18 | 78 | O6P | |
| 59 | O7N | 7240.11 | 2617.54 | 79 | O7N | |
| 60 | O7P | 7240.11 | 2774.9 | 80 | O7P | |
| 61 | O8N | 7240.11 | 2932.26 | 81 | O8N | |
| 62 | O8P | 7240.11 | 3089.62 | 82 | O8P | |
| 63 | O9N | 7240.11 | 3246.98 | 83 | O9N | |
| 64 | O9P | 7240.11 | 3404.34 | 84 | O9P | |
| 65 | O10N | 7240.11 | 3561.7 | 85 | O10N | |
| 66 | O10P | 7240.11 | 3719.06 | 86 | O10P | |
| 67 | O11N | 7240.11 | 3876.42 | 87 | O11N | |
| 68 | O11P | 7240.11 | 4033.78 | 88 | O11P | |
| 69 | O12N | 7240.11 | 4191.14 | 89 | O12N | |
| 70 | O12P | 7240.11 | 4348.5 | 90 | O12P | |
| 71 | O13N | 7240.11 | 4505.86 | 91 | O13N | |
| 72 | O13P | 7240.11 | 4663.22 | 92 | O13P | |
| 73 | O14N | 7240.11 | 4820.58 | 93 | O14N | |
| 74 | O14P | 7240.11 | 4977.94 | 94 | O14P | |
| 75 | O15N | 7240.11 | 5135.3 | 95 | O15N | |
| 76 | O15P | 7240.11 | 5292.66 | 96 | O15P | |

### Table 13. Topside package pins and silicon pads information

| Pad Number | Pad Name | X Center (µm) | Y Center (µm) | Pin Number | Pin Name | Comments |
|---|---|---|---|---|---|---|
| 77 | VDDO | 6950.805 | 5668.16 | 101 | VDDO | |
| 78 | VDDO | 6658.485 | 5668.16 | 102 | VDDO | |
| 79 | VSS | 6366.165 | 5668.16 | 103 | VSS | |
| 80 | VSS | 6073.845 | 5668.16 | 104 | VSS | |
| 81 | SDO | 5781.525 | 5668.16 | 105 | SDO | |
| 82 | TEST | 5489.205 | 5668.16 | 106 | TEST | |
| 83 | VSS | 5196.885 | 5668.16 | 107 | VSS | |
| 84 | VSS | 4904.565 | 5668.16 | 108 | VSS | |
| 85 | VDD | 4612.245 | 5668.16 | 109 | VDD | |
| 86 | VDD | 4319.925 | 5668.16 | 110 | VDD | |
| 87 | VSS | 4027.605 | 5668.16 | 111 | VSS | |
| 88 | VSS | 3735.285 | 5668.16 | 112 | VSS | Downbond-to-substrate |
| 89 | VDD | 3442.965 | 5668.16 | 113 | VDD | |
| 90 | VDD | 3150.645 | 5668.16 | 114 | VDD | |
| 91 | VSS | 2858.325 | 5668.16 | 115 | VSS | |
| 92 | VSS | 2566.005 | 5668.16 | 116 | VSS | Downbond-to-substrate |
| 93 | VDD | 2273.685 | 5668.16 | 117 | VDD | |
| 94 | VDD | 1981.365 | 5668.16 | 118 | VDD | |
| 95 | VSS | 1689.045 | 5668.16 | 119 | VSS | |
| 96 | VSS | 1396.725 | 5668.16 | 120 | VSS | Downbond-to-substrate |
| 97 | VDD | 1104.405 | 5668.16 | 121 | VDD | |
| 98 | VDD | 812.085 | 5668.16 | 122 | VDD | |
| 99 | VSS | 519.765 | 5668.16 | 123 | VSS | |
| 100 | VSS | 227.445 | 5668.16 | 124 | VSS | Downbond-to-substrate |
