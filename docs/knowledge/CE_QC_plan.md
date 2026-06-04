# DUNE FD1-HD TPC Electronics and FD2-VD Bottom Drift Electronics (BDE) Quality Control Plan

> Source: /Users/chaozhang/Library/CloudStorage/OneDrive-BrookhavenNationalLaboratory/Work/CE/CE Knowledge Database/QC procedures/CE_QC_plan.pdf
> Converted: 2026-06-04 (full-text extraction)

Long-Baseline Neutrino Facility (LBNF) / Deep Underground Neutrino Experiment (DUNE) - US

LBNF/DUNE-US — DUNE FD1-HD Time Projection Chamber (TPC) Electronics and FD2-VD Bottom Drift Electronics (BDE) Quality Control Plan

Document Number: EDMS 2815079

## Document Approvals

| Signatures Required | Signature & Date Approved |
|---|---|
| Originator: David C. Christian | |
| Approver: Vladimir Tishchenko | |
| Approver: Cheng-Ju Stephen Lin | |
| Approver: Eric James | |
| Approver: Steve Kettell | |
| Approver: Kevin Fahey | |

## Revision History and Version Control

This version of the document may not be the current or approved revision. The current revision is maintained in the Engineering & Equipment Data Management Service (EDMS) where internal Project document approvals are managed. EDMS can be accessed through the web at https://edms.cern.ch. This document can be identified by the revision date as indicated in the Version Control Table below.

The current approved version is always available in EDMS.

| Version | Author | Revision Date | Location | Description of Changes |
|---|---|---|---|---|
| 0.1 | David Christian | 01/12/2023 | | Added location of FEMB, WIB, & PTC QC tests to original draft |
| 1.0 | David Christian | 01/19/2023 | EDMS 2815079 | Added CRP patch panel section, revised cold cable section, revised WIEC section, PTB section, feedthrough flange section, WIEC assembly section, & spool piece section with input from Hucheng. This is the first version in EDMS |
| 1.1 | Anne Heavey | 1/25/2023 | | Reformatted per new standard |
| 1.2 | David Christian | 2/6/2023 | | Replaced "Purpose" with DUNE standard text. |
| 1.3 | V. Tishchenko | 05/04/2023 | | Misc. changes including restructuring of section 4. |
| 2.0 | V. Tishchenko | 07/09/2025 | | Streamlining the document into a more compact version and reorganizing various sections into separate standalone documents. |
| 2.1 | V. Tishchenko | 10/30/2025 | | Addressing recommendations of FD CE/HVS Bias-Voltage Supplies & Cables PRR: all cold bias cables will be tested. |
| 2.2 | V. Tishchenko | 01/08/2025 | | Updating QC plan for PL506 – burn-in test will be performed by the vendor. |

## List of Figures

- Figure 1: Cold power cable daisy-chained test setup.
- Figure 2: Cold cable daisy chain test board
- Figure 3: Test of two 22m cold power cables and two Samtec cold data cables
- Figure 4: Feedthrough assembly leak test setup

## List of Tables

- Table 1: PTC QC items
- Table 2: Definitions
- Table 3: Acronyms

(Note: in-document table/figure numbering as it appears in the source text; the source's List of Tables and List of Figures sections used differing numbering — the numbers above follow the captions actually printed at each table/figure in the body.)

## 1 PURPOSE AND SCOPE

### 1.1 Purpose

The purpose of this Quality Control Plan is to outline the strategy and methodology for managing product and process variations, ensuring the delivery of high-quality parts of DUNE TPC readout electronics (aka Cold Electronics or CE) that meet the requirements of the DUNE experiment. Detailed descriptions of QC processes for individual components are provided in separate standalone documents.

### 1.2 Scope

The methodology of CE QC includes the following components:

- **Supplier Quality Management** – Evaluating and managing supplier quality to ensure consistency in raw materials and components.
- **Process Control** – Monitoring and controlling production processes to maintain consistency and prevent defects.
- **Inspection and Testing** – Evaluating products, components, or processes to ensure they meet specified standards.
- **Standards and Specifications** – Establishing clear quality benchmarks and compliance requirements.
- **Corrective and Preventive Actions** – Identifying, addressing, and preventing defects or non-conformities.
- **Staged design** – Implementing a structured, multi-phase process for custom-built products that includes design validation through prototyping, prototype testing, and a systematic review process at key stages: conceptual, preliminary, and final design.
- **Pre-production validation** – Fabrication and QC testing of pre-production quantity of final design products.
- **Documentation and Record Keeping** – Maintaining detailed records of QC activities for traceability and compliance. The CE consortium uses DUNE HardWare DataBase (HWDB) for record keeping of QC test progress and results, as well as tracking the production, shipping and installation of various components.
- **Training and Competency** – Ensuring personnel are adequately trained to maintain quality standards.
- **Continuous Improvement** – Implementing feedback loops and data analysis to enhance processes and reduce defects over time.
- **Reporting** – Providing updates to DUNE upper management and the DUNE Project Quality Assurance Manager on production and QC progress; designating a QC representative for each testing site.
- **Tiered approach** – Conducting QC testing at multiple levels, including individual CE components, sub-assemblies, and system-level integration of the final product.

The QC of FD1-HD and FD2-VD TPC detector electronics involves

- For custom built products: selection of manufacturers that are reputable in the industry and certified to meet quality standards required by the responsible institution. For example, a BNL-QA-101 form is applied to all vendors if the purchase order is made by BNL Procurement & Property Management Division (PPM).
- For off-the-shelf items: selection of quality components from reputable vendors.
- Designing and producing tools and equipment for QC testing.
- Developing the software for QC testing.
- Developing and documenting the QC testing procedures and acceptance criteria.
- Developing assembly, handling, installation, shipping, transportation, etc. procedures.
- Analyzing the information collected during the QC processes.
- Recording the test results to DUNE HardWare DataBase (HWDB) and archiving the raw data from QC tests for future references.
- Reviewing the results of QC process at regular intervals and developing corrective actions.
- Feeding back the QC testing information to manufacturers to implement corrective actions and achieve the required quality level of deliverables.
- Coordinating the work between different QC testing sites; assuring that the QC procedures are applied uniformly across the various sites involved in detector construction, installation, and integration.
- Organizing QC meetings to share experience between different testing sites, discuss problems, develop corrective action, etc.
- Reviewing and, if necessary, updating the QC testing procedures.

The QC plan for mechanical components includes

- QC certificates from the vendor, if applicable (e.g. results of leak tests).
- Sample testing of items from each batch (visual inspection, measurements of critical dimensions, fit testing, etc.) by responsible institutions.
- Testing of sub-assemblies (e.g. leak testing of assembled CE flanges prior to shipping for installation in DUNE detectors).

## 2 Representatives and Responsibilities

### 2.1 Technical Lead

Name: D. Christian (Fermilab)

Responsibilities:

- Oversee inspection and tests for quality performance.
- Provide periodic assessment of fabrication field inspection, oversight, testing, commissioning, and acceptance.
- Review inspection and test data for accuracy and completeness.
- Interface with LBNF/DUNE QA Manager on Consortia QA/QC related matters.
- Make or arrange for inspections to be performed by the Consortium.
- Monitor the status of all required testing based on the testing plan and log.
- Check certifications of materials and equipment delivered to the site, spot check workmanship, observe testing procedures.
- Review rework items list, testing plan and log, etc.
- Issue non-conformance report for deficiencies observed by the Consortium.
- Maintain and monitor the issues and actions document.

### 2.2 Consortium Lead

Name: C-J Lin (LBNL)

Responsibilities:

- Ensure compliance with this quality plan for their areas of responsibility including flow down of requirements and awareness.
- Ensure integration of the QA Program requirements into Project processes.
- Responsible for appropriate quality planning, allocating adequate resources for work, and for implementing quality requirements in their respective organizations.
- Establish adequate and transparent performance metrics to monitor the performance of the Project.
- Ensure sub-project managers have the authority, responsibility, and is held accountable for integrating quality into processes and programs.
- Responsible for assessing the efficacy and robustness of processes within areas of responsibility and resolving gaps to prevent substandard performance or achievement of goals/objectives.
- Responsible for the effectiveness of this QA Program by establishing adequate assurance processes and practices in their areas of responsibility.

### 2.3 Consortium QC Representative

Name: J. Paley (Fermilab)

Responsibilities:

- Oversee the installation inspection and tests for Quality performance.
- Provide periodic assessment of fabrication/testing field inspection, oversight, QC testing, commissioning, and acceptance.
- Review the inspection and test data for accuracy and completeness.
- Interface with the LBNF DUNE QA Manager on Consortia QA/QC related matters.
- Make or arrange for inspections to be performed by the Consortium.
- Monitor the status of all required testing based on the Testing Plan and Log.
- Check certifications of materials and equipment delivered to the site, spot check workmanship, observe testing procedures. Review rework items list, testing plan and log, etc.
- Issue Nonconformance Report for deficiencies observed or the Consortia has not been corrected within 24 hours or entered in a Rework Items List.
- Maintain and Monitor the Rework Items List.

### 2.4 Institutional QC representatives

1. Alex Sousa (University of Cincinnati)
2. Frank Krennich (Iowa State University)
3. Martin Tzanov (Louisiana State University)
4. David Warner (Colorado State University)
5. Ciro Riccio (Stony Brook University)
6. Ed Kearns (Boston University)
7. Josh Klein (University of Pennsylvania)
8. Cheng-Ju Lin (Lawrence Berkeley National Laboratory)
9. Jon Paley (Fermi National Laboratory)
10. Vladimir Tishchenko (Brookhaven National Laboratory)
11. Kendall Mahn (Michigan State University)
12. Jianming Bian (University of California at Irvine)

Responsibilities:

- **Develop and Document Site-Specific QC Procedures** — Adapt and document quality control procedures specific to the local QC site, based on the overarching collaboration-wide CE QC procedures.
- **Implement Procedure and Criteria Updates** — Ensure timely adoption and implementation of updates to QC procedures, acceptance criteria, and testing protocols.
- **Plan and Schedule QC Activities** — Coordinate and plan the QC testing workflow at the site to align with project timelines and resource availability.
- **Oversee QC Operations** — Provide general oversight of the quality control processes and workflow at the testing site to ensure efficient and consistent operations.
- **Liaise with CE Consortium QC Representative** — Report regularly to the CE consortium QC representative, ensuring transparent communication and coordination.
- **Manage Nonconformities** — Document any nonconforming components or processes and promptly report them to the CE QC representative. Ensure proper routing of such parts for rework or further investigation.
- **Ensure Compliance with the CE QC Plan** — Monitor adherence to the established CE QC plan and schedule, taking corrective actions when necessary.
- **Maintain QC Equipment** — Ensure the proper functionality of QC test equipment, including performing calibrations as needed to maintain accuracy and reliability.
- **Ensure Proper Data Recording** — Verify that all QC data is accurately and consistently recorded in the Hardware Database (HWDB).
- **Manage Logistics** — Oversee logistics workflows related to component tracking, movement, and storage within the QC process.
- **Enforce Safety Standards** — Ensure that all personnel follow required safety procedures, including electrostatic discharge (ESD) protection and general lab safety protocols.
- **Attend QC Coordination Meetings** — Participate in meetings organized by the CE QC representative to stay informed of developments and maintain alignment with the collaboration.
- **Provide Feedback and Suggestions** — Offer input and suggestions for improving the CE QC process based on site-specific experience and observations.

## 3 Document Control

### 3.1 Design Files

All design files, including schematics, layout, BOM, and other relevant files, must be finalized and uploaded to CERN EDMS before the production phase begins. An initial design validation should be performed to confirm the correctness. After that, the design files should be locked, and any modification should be reviewed and approved by the CE consortium.

Design files related to FD1-HD can be found at: https://edms.cern.ch/project/CERN-0000193828

Design files related to FD2-VD can be found at: https://edms.cern.ch/project/CERN-0000214653

For all printed circuit boards, design files include:

- Schematics in native and pdf format,
- Layout files in native format,
- PCB fabrication package, including Gerber (GBR) and drill files,
- Assembly package, including bill of materials (BOM), Gerber files, and position files, as well as any specific assembly instructions, and
- Other relevant files like a list of substitutes, assembly quotes or PCB fabrication quotes.

For Spool pieces, WIECs, cable strain relief fixtures, module front panels and enclosures, and cable management systems, design files include 3D models in native format and drawings in pdf format.

For custom cables, a list of requirements as well as either specification sheets or test results demonstrating that the parts meet requirements, must be uploaded to EDMS.

For commercial off the shelf parts, including cables, power supplies, and detector safety system modules, a list of requirements and specification sheets demonstrating that the items meet requirements, must also be uploaded to EDMS.

### 3.2 Firmware and Software

Firmware and software developed for testing and for normal running in DUNE shall be maintained in Git repositories that are or can be made accessible to all DUNE collaborators.

## 4 Components Requiring QC Inspection and Test

The equipment produced for FD1-HD and FD2-VD are almost identical. These consist of:

- ASICs used in Front End Motherboards (FEMBs)
- FEMBs
- Cold Electronics (CE) boxes for FEMBs
- Patch panels to be mounted on CRPs (for FD2-VD)
- Cable trays and associated hardware to be mounted on APAs (for FD1-HD)
- Cold cables to power, control, and read out the FEMBs
- Warm Interface Boards (WIBs)
- Power and Timing Cards (PTCs)
- Feedthrough printed circuit boards
- Feedthrough flanges and associated cable strain relief fixtures
- Warm Interface Electronics Crates (WIECs)
- Power and timing backplanes (PTBs) for WIECs
- Filter boards and boxes that mount on the WIECs
- WIEC fan and filter assemblies
- Cryostat penetration spool pieces and associated cable strain relief fixtures.
- Commercial off-the-shelf power supplies, cables, and safety system components.

The Frontend Electronics MotherBoard (FEMB) is the most upstream as well as the major electronics component instrumenting DUNE TPC detectors. It consists of a Printed Circuit Board (PCB) stuffed with custom-built ASICs and off-the-shelf discrete electronics components. The PCB is installed into custom-built aluminum encloser which provides mechanical protection and RF shielding to the electronics.

Once the DUNE detectors are installed inside the cryostat at SURF, only limited access to the detector components will be available to the CE consortium. After the temporary construction opening (TCO) is closed, no access to detector components will be available; therefore, FEMBs and power and data cables should be constructed to last the entire lifetime of the experiment (20 years). This puts very stringent requirements on the reliability of these components. All detector components installed inside the cryostat will be thoroughly QC tested and sorted before they are prepared for integration with other detector components prior to installation. All other CE components can be replaced, if necessary, even while the detector is in operation. Regardless, every component will be tested before it is installed in Sanford Underground Research Facility (SURF) to ensure smooth commissioning of the detector.

The selection and procurement of discrete electronics components for FEMB (as well as for other CE deliverables) will be overseen by electronics engineer at BNL to ensure that quality components from reputable vendors characterized for operation in LAr are used. The quality of deliverables from external companies must be demonstrated during the preliminary and final design stages.

The ASICs will be produced by Taiwan Semiconductor Manufacturing Company (TSMC), one of the leading companies in semiconductor industry. Each FEMB uses three types of ASICS: analog frontend chips (LArASIC), analog-to-digital converters (ColdADC) and control and communication ASICs (COLDATA). The LArASIC is the most sensitive electronics component which can be damaged by ElectroStatic Discharge. Therefore, special handling procedures must be observed and special protective equipment may be need for LArASIC chips and FEMBs during various stages of assembling, testing, installation and transporting, which are provided in [1] ("ESD Protection", EDMS:2782612). The robotic chip testing station (RTS) mitigates the risk of chip damage by ESD by minimizing human intervention into the chip testing process (see EDMS:CERN-0000260416).

The dicing and packaging of ASICS is a standard procedure performed by the semiconductor manufacturing industry. It will be performed by external companies. Each packaged chip will have a unique serial number printed on it. The information is recorded to HWDB on chip origin (wafer batch number). Each PCB has its own serial number (QR code) printed for associating FEMBs with ASICS. Finally, each COLDATA chip has e-fuses for serial number encoding and FEMB identification through software.

All ASICs will be tested both at room temperature and, depending on the yield, a fraction of chips will be tested in liquid nitrogen temperature using RTS.

The RTS will be equipped with optical system and image recognition software for automated readout of chip serial numbers off the chip packages. Thus, the test results will be associated with ASIC chips by serial number automatically by RTS software, which minimizes risks of human mistakes. The test reports will be produced for each tested chip for each test and provided for subsequent transfer to central DUNE HWDB. Only ASICs that pass this QC step will be used in the assembly of FEMBs.

Based on experiences at ProtoDUNE-SPs, discrete components like resistors and capacitors need not undergo cryogenic testing before they are installed on the FEMBs.

The PCBs for FEMBs (and other CE components like WIBs, PTCs, etc.) will be manufactured by external companies that meet the quality standard required by DUNE and the responsible institution. A trial run of a small amount must be performed before the large purchase. Each PCB of FEMB will have a QR code printed on either side. This QR code will be used as FEMB ID number.

The installation of electronics components on PCBs (surface mount components, ASICs, FPGAs, connectors, etc. for the FEMBs, WIBs, PTCs, etc.) is performed by certified external companies chosen based on past experience with FEMB assembling during previous R&D stages.

The assembled FEMBs will be tested both at room temperature and at liquid nitrogen temperature. The FEMBs passed both tests will be provided for installation on DUNE detectors. Pictures of either side of each FEMB will be taken to automatically associate PCBs with ASICs (by QR code on PCB and serial numbers on the ASICs) at a dedicated station instrumented with image recognition software.

The fabrication of aluminum FEMB enclosures is performed by an external machine shop. We will perform sample testing of enclosures from each batch.

The mechanical assembly of FEMBs (installation into enclosures) is performed at BNL by qualified trained technicians. The assembly procedure specifies torque values for bolted connections. Some mechanical connections provide electrical connection between FEMB ground plane and metal enclosure, which require special hardware. The assembly procedure gives necessary instructions for these.

The TPC electronics consortium plan involves having multiple sites using the same QC procedure. The choice of distributing the testing activities among multiple institutions has been made based in part on the experience gained with ProtoDUNE-SP, where all associated testing activities were concentrated at BNL. While this approach had some advantages, like the direct availability of the engineers that had designed the components, a strict conformance to the testing rules, and a fast turn-around time for repairs, it also required a very large commitment of personnel from a single institution. Personnel from other institutions interested in TPC electronics participated in the test activities but could not commit for long periods of time. For this reason, we are planning to distribute the QC testing activities for ASICs and FEMBs among multiple institutions belonging to the TPC electronics consortium. It should be noted that this approach is used in the LHC experiments for detector components like the silicon tracker modules where both the assembly and QC activities take place in parallel at multiple (of the order of ten) institutions. To avoid problems during most of the production phase, training as well as documentation of QA should be emphasized. To ensure that all sites produce similar results, we will emphasize training experienced personnel that will overview the test activities at each site, and we will have reference FEMBs that will be initially used to cross-calibrate the test procedures among sites and then to check the stability of the test equipment at each site. All FEMB test activities will be monitored by a member of the management of the TPC electronics consortium who will also have the responsibility of training the personnel at all sites and conducting site inspections to ensure that all safety and testing rules and procedures are applied uniformly. The yields of the production will be centrally monitored and compared among different sites.

All other electronics components, including the cold cables, will be tested at room temperature only. It is not necessary to test the cables at cryogenic temperature since the cable resistivity and insertion loss is much lower cold than warm. All cables will be QC tested at the production site. We will do sample testing of a few per cent of cables as a cross-check.

Stringent requirements must be applied to cryostat penetrations to avoid argon leaks. The cryostat penetrations have two parts: the first is the crossing tube with its spool pieces, and the second one is the three flanges used for connecting the power, control, and readout electronics to the CE and PDS components inside the cryostat. On each cryostat penetration there are two flanges for the CE and one for the PDS. The crossing tubes with their spool pieces are fabricated by industrial vendors and pressure-tested and tested for leaks by other vendors. The flanges are assembled by institutions that are members of the TPC electronics and PDS consortia; the flanges must undergo both electrical and mechanical tests to ensure their functionality. Electrical tests comprise checking all the signals and voltages to ensure they are passed properly between the two sides of the flange and that there are no shorts. Mechanical tests involve pressure-testing the flange itself, including checking for leaks. Further leak tests are performed after the cryostat penetrations are installed on the cryostat and later after the TPC electronics and PDS cables are attached to the flanges. These leak tests are performed by releasing helium gas in the cryostat penetration and checking for the presence of helium on top of the cryostat. Similar tests were performed during the ProtoDUNE-SP installation. More details will be provided in section 4.

An important step in CE QC process is the integration testing of CE components mounted to DUNE detector modules (APA or CRP). These tests will verify all electrical connections between CE and detector elements, determine if the noise level is at the expected level and all detector channels are functioning as expected. The observed anomalies, if any, will be checked against detector non-compliance reports. Observed deviations from expectations will need to be resolved in cooperation with other consortia (APA, CRP, etc.).

The final step in CE QC process is system testing of CE installed in DUNE far detector cryostats at SURF and connected to other systems (DAQ, power plant, slow control and safety system). The WIECs will be assembled and tested with all the WIBs and PTC installed. Testing requires a slice of the DAQ back-end, power supplies, and at least one FEMB to check all connections. All cables between the bias voltage supplies and the end flange, as well as all the cables between the low-voltage power supplies and the PTCs will be tested for electrical continuity and for shorts. All power supplies will undergo a period of burn-in with appropriate loads before being installed in the cavern. All test equipment used for qualifying the components to be installed in the detector will be either transported to SURF or duplicated at SURF to be used as diagnostic tools during operations.

### 4.1 ASICs

All ASICs will be tested both at room temperature and, depending on the observed yield, a fraction of chips will be tested at liquid nitrogen temperature using a robotic testing system (RTS) instrumented with a universal ASIC test board, WIB with standard firmware and dedicated testing software. The test board will reproduce the entire detector readout chain with all three types of ASICs involved (LArASIC, ColdADC and COLDATA), like regular FEMB. Unlike FEMB, the test board will be instrumented with several ADCs for monitoring all ASICs power rails, test DACs, replaceable ASIC sockets, e-fuse programming hardware for serial number encoding in COLDATA chips. Only ASICs that pass this QC step will be used in the assembly of FEMBs. Chips that fail the test will be retested one or more times to ensure that the failure is not due to the test setup itself.

Given the large number of ASICs required for DUNE detectors, the QC activities will be distributed among multiple institutions within the CE consortium. All tests will be performed in accordance with a standardized set of procedures to ensure consistency across sites.

#### 4.1.1 LArASICs

LArASIC QC plan and procedures are available in EDMS:3284638.

##### 4.1.1.1 Location

LArASIC QC will be performed at

- BNL
- MSU

##### 4.1.1.2 Justification

QC tests of LArASIC parts from the engineering run indicate that the yield of packaged parts is very high (~99%). However, even 99% yield would imply that ~8% of FEMBs would fail QC tests and require rework because of a bad LArASIC if individual chip QC tests are not done. If the yield is 99.9%, the fraction of FEMBs that would need to be reworked would be less than 1%. If the LArASIC yield proves to be high enough, we will reconsider the decision to individually test every chip. Similarly, if the fraction of LArASICs that fail QC tests at LN2 temperature after passing at room temperature is low enough (~0.1%), we will likely decide to do cryogenic testing only for a fraction of the chips.

##### 4.1.1.3 Data to HWDB

The following will be included in the hardware database entry for each LArASIC:

- Serial number
- Location of test
- QC test results

For additional details, see EDMS:3284638.

#### 4.1.2 ColdADCs

ColdADC QC plan and procedures are available in EDMS:3303611.

##### 4.1.2.1 Location

ColdADC testing will be done at

- Louisiana State University (LSU)
- LBNL.

##### 4.1.2.2 Justification

QC tests of ColdADC parts from the engineering run indicate that the yield of packaged parts is very high (~99%). However, even 99% yield would imply that ~8% of FEMBs would fail QC tests and require rework because of a bad ColdADC if individual chip QC tests are not done. If the yield is 99.9%, the fraction of FEMBs that would need to be reworked would be less than 1%. If the ColdADC yield proves to be high enough, we will reconsider the decision to individually test every chip. Similarly, if the fraction of ColdADCs that fail QC tests at LN2 temperature after passing at room temperature is low enough (~0.1%), we will likely decide to do cryogenic testing only for a fraction of the chips.

##### 4.1.2.3 Data to HWDB

The results of QC measurements described in EDMS:3303611 will be stored in the HWDB combined with

- chip serial number
- QC site name
- operator name
- date
- test conditions (at cold/warm temperature).

For more details see EDMS:3303611.

#### 4.1.3 COLDATAs

Tests of the COLDATA ASIC include verification of both the control and high-speed data output links using actual length cables.

The COLDATA QC plan and procedures are available in EDMS:3298044.

##### 4.1.3.1 Location

COLDATA testing will be done at

- Fermilab
- UC-Irvine

##### 4.1.3.2 Justification

QC tests of COLDATA parts from the engineering run indicate that the yield of packaged parts is very high (~99%). However, we would like to assign each COLDATA a serial number (using the eFUSE bits) that will allow us to unambiguously check the cabling of each FEMB. The additional work required to do a quick warm test of COLDATA as well as write the eFUSE bits is minimal, so unless the COLDATA yield is determined to be extremely high (~99.9%) we will do warm QC tests for every chip. If the fraction that fail QC tests at LN2 temperature after passing at room temperature is low enough (~0.25%), we will likely decide to do cryogenic testing only for a fraction of the chips.

##### 4.1.3.3 Data to HWDB

For each COLDATA chip an entry will be created in HFDW indicating

- QC PASS/FAIL status
- chip serial number
- QC site name
- operator name
- date
- test conditions (cold/warm).
- Additional test results will be recorded for chips that pass the QC test (e.g. locking range for the PLL, eye diagram, etc.).

For more details refer to EDMS:3298044.

### 4.2 FEMB

Each Front-End Motherboard (FEMB) includes 8 LArASIC chips, 8 ColdADC chips, and 2 COLDATA chips. The FEMB designs for FD1-HD and FD2-VD are functionally identical, differing only in the type of data cable connector used and the specific layout of mounting holes. FEMBs intended for FD1-HD additionally require an adapter board to allow vertical mounting. Only ASICs that have successfully passed the quality control (QC) tests, as described above, will be installed on FEMB printed circuit boards (PCBs).

Like other CE boards, the FEMB PCB fabrication and assembly will be performed by two independent external companies. This approach allows us to have greater quality control over the WIB fabrication process and over materials and components being used.

Vendors of components (other than the ASICs) must be certified to meet quality standards required by the responsible institution (BNL). A BOM along with an assembly note should be provided at the same time for the assembly house. The assembly note will emphasize the instruction of soldering of the data connector.

FEMB QC consists of the following steps:

1. Reception check of bare PCBs (visual inspection, QC documentation review).
2. Reception check of assembled boards (visual inspection, serialization, checkout testing).
3. Functionality testing at room temperature.
4. Functionality testing at cryogenic temperature (in liquid nitrogen)

For details see EDMS:3284637.

#### 4.2.1 Location

The FEMBs will be QC tested at the following sites:

- BNL
- Fermilab
- Cincinnati
- Iowa State
- Louisiana State University (LSU)

#### 4.2.2 Justification

Testing the FEMBs is a necessary step to ensure that the electronics components and the entire assembly operate properly both at room temperature and under design conditions (in cryogenic liquid). Testing in warm requires significantly less time than testing in cold. If FEMB already fails the warm test, there is no point in taking it to the next QC step, which saves time.

QC testing of each FEMB prior to installation on the DUNE detector is essential to ensure that the Cold Electronics meet the performance requirements of the experiment. Certain issues, such as noisy channels, can be difficult to diagnose once the FEMB is installed, as it becomes challenging to distinguish between detector-related and electronics-related defects (e.g. noisy channels). Moreover, the process of removing and reinstalling a FEMB, followed by cold testing of the entire APA or CRP, involves significant turnaround time (FEMB removing from the detector, reinstalling on detector, cold testing of the entire APA or CRP) and poses a risk of potential damage to the detector. Thorough pre-installation testing minimizes these risks and helps ensure reliable operation of the CE system within DUNE.

#### 4.2.3 Data to HWDB

Record measured values described in EDMS:3284637, pass/fail status, links to raw data, histograms, plots, test conditions. Note that FEMBs will be identified automatically by serial numbers encoded in COLDATA chips w/o the need of human intervention, and the links between test results and FEMBs will be established by testing software.

Cold testing will be performed at the same QC testing sites as warm testing – BNL, Fermilab, Cincinnati, Iowa State, and U. of Florida.

#### 4.2.4 Non-Conformance Handling

FEMBs failed the test will be sent to BNL for investigation / rework.

#### 4.2.5 Storing and shipping

Each FEMB/CE box assembly (including a CR adapter board for FD1-HD) that passes QC tests will be:

- Labelled with a serial number. The serial number should be unique so that its information can be located from the database if needed
- Bagged in an ESD static shielding bag
- Packed in a foam box to protect damage from collision
- Stored in the environment with humidity and temperature control
- Recorded before and after transportation

#### 4.2.6 Reception at SURF

##### 4.2.6.1 Description

The FEMBs that pass QC tests at FEMB QC testing sites, will be shipped to installation sites (SURF in the case of FD1-HD, or CRP production sites in the case of FD2-VD). All FEMBs will be QC tested before they are installed on detectors to ensure that no problems were developed in shipping and that FEMBs are functioning prior to installation on the detector. It is a relatively simple check at room temperature that all channels respond to pulser and the noise is at the expected level. This reception test will be performed in the clean room at room temperature using the same single warm interface board (WIB) apparatus as is used for FEMB QC during production. The FEMBs that fail the test will be sent to BNL for investigation/rework.

##### 4.2.6.2 Location

Clean room at SURF (for FD1-HD) or CRP production sites (FD2-VD).

##### 4.2.6.3 Justification

Ensure that no problems developed during shipping and prior to installation on the detector. If not tested, it will be impossible to determine and develop corrective actions if problems developed during shipping or handling/installation of FEMBs.

##### 4.2.6.4 Data to HWDB

Test PASS/FAIL result alone with information on test date and time, location, operator name, channel by channel RMS noise, pulser response, etc.

### 4.3 CRP Patch Panels (FD-2VD)

Each half CRP (CRU) has two patch panels mounted on the composite frame as the interface between 2.5m cables to the CE boxes and 27m cables to the signal feed-through flange. Patch panels are simple PCBs with various connectors and mechanical mounting holes.

#### 4.3.1 Continuity check

##### 4.3.1.1 Description

The QC test will check the continuity to verify the proper population of connectors on the board, which can be done with resistance measurement of data cables and power cables daisy chained together by using a "flange daisy chain test board". The test should be performed at both room temperature and LN2 temperature.

##### 4.3.1.2 Location

QC tests of CRP patch panels will be done at BNL with participation of collaborators from other collaboration institutes.

##### 4.3.1.3 Justification

Good assembly quality of the patch panel is important to ensure the proper connection between CE boxes and feed-through flange. DC measurement is required to verify the proper population of connectors and confirm they'll work reliably at both room temperature and LN2 temperature.

##### 4.3.1.4 Data to HWDB

A total of 320 panel panels are required to instrument BDE on 80 CRPs. Test results of the patch panel, pass or fail, will be stored in the HWDB, together with the serial number and assembly batch.

### 4.4 Cold Data and Power Cables

The custom cables are manufactured by qualified manufacturers which meet the required industry standard with QA/QC. Each cable is tested by the manufacturer to verify that the intended connections are robust and there are no shorts. The cable test will be carried out by the manufacturer using a cable tester with appropriate adapters automatically, a QC report is available for every cable. In addition, power cables have crimped pin receptacles plugged into the connector shrouds; a retention test tool is used to check the proper placement of every pin in the connector body.

Materials used for cold cable production must be under control. Only permitted materials (e.g., wire, connector) are allowed to be used during cable production. On the one hand, the BOM from cable manufacturers will be inspected before production. On the other hand, the reception test procedure will include the cryogenic qualification test.

#### 4.4.1 Sample testing

##### 4.4.1.1 Description

Around 5% of each batch of cold cables will be tested in LN2 a couple of times. Each cable will be visually inspected when it returns to room temperature, no crack or damage is expected because the cables are made with Teflon insulation materials.

The risk of receiving a bad batch of cables will be further mitigated by continuity testing approximately 5% of each batch of cold cables.

The test for cold power cables will be done by a simple daisy chained test setup. The setup includes two mating connectors and two digital multimeters (see Figure 1). Some pins of two mating connectors are shorted in a way to form a daisy chained connection. White wires and black wires are daisy chained independently. As shown in Figure 1 below, measurements are done in such a way that the gauge of wire can be confirmed by resistance per unit (~33 mΩ/m). Each power cable is tested with the same connections as are used in the FEMB and flange board assemblies.

> **Figure 1:** Cold power cable daisy-chained test setup. (image not included)

The test of cold cables will be performed using a "flange daisy chain test board", which is designed to verify the flange board and cold cables. All conductors of two cold data cables and two cold power cables (white wires) are daisy chained together and the total series resistance is measured. The series resistance must be around 164 Ω for two 22 m cold power cables and two 22 m Samtec cold data cables daisy chained together. The series resistance is in compliance with the total resistance from wires of cables which depends on the length, traces on the flange daisy chain test board (fixed value), and contact resistance (< 0.1 Ω per connection).

> **Figure 2:** Cold cable daisy chain test board (image not included)

The flange daisy chain test board (Figure 2) is inserted to a slot of flange board. Each slot has ERF8-60 and ERF8-75 connectors. As shown in Figure 3, the cold cable QC test will be done with the flange daisy chain test board, a WIB adapter board, and a multimeter.

> **Figure 3:** Test of two 22m cold power cables and two Samtec cold data cables (image not included)

##### 4.4.1.2 Location

QC tests of cold cables will be done at BNL with participation of collaborators from other collaboration institutes.

##### 4.4.1.3 Justification

The risk of cable failure is very low because cables are manufactured by qualified manufacturers which meet the required industry standard with QA/QC. All materials used for cold cable production have been verified to be compatible with liquid argon at Fermilab MTS (Material Test Stand). The test of a 5% sample from each batch of cold cables at both room temperature and LN2 temperature is considered sufficient to mitigate the risks.

##### 4.4.1.4 Data to HWDB

The results of cable tests, pass or fail, will be stored in the HWDB, together with the cable type, batch number, and serial number.

#### 4.4.2 Visual inspection

##### 4.4.2.1 Description

Each cable will be inspected during assembling the cables into cable bundles for potential defects which could not be captured by manufacturer's continuity check. Some typical inspection items are: mechanical flaws in connector manufacturing, excessive wire stripping, abnormal epoxy application, etc. Defective cables will not be used for cable bundle production. Simple problems (loose pins) can be fixed by a trained person. Observed problems will be fed back to the manufacturer to develop corrective actions. Depending on the issue, defective cables can shipped back to the manufacturer for rework.

##### 4.4.2.2 Location

At BNL.

##### 4.4.2.3 Justification

Simple visual check during cable bundle does not add much overhead to the production process, but it can save significant amount of time. If not done and a problem is discovered after installation, it will take a significant amount of effort to correct.

##### 4.4.2.4 Data to HWDB

Document observed defects, include pictures.

### 4.5 Cold HV cables

Cold HV cables will be hi-pot tested in argon gas as described in EDMS:3207305.

### 4.6 WIBs

Like other CE boards, the WIB PCB fabrication and assembly will be performed by two independent external companies. This approach allows us to have a greater quality control over the WIB fabrication process and materials and components being used.

#### 4.6.1 PCB reception check

##### 4.6.1.1 Description

The WIB PCB fabrication house must provide a quality certificate for each batch of PCB fabrication. The certificate will include

- Final Product Inspection Report with a list of materials and solder masks found on the product and checks against purchase order requirements, results of measurements of line widths, spacings, BGA, SMT, PCB dimensions (including thickness and warpage), hole sizes, etc.
- Electric test report according to IPC-9252 standard requirements
- Micro-section Analysis Report (copper and soldermask thickness, roughness, defects inspection, etc.).
- Surface Plating Thickness Test Report
- Impedance Test Report
- Solderability Test Report
- Ionic Contamination Test Report
- Thermal Stress Test Report

One extra PCB will be fabricated per each batch to conduct destructive tests. Such PCB cannot be used for assembly. It will be clearly labeled, packaged separately and provided to us along with tin and impedance samples. At reception, each PCB will be quickly inspected as a cross-check, the QR codes will be scanned and each PCB will be registered in HWDB. Boards with problems will be reviewed by an engineer. Problems will be documented and reported back to the manufacturer for developing corrective actions.

##### 4.6.1.2 Location

At BNL.

##### 4.6.1.3 Justification

The reception check is needed to register WIB PCBs in HWDB and associate manufacturer's QC documents with the boards.

##### 4.6.1.4 Data to HWDB

Register PCBs in HWDF, upload manufacturer's QC documents to HWDB and associate them with individual boards.

#### 4.6.2 Post-assemby check

##### 4.6.2.1 Description

For each WIB fabrication batch the PCB assembly house will provide a Quality Certificate with test reports in accordance with the terms and conditions of the contract. The contract will require IPC-A-610 Class 2 of higher quality standard for the assembly and inspection including

- Certification of assembly operators and inspectors.
- 100% inspection of all SMD components using Automatic Optical Inspection equipment.
- Certificate of compliance with hazardous materials free fabrication requirements.
- Certificate of compliance with requirements of fabrication free of hazardous materials.
- Results of ion test purity report.

A visual inspection of every assembled WIB shall be performed before power is turned on. Some typical inspection items are:

- Missing soldering. Sometimes the assembly house may omit the soldering of through hole when a part with both SMD and THRU pins
- Extra soldering paste on board
- Extra components on board
- Insufficient cleaning

Observed problems will be reviewed by electronics engineer, documented and reported back to the assembly house for developing corrective actions. Boards failed the check will be sent back to the assembly house for rework.

##### 4.6.2.2 Location

At BNL.

##### 4.6.2.3 Justification

Visual inspection prior to powering on a board will reduce the risk of non-repairable catastrophic failures due to fabrication defects.

##### 4.6.2.4 Data to HWDB

Test pass / fail result. Document observed problems. Upload quality certificate and test reports from the assembly house to the HWDB and associate them with individual boards.

#### 4.6.3 Functionality check

##### 4.6.3.1 Description

Each WIB will undergo a thorough functionality test prior to providing it for installation at SURF. The QC procedure is designed to ensure the quality of the WIB hardware. It is not intended to verify the WIB firmware or software. The test setup includes a support structure, a PTB, a WIB adapter board, 4 FEMBs and cables, and a DUNE timing system clock source. The QC Sequence is:

1. Visual inspection
2. LTC2977 programming and board power checkout
3. Self-test
4. Final tests

The tests performed in the last two steps of the QC sequence are detailed in Table 3 [WIB QC items table below]. The firmware and software for the self-test are provided on an SD card. When a WIB is turned on with the SD card inserted, the test firmware and software will be loaded automatically. A TCP/IP connection to the WIB will be used to monitor the self-test and receive results to be stored in the hardware database.

**WIB QC items**

| Test item | Description | Expected output |
|---|---|---|
| WIB Power management (hardware dongle) | Validate all WIB power rails are operational and are in expected range through LTC2977 power management IC | Use "LT powerplay" software and DC1613A dongle for verification |
| FPGA initialization testing | SD Card & JTAG programming of the FPGA | Front panel LED & UART status |
| TCP/IP communication | The TCP/IP connection is built between the WIB and the host PC | WIB pass "ping" test |
| On-board power measurement (Linux interface) | Voltage/current of each power rail through software monitoring (I2C) LTC2991 and LTC2990 | In the expected range |
| On-board I2C devices detection | FPGA detects all on-board I2C devices | All I2C devices work |
| FEMB power management | Voltage/current of each power rail can be set/monitored | In the expected range |
| Communication between WIB & FEMB (FEMB interface) | WIB ←→ WIB adapter board ←→ 4 FEMBs: I2C command, Fast command, Clock, Data links, External calibration path (FEMBs are configured to accept external calibration pulser control by WIB) | Receive correct data pattern from FEMBs |
| FEMB calibration/monitor verification | On board DAC8411, ADC, and external calibration verification | An external calibration source should be used to calibrate the ADC which then can be used to verify the on board DAC for each FEMB |
| DDR check | Read/write, burst mode | Pass or fail software test |
| PTB interface | 12V power from PTB; Receive system clock from PTB; Identify WIB address | Verify all connections to PTB |
| Timing interface | Verification of all timing paths front and back panel connections. Will also verify ADN2814 and SI5344 functions. Back panel connection will require PTB & PTC or a test dongle. | FPGA can generate a pass or fail for timing chain |
| IBERT test | Vivado IBERT tool; TX ←→ fiber ←→ RX | Can't be done by self-checkout test. This can be done using test firmware but some development will be required. |

All problems will be investigated by a dedicated electronics engineer and corrective actions will be developed on case by case basis.

##### 4.6.3.2 Location

WIB QC testing will be done at SBU and at Boston University.

##### 4.6.3.3 Justification

Bench testing of WIB functionality is necessary to ensure that only fully functional electronics f installed at SURF. If not tested and a problem is observed at SURF, it will be harder to localize and debug.

##### 4.6.3.4 Data to HWDB

Pass/fail status, results of measurements of various values from section 4.6.3.1, a note on observed problems.

### 4.7 PTCs

The PTC distributes power to up to 6 WIBs in a WEIC, distributes a synchronized timing datastream to all WIBs, and acts as an interface with the SC and DDSS. The QC procedure will ensure that the PTC is assembled properly, and that all physical interfaces are usable. The QC procedure will not exhaustively check all firmware and software functionality of the PTC.

Like other CE boards, the PTC PCB fabrication and assembly will be performed by two independent external companies. This approach allows us to have a greater quality control over the PTC fabrication process and materials and components being used.

#### 4.7.1 PCB reception check

##### 4.7.1.1 Description

The PTC PCB fabrication house must provide a quality certificate for each batch of PCB fabrication. The certificate will include

- Final Product Inspection Report with a list of materials and solder masks found on the product and checks against purchase order requirements, results of measurements of line widths, spacings, BGA, SMT, PCB dimensions (including thickness and warpage), hole sizes, etc.
- Electric test report according to IPC-9252 standard requirements
- Micro-section Analysis Report (copper and soldermask thickness, roughness, defects inspection, etc.).
- Surface Plating Thickness Test Report
- Impedance Test Report
- Solderability Test Report
- Ionic Contamination Test Report
- Thermal Stress Test Report

One extra PCB will be fabricated per each batch to conduct destructive tests. Such PCB cannot be used for assembly. It will be clearly labeled, packaged separately and provided to us along with tin and impedance samples. At reception, each PCB will be quickly inspected as a cross-check, the QR codes will be scanned and each PCB will be registered in HWDB. Boards with problems will be reviewed by an engineer. Problems will be documented and reported back to the manufacturer for developing corrective actions.

##### 4.7.1.2 Location

U. Pennsylvania.

##### 4.7.1.3 Justification

The reception check is needed to register PTC PCBs in HWDB and associate manufacturer's QC documents with the boards.

##### 4.7.1.4 Data to HWDB

Register PCBs in HWDF, upload manufacturer's QC documents to HWDB and associate them with individual boards.

#### 4.7.2 Post-assembly check

##### 4.7.2.1 Description

For each PTC fabrication batch the PCB assembly house will provide a Quality Certificate with test reports in accordance with the terms and conditions of the contract. The contract will require IPC-A-610 Class 2 of higher quality standard for the assembly and inspection including

- Certification of assembly operators and inspectors.
- 100% inspection of all SMD components using Automatic Optical Inspection equipment.
- Certificate of compliance with hazardous materials free fabrication requirements.
- Certificate of compliance with requirements of fabrication free of hazardous materials.
- Results of ion test purity report.

A visual inspection of every assembled PTC shall be performed before power is turned on. Some typical inspection items are:

- Missing soldering. Sometimes the assembly house may omit the soldering of through hole when a part with both SMD and THRU pins.
- Extra soldering paste on board
- Extra components on board
- Insufficient cleaning

Boards [failed the check will be sent back to the assembly house for rework — text truncated in source]

##### 4.7.2.2 Location

U. Pennsylvania.

##### 4.7.2.3 Justification

Visual inspection prior to powering on a board will reduce the risk of non-repairable catastrophic failures due to fabrication defects.

##### 4.7.2.4 Data to HWDB

Test pass / fail result. Document observed problems. Upload quality certificate and test reports from the assembly house to the HWDB and associate them with individual boards

#### 4.7.3 Functionality check

##### 4.7.3.1 Description

The functionality test of PTCs will be performed using a dedicated WIEC crate with WIBs connected to FEMBs with the total load expected under normal operation of PTCs in DUNE. To test PTC communication with external devices, it will be connected to a clock master via fiber cable, to a PC via network interface and to DDSS devices through EtherCAT. The following functions will be tested:

- supply the voltage to the PTB
- communication with WIBs through PTB
- receiving and distribution of clock signal
- communication through Ethernet with Slow Control master
- communication through EtherCAT with DDSS devices

Identified problems will be investigated by an electronics engineer.

A more complete description of a test setup for PTC functionality check includes:

- The device under test (DUT)
- A WIEC
- A PTB manufactured 2022 or later (to have the correct functional pinouts for PTCv4)
- Up to 6 WIBs (preferred) – although a single WIB can be installed in all 6 slots one-by-one, this will require a much larger labor investment.
- Cables: 48V in, micoUSB for serial connection, 3x multimode fiber pairs for front panel connections, JTAG over a standard 10-pin Xilinx connector, RJ-45 cables for debug Ethernet and optical converter Ethernet
- A microSD card of 32GB that can be formatted for test software
- An Infineon KITXMCLINKSEGGERV1TOBO1 debug pod, and a Xilinx Platform Cable USB II, for programming the EtherCAT controller and FPGA debug, respectively
- The following SFPs for front panel connections: 100Base-FX (DDSS), 1000Base-LX (SC), 1000Base-BX (timing)
- A DUNE timing system clock source

The QC Sequence is:

1. Visual inspection
2. Boot FPGA using a prepared microSD card
3. Self-test of voltage rails and I2C
4. External interface tests of GbE and EtherCAT
5. WIB interface tests
6. Final tests

The tests performed in steps 2 – 5 of the QC sequence are detailed in Table 1 [PTC QC items table below]. The firmware and software for the self-test are provided on an SD card. When a PTC is turned on with the SD card inserted, the test firmware and software will be loaded automatically. A TCP/IP connection to the PTC will be used to monitor the self-test and receive results to be stored in the hardware database.

**Table 1: PTC QC items**

| Test item | Description | Expected output |
|---|---|---|
| FPGA initialization testing | SD Card & JTAG programming of the FPGA | Front panel LED & UART status indicate success |
| Power validation (PTC only) | Validate all PTC power rails are operational and are in expected range through LTC2945 current/voltage monitors. This also partially validates the I2C bus. | Software will indicate pass/fail based on expected output of 48V and 12V measurements. Manual measurement to be made in case of failure. |
| Power validation (with WIBs) | A WIB will be installed in each PTC slot. Each WIB will be powered up by PTC, and the current consumption read. | Status over PTC TCP/IP connection will show that WIB is powered on. |
| TCP/IP communication | An Ethernet connection between PTC and SFP0, and debug RJ-45 connection | PTC pass "ping" test |
| I2C test | In addition to the power monitor test, the I2C test will also read the 3 on-board temperature monitors, and on-board EEPROM | Temperatures in reasonable range for ambient conditions, EEPROM serial number write passes |
| EtherCAT test | A link to Beckhoff TwinCAT EtherCAT master software will be established between SFP1 and a PC. The XMC4300 EtherCAT controller will be programmed with the Infineon debug pod before this test (the programming is retained after this step.) | TwinCAT recognizes PTC on the EtherCAT bus, measurement information can be transferred from PTC->TwinCAT, and TwinCAT can send a status code back to PTC and be read over register read |
| Timing test (PTC only) | The timing signal can be received and locked onto by the PTC. This will also include distributing a test clock from the on-board SoC, and exercising the MUX and level translator using the FPGA pins. | A status LED on the front panel indicates timing lock |
| Timing test (with WIBs) | A WIB will be installed in each PTC slot, and the timing stream will be routed through PTC hardware, over the PTB, and to the WIB receiver. This also validates the timing priority encode lines over the PTB. | The WIB will lock onto the timing stream, and can report its round-trip time through the PTC back to the DUNE timing master. The status will be read over the WIB TCP/IP or UART connection, or over the PTC I2C bus. |
| Backplane addressing | PTC will read its own DIP switch 8-bit address through firmware, and WIB will read the same 8-bit address through firmware | Pass/fail software test |
| DDR check | Read/write, burst mode | Pass/fail software test |
| External register and ALARM test | Power monitors will be written with register values that cause ALARM lines to be asserted. This ensures lines to not have errors in board manufacturing or pullup resistor value | Pass/fail software test |
| Reset test | FPGA and EtherCAT controller will be able to be reset via on-board pushbutton and over console. Both can be reprogrammed over TCP/IP. | Pass/fail software test |

##### 4.7.3.2 Location

PTC QC testing will be done at U. Pennsylvania.

##### 4.7.3.3 Justification

Functionality testing is needed to ensure that fully functioning boards are provided for installation at SURF. PTCv4 has a number of complex interfaces that will need to be running in the detector. The GbE and EtherCAT interfaces require an initial programming to make them functional. QC testing ensures these interfaces undergo a rudimentary test before PTC is installed.

The main DC-DC converters that power WIBs are BGA footprint components that need to be installed correctly in order to function. In addition, small assembly errors like wrong resistor values can affect voltages generated and the state of interfaces. QC testing here ensures correct assembly.

Since the PTC is the primary interface to WIB, QC testing with a real number of WIBs ensures that there are no assembly or quality errors that prevent WIBs from powering up once PTC is installed.

##### 4.7.3.4 Data to HWDB

Test pass/fail result for various tests. Results of measurements of various monitors (e.g. output voltages).

### 4.8 Feedthrough Flanges

The feedthrough flange consists of a customized ConFlat flange blank on which a printed circuit board is mounted. A commercial ConFlat flange blank will be machined by a contract machine shop to accept a TPC electronics feedthrough flange printed circuit board, SHV connectors, a gas purge valve, cable strain relief fixtures, and a WIEC.

#### 4.8.1 Reception check

##### 4.8.1.1 Description

Each ConfFlat flange will be visually inspected at receiving. Some inspection items include: quality of the knife (should not have scratches or dents). Defective items will be shipped back to the manufacturer for rework.

##### 4.8.1.2 Location

At BNL.

##### 4.8.1.3 Justification

Ensure quality of parts prior to making assemblies.

##### 4.8.1.4 Data to HWDB

Register flanges in HWDB. Record observed defects. Visual inspection pass/fail status.

#### 4.8.2 Leak check

##### 4.8.2.1 Description

After partial assembly, all flanges will be pressure tested to 20 PSIG (4 times the maximum allowable working pressure of the GTT membrane cryostat, per ASME BPV code). They will also be Helium leak tested. The leak check setup is shown in Figure 4. All feedthrough assemblies must be leak tight to better than 10⁻⁹ mbar-liters/sec. Flanges that do not meet this specification will be reworked.

> **Figure 4:** Feedthrough assembly leak test setup (image not included)

##### 4.8.2.2 Location

Feedthrough flanges will be assembled and tested at BNL.

##### 4.8.2.3 Justification

All cryostat feedthroughs must be pressure safe and leak tight. The leak rate must be low because the liquid argon filtration system does not remove nitrogen and nitrogen contamination will reduce the prompt argon scintillation light signal.

##### 4.8.2.4 Data to HWDB

150 signal feed-through flanges are required to instrument FD1-HD and 80 signal feed-through flanges are required to instrument FD2-VD. Test results of the flange boards, pass or fail, and signal feed-through assembly leak rate will be stored in the HWDB, together with the serial numbers of flange board and flange.

### 4.9 Power and Timing Backplanes (PTBs)

The PTB is a printed circuit board that distributes 12V power from the PTC in a warm interface crate (WIEC) to the WIBs. It also distributes the timing signal and includes lines that allows the PTC to communicate with the WIBs using I2C protocol. The PTB consists only of traces and connectors. No independent PTB QC, other than visual inspection, will be done by CE consortium members until the PTB is integrated into a flange/WIEC/PTB assembly.

The QC of TPC is part of WIEC QC, see EDMS:3349589.

### 4.10 Warm bias filters

The QC of warm bias filters is now part of WIEC QC, see EDMS:3349589.

### 4.11 Feedthrough Flange/WIEC/PTB Assembly

A WIEC is assembled using metal parts machined to order. WIECs will be assembled at BNL. After the signal feed-through flange assembly passes leak check, a PTB and a WIEC are mounted on the warm side of a feed-through flange. Fans and heaters/RTDs will be installed at the same time. Warm bias filter boards and enclosures are installed on two sides of WIEC. Cable support fixtures are mounted on the cold side of the flange.

QC testing will be done after WIEC assembly and integration with a PTB and a feedthrough flange. A traveler to keep the assembly record of signal feed-through and WIEC is necessary and will be put in the shipment of the signal feed-through assembly.

For a detailed description of WIEC QC refer to EDMS:3349589.

### 4.12 Cable trays

TBD

### 4.13 Cable strain relief fixtures

TBD

### 4.14 X-shape spool pieces

CE cryostat signal penetration assembly with cable clamping plates and CE cross shape spool piece will be fabricated by outside manufacturers. Designs will have been validated with mockup tests in B902 at BNL and ProtoDUNE-II at CERN. 75 penetration assemblies and spool pieces are required to instrument FD1-HD and 40 penetration assemblies and spool pieces are required to instrument FD2-VD. Visual inspection and mechanical measurement of these parts will be performed upon delivery at BNL or South Dakota. In addition, all CE cross shape spool pieces will be leak checked by the manufacturer and a certificate will come with every piece.

#### 4.14.1 Reception check

##### 4.14.1.1 Description

The X-shape spool pieces will be leak tested by the manufacturer and certificates will be provided. Each spool piece will be visually inspected (check for potential damages of CE flange knives, check that the flanges are welded in correct orientation, etc.). Observed problems will be recorded and, if necessary, the items will be returned to the manufacturer for rework.

##### 4.14.1.2 Location

At SURF warehouse.

##### 4.14.1.3 Justification

Items with substantial damages or deviations from specs cannot be installed in DUNE and should be returned to the manufacturer to resolve deficiencies.

##### 4.14.1.4 Data to HWDB

Quality certificates from manufacturer, results of inspection check (checklist), detailed description of observed deficiencies.

### 4.15 Commercial Items to be used outside the cryostats

#### 4.15.1 Description

Commercial data cables will be used between the warm interface electronics and DAQ, timing system, and detector safety system elements. Most of these will be optical fibers. Commercial twisted pair cables will connect commercial power supplies to the PTCs and commercial SHV cables will connect commercial power supplies to the filter boxes mounted on the WIECs.

#### 4.15.2 PL 506 power supplies

Low-voltage power supplies PL506 are COTS items. The units will be procured in two configurations:

1. Units with six (6) independent floating channels (for FD1-HD)
2. Units with four (4) independent floating channels (for FD2-VD)

Each power supply will go through a multistep setup/configuration and test process by the vendor which includes a burn-in with at least 3.5 hours duration:

1. First Isolation Test
2. Commissioning
3. Firmware check/update
4. General MUSE Configuration Guide
5. Programming the MAC Address
6. Setting the Serial Number via SNMP
7. Programming the Serial Number into the USB EEPROM via USB
8. PWM Phase Delay (up to MUSE-2.1.3636.0) or PWM Settings (Alternating MinPeriod) from MUSE-2.3.6151.0
9. Calibrate Voltage if necessary
10. Calibrate Current if necessary
11. Shutdown Test
12. Interlocks and Switches
13. Endurance Test (>=3.5 hours burn-in)
14. Second Isolation Test
15. Final Check

The factory will supply test reports.

The reception inspection at Fermilab will include:

- Visual inspection of shipping crates for possible damage
  - Shipping crates should arrive undamaged.
  - If crate is damaged
    - Problems will be documented and communicated to the vendor / shipping company to agree on the next set of actions (such as, performing a visual inspection of the power supply units, functionality testing, returning to vendor, etc.).
    - Unit damage requires action by the vendor.
  - Verify labeling reflects unit configuration
    - FD1 (Horizontal Drift): equipped with six channels of 60V/13.5A/650W modules.
    - FD2 (Vertical Drift): equipped with four channels of 60V/13.5A/650W modules.
  - Property tagging
- Sample testing of ~10% of power supplies (3 units in each configuration), consisting of:
  - Powering up the power supply
  - Testing functionality of remote control using vendor's MUSE software
  - Powering on / off individual channels
  - Reading unit serial number
  - Making records in HWDB indicated test location, date, list of tests performed.
  - Observed problems will be communicated to Consortium QC representative, communicated to the vendor, and a plan of actions will be developed (as to check all units in the batch, reject the entire batch and return to the vendor, etc., depending on the observed problem).

After reception inspection at Fermilab, PL506 units will be repackaged and shipped to South Dakota following DUNE shipping procedures.

## 5 FD1-HD installation

The reception checks at SURF are described above in sections 4.2.6 (FEMBs), 4.14.1 (X-shape spool pieces).

Pairs of anode plane assemblies will be assembled just outside the clean room. After an assembled APA pair is moved into the clean room, the cold electronics cables will be installed. FEMBs will then be installed and connected to cables, and the cable bundles will be positioned in cable trays at the top of the APA pair. The APA pair will be moved into one of the cold boxes, and the cables connected to a patch panel inside the cold box. The FEMBs will then be tested using a two-WIEC DAQ system dedicated to the cold box. Once warm tests are passed, the cold box will be closed and cooled down and the tests will be repeated.

The APA pair will then be moved into its final position inside the cryostat. The CE and PDS cables will be routed through the cryostat penetration and connected to the corresponding warm flanges. The FEMBs will then be tested using DUNE DAQ. After this test is passed, the flanges will be bolted closed and a helium leak test will be conducted. These leak tests are performed by releasing helium gas in the cryostat penetration and checking for the presence of helium on top of the cryostat. This leak checking procedure will be exercised during Proto-DUNE installation. Once the leak test is successful, the FEMBs will be tested again using DUNE DAQ, and the next APA pair will be installed.

### 5.1.1 ColdBox test

#### 5.1.1.1 Description

Test the FEMBs and the cold power and data cables installed on the detector, both warm and cold. The test is needed to ensure that i) all electrical connections between detector sense wires/strips and detector readout electronics are established; ii) the RMS noise level is at the expected level; iii) no damage was made during installation; iv) all electrical connections between cold cables and FEMBs are established. Problems will be investigated and resolved in collaboration with detector consortia (APA, CRP).

#### 5.1.1.2 Location

At SURF in the APA cold box.

#### 5.1.1.3 Justification

It is critical to test each DUNE detector prior to installation in the cryostat both cold and warm. Once the DUNE detector cryostat is filled with LAr, there will be no access to the detector components to debug and fix problems. This is a critical integration test where the detector, FEMBs and cold cables (signal and power) will be tested as system.

#### 5.1.1.4 Data to HWDB

Channel-by-channel RMS noise levels, pulse traces, alone with test conditions (warm, cold, etc.), APA number, test location name, QC operator name, etc.

### 5.1.2 CE post-install test

#### 5.1.2.1 Description

In this integration test, the entire readout chain of each DUNE detector will be validated (FEMBs + cold cables + feedthrough connections + WIECs with WIBs and PTCs). Observed problems will be investigated and resolved in collaboration with other consortia (APA, CRP). This test may be repeated periodically to monitor stability and to ensure that no problem develop.

#### 5.1.2.2 Location

At SURF, in DUNE cryostat.

#### 5.1.2.3 Justification

The test is needed to ensure integrity of DUNE detector readout chain and to verify that no problems developed during APA/CRP installation into the cryostat.

#### 5.1.2.4 Data to HWDB

Channel-by-channel RMS noise levels, pulse traces, etc.

## 6 FD2-VD installation

The installation of BDE components consists of four steps:

- Install power supplies and DDSS components in the detector mezzanine.
- Install 40 cryostat penetrations (spool pieces and crossing tubes) and 80 WIECs.
- Install 27 m long cold cables from the WIECs to the bottom of the cryostat.
- Connect the cold cables to the patch panels on the bottom CRPs as they are installed.

The installation of power supplies and DDSS components in the detector mezzanine can take place as soon as the mezzanine is available and will be the first step in BDE installation.

The FSII team will provide the transport crate and mobile gantry used in the installation of the cryostat penetrations. They will also do the installation of the penetrations and spool pieces. A BDE crew will install the flanges, WIECs, WIBs, and PTCs. After each WIEC is installed, the BDE crew will verify that the WIBs and PTC are functional.

Cold cables will arrive at SURF pre-assembled into cable bundles fastened to rope ladders wound onto large reels. Each reel will hold the cables associated with one WIEC. The FSII team will install the cables and two BDE teams will test the cables after installation. The rope ladder will be attached to the cryostat wall and the cable bundles will be hoisted through a penetration using a lift. A BDE team on the cryostat roof will strain relief the cables and connect them to a warm electronics flange. A second BDE team will connect FEMBs to the cables on the floor of the cryostat where a CRP will be installed. The BDE team on top of the cryostat will verify that every FEMB is powered properly and can be read out, and then the FEMBs will be disconnected.

The half CRPs will be moved into the cryostat by FSII and CRP consortium members. Two half CRPs will be joined to form a full CRP, moved into position, and placed on a support truss that will hold the CRP approximately 1.2 m off the floor. BDE crew members will connect cold cables to the CRP patch panels and perform readout tests to verify that all of the cables are connected properly and the full readout chain works. The FSII crew will then remove the truss and lower the full CRP into its final position.

Quality control tests will be performed at each step of the installation. After the WIECs are installed, test patterns will be read out from each WIB. After the cold cables are installed, four (data cable, power cable) pairs at a time will be connected to FEMBs inside the cryostat and read out through a WIB on top of the cryostat. After each half CRP is transported to the clean room, a BDE crew will connect cold cables to the CRP patch panels and use a test system to verify that all FEMB channels are working. Any FEMB with a dead channel will be replaced before the half CRP is moved to the cryostat. Finally, after a full CRP is positioned, it will be read out through the normal readout chain. If any dead channel is observed and the CRP installation schedule allows, the CRP will be raised back onto support trusses and the faulty FEMB will be replaced.

## 7 Database Interface Description

Procedures for entering data and procedures for retrieving data and generating reports are being developed.

## 8 Definitions and Acronyms

### Table 2: Definitions

| Term | Definition |
|---|---|
| Gerber | "The Gerber format is an open ASCII vector format for printed circuit board (PCB) designs. It is the de facto standard used by PCB industry software." (Wikipedia) |
| Git | "Distributed version control system originally written in 2005 by Linus Torvalds." (Wikipedia) |
| Quality | Fitness of an item, service, process, or design for its intended use. |
| Quality Assurance (QA) | Proactive set of actions taken to provide confidence that quality requirements are fulfilled, and to detect and correct poor results. |
| Quality Control (QC) | System for verifying and maintaining a desired level of quality in an existing product or service by careful planning, use of proper equipment, continued inspection, and corrective action as required. |
| Quality Assurance Plan | Plan establishes principles, requirements, practices, and methods for integrating quality into the project. |
| Quality Control Plan | Written description of the measures for controlling the variations in a process within the acceptable limits. |
| Quality Assurance Representative | Person designated by the DUNE project manager and DUNE consortia technical lead to perform quality assurance functions. |
| Inspection Test Record (ITR) | Document listing the criteria that will be checked prior to making an item or service acceptable. |

### Table 3: Acronyms

| Acronym | Full term |
|---|---|
| APA | Anode Plane Assembly |
| BDE | Bottom Drift Electronics |
| CERN | European Organization for Nuclear Research |
| CRP | Charge-Readout Plane |
| DAQ | Data Acquisition System |
| DocDB | Fermilab Document Database |
| DOE | Department of Energy |
| DUNE | Deep Underground Neutrino Experiment |
| EDMS | CERN Electronic Data Management System |
| ESD | Electrostatic Discharge |
| ESH | Environment, Safety and Health |
| ESH&Q | Environment, Safety, Health and Quality |
| FD1-HD | Far Detector 1 - Horizontal Drift Detector (uses APAs) |
| FD2-VD | Far Detector 2 - Vertical Drift Detector (uses CRPs) |
| Fermilab | Fermi National Accelerator Laboratory |
| FESHM | Fermilab Environment, Safety and Health Manual |
| FNAL | Fermi National Accelerator Laboratory |
| FRA | Fermi Research Alliance, LLC |
| I&I | Installation & Integration |
| LAr | Liquid Argon |
| OSHA | Occupational Safety & Health Administration |
| PCB | Printed Circuit Board |
| PDS | Photon Detection System |
| PTB | Power and Timing Board (part of WIEC) |
| PTC | Power and Timing Card (installed in 1 slot in WIEC) |
| QA | Quality Assurance |
| QC | Quality Control |
| QAM | Quality Assurance Manager |
| QAP | Quality Assurance Plan |
| QAS | Quality Assurance Specialist |
| QAR | Quality Assurance Representative |
| SDSTA | South Dakota Science and Technology Authority |
| SME | Subject Matter Expert |
| SURF | Sanford Underground Research Facility |
| TDE | Top Drift Electronics |
| TPC | Time-Projection Chamber |
| WIB | Warm Interface Board |
| WIEC | Warm Interface Electronics Crate |

## References

[1] EDMS:2782612. [Online]. Available: https://edms.cern.ch/document/2782612.

[2] LBNF/DUNE, "LBNF/DUNE Life Cycle Costs (dune-doc-226)," May 2021. [Online]. Available: https://docs.dunescience.org/cgi-bin/sso/ShowDocument?docid=226.

[3] "PID CRP FD2 (EDMS 2505353)," [Online]. Available: https://edms.cern.ch/document/2505353.

[4] "DUNE Parts Identifier (EDMS 2505353)," [Online]. Available: https://edms.cern.ch/document/2505353.

[5] "CRP Requirements and Specifications (EDMS 2718669)," [Online]. Available: https://edms.cern.ch/document/2718669.

[6] LBNF/DUNE Project, "LBNF/DUNE Quality Assurance Plan (EDMS 2699054)," [Online]. Available: https://edms.cern.ch/document/2699054.

[7] "Top and Bottom Assembly Procedure (EDMS 2798705)," [Online]. Available: https://edms.cern.ch/document/2798705.
