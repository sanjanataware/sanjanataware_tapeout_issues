# EECS151T Forge

151T Forge is a teaching-focused SoC development repository designed to simplify chip design education by emphasizing SystemVerilog integration and reducing complexity. Built as a streamlined alternative to Chipyard, Forge combines Chisel and SystemVerilog to create a more accessible platform for implementing and testing RISC-V cores and peripherals. Forge makes use of a Hammer physical design flow and Sodor core as basis. 

A small lab manual is available under `/labs`. In Lab 2, you'll set up the repository and validate one of five Sodor core implementations (ranging from a 1-stage ISA simulator to a fully pipelined 5-stage design) by running existing RISC-V assembly tests. This Spring 2026 experiment encourages collaborative development - submit pull requests, share feedback, and document issues as the community refines this platform together. The goal is to progressively add peripherals, run verification, and carry your core's RTL through physical-design flows in Sky130 toward tapeout. Lab 5 describes the physical design flow. 

## Course Info

EECS151 Tapeout is a Decal (student-run course) giving a hands-on, end-to-end experience in SoC design and implementation culminating in a tapeout.

Students with a background in the fundamentals of digital design and VLSI CAD tools (EECS151 + ASIC lab) will learn how to use the Chisel hardware description language and Chipyard (an agile hardware design framework) to integrate their EECS151 ASIC core or a custom IP block of their own design into a full-scale System-on-Chip (SoC). While covering the basics of agile SoC design concepts and methodology, the course is primarily a hands-on experience. One (or more, depending on student interest) class SoCs are planned to be taped out in the open-source Skywater 130nm process at the end of the semester. Extra chip area is available for motivated students with unique, large-scale projects.

The course aims to give all students hands-on experience in every step of the SoC design process from system-level design (interfaces, modular decoupling), to toplevel integration and physical design with commercial CAD tools though Berkeley’s Hammer tool. Students will participate in a class project consisting of one or more physically realized and fabricated SoCs in the open-source Skywater 130nm process node. Student contributions to the designs may range from a chipyard-integrated version of their EECS 151 ASIC core to custom accelerators or off-chip peripheral interfaces. It is emphasized that while multiple students may collaborate on a single SoC (or even within a module), every student will receive hands-on experience with the full tapeout process, from system architecture to GDSII signoff.

This course spans 13 weeks. Class meets for two hours once a week. Each class will generally consist of a short mini lecture, overview of project status, and check-ins with each team on milestones and obstacles. Students are expected to spend a bit more time each week outside of class time working on their project. The ultimate goal of this course is to tapeout on the Cadence SkyWater 130nm shuttle.

**Read more here: [https://151tapeout.berkie.ee/](https://151tapeout.berkie.ee/)**
