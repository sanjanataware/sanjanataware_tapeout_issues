#!/usr/bin/env python3
"""
Apply UART MMIO peripheral integration to riscv-sodor.

Run from the repo root:
    python3 scripts/apply_uart_mmio.py

What this does:
  1. Creates  generators/riscv-sodor/src/common/uart.scala      (new)
  2. Patches  generators/riscv-sodor/src/common/consts.scala    (add MMIO_BASE)
  3. Patches  generators/riscv-sodor/src/common/memory.scala    (UART + MMIO decode)
  4. Replaces generators/riscv-sodor/src/rv32_1stage/tile.scala (add uart_tx IO)
  5. Replaces generators/riscv-sodor/src/rv32_1stage/top.scala  (add uart_tx IO)
"""

import sys
import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def read(path):
    return Path(path).read_text()

def write(path, text):
    Path(path).write_text(text)
    print(f"  wrote  {path}")

def patch(path, old, new, tag):
    txt = read(path)
    if old not in txt:
        print(f"  ERROR [{tag}]: expected text not found in {path}")
        print(f"         First 60 chars of old string: {repr(old[:60])}")
        sys.exit(1)
    if new in txt:
        print(f"  SKIP  [{tag}]: already applied in {path}")
        return
    write(path, txt.replace(old, new, 1))
    print(f"  patch  {path}  [{tag}]")

# ---------------------------------------------------------------------------
# Sanity check: must be run from repo root
# ---------------------------------------------------------------------------

SODOR_COMMON  = Path("generators/riscv-sodor/src/common")
SODOR_1STAGE  = Path("generators/riscv-sodor/src/rv32_1stage")

for d in [SODOR_COMMON, SODOR_1STAGE]:
    if not d.is_dir():
        print(f"ERROR: {d} not found. Run this script from the repo root "
              f"after `git submodule update --init --recursive`.")
        sys.exit(1)

# ---------------------------------------------------------------------------
# 1. uart.scala  (new file)
# ---------------------------------------------------------------------------

UART_SCALA = SODOR_COMMON / "uart.scala"

UART_CONTENT = '''\
package Common

import chisel3._
import chisel3.util._

// UART transmitter (8N1). Accepts one byte at a time via a Decoupled interface
// and serialises it at the given baud rate. data.ready is low while a byte is
// in flight; bytes written when !ready are silently dropped by the Decoupled
// handshake (only consumed when ready && valid both true).
class UartTx(clockFreq: Int, baudRate: Int) extends Module {
  val io = IO(new Bundle {
    val tx   = Output(Bool())
    val data = Flipped(Decoupled(UInt(8.W)))
  })

  val DIV = (clockFreq / baudRate) - 1

  val idle :: start :: send :: stop :: Nil = Enum(4)
  val state   = RegInit(idle)
  val counter = RegInit(0.U(log2Ceil(DIV + 2).W))
  val shift   = RegInit(0.U(8.W))
  val bitIdx  = RegInit(0.U(3.W))

  io.tx         := true.B       // idle / stop = high
  io.data.ready := state === idle

  switch(state) {
    is(idle) {
      when(io.data.valid) {
        shift   := io.data.bits
        counter := DIV.U
        state   := start
      }
    }
    is(start) {
      io.tx := false.B          // start bit
      when(counter === 0.U) {
        counter := DIV.U
        bitIdx  := 0.U
        state   := send
      }.otherwise {
        counter := counter - 1.U
      }
    }
    is(send) {
      io.tx := shift(bitIdx)    // LSB first
      when(counter === 0.U) {
        counter := DIV.U
        when(bitIdx === 7.U) { state := stop }
        .otherwise            { bitIdx := bitIdx + 1.U }
      }.otherwise {
        counter := counter - 1.U
      }
    }
    is(stop) {
      when(counter === 0.U) { state := idle }
      .otherwise            { counter := counter - 1.U }
    }
  }
}
'''

if UART_SCALA.exists():
    print(f"  SKIP  {UART_SCALA} (already exists)")
else:
    write(UART_SCALA, UART_CONTENT)

# ---------------------------------------------------------------------------
# 2. consts.scala  — add MMIO_BASE / UART_BASE to PrivilegedConstants
#    The original line has a trailing space: `   val START_ADDR = "h80000000".U `
# ---------------------------------------------------------------------------

patch(
    SODOR_COMMON / "consts.scala",
    old='   val START_ADDR = "h80000000".U ',
    new=('   val START_ADDR = "h80000000".U \n'
         '   val MMIO_BASE   = "h80200000".U  // MMIO region: above 2 MB scratchpad\n'
         '   val UART_BASE   = MMIO_BASE'),
    tag="consts MMIO_BASE",
)

# ---------------------------------------------------------------------------
# 3. memory.scala  — four targeted patches
# ---------------------------------------------------------------------------

MEM = SODOR_COMMON / "memory.scala"

# 3a. uart_tx output in AsyncScratchPadMemory IO bundle
patch(
    MEM,
    old=(
        '      val core_ports = Vec(num_core_ports, Flipped(new MemPortIo(data_width = conf.xprlen)) )\n'
        '      val debug_port = Flipped(new MemPortIo(data_width = 32))\n'
        '   })\n'
        '   val num_bytes_per_line = 8\n'
        '   val num_lines = num_bytes / num_bytes_per_line\n'
        '   println("\\n    Sodor Tile: creating Asynchronous'
    ),
    new=(
        '      val core_ports = Vec(num_core_ports, Flipped(new MemPortIo(data_width = conf.xprlen)) )\n'
        '      val debug_port = Flipped(new MemPortIo(data_width = 32))\n'
        '      val uart_tx    = Output(Bool())\n'
        '   })\n'
        '   val num_bytes_per_line = 8\n'
        '   val num_lines = num_bytes / num_bytes_per_line\n'
        '   println("\\n    Sodor Tile: creating Asynchronous'
    ),
    tag="async IO uart_tx",
)

# 3b. UART logic + MMIO mux in AsyncScratchPadMemory DPORT section
#     Note: original lines have trailing spaces on "DPORT " and type lines
patch(
    MEM,
    old=(
        '   /////////// DPORT \n'
        '   val req_addri = io.core_ports(DPORT).req.bits.addr\n'
        '\n'
        '   val req_typi = io.core_ports(DPORT).req.bits.typ\n'
        '   val resp_datai = async_data.io.dataInstr(DPORT).data\n'
        '   io.core_ports(DPORT).resp.bits.data := MuxCase(resp_datai,Array(\n'
        '      (req_typi === MT_B) -> Cat(Fill(24,resp_datai(7)),resp_datai(7,0)),\n'
        '      (req_typi === MT_H) -> Cat(Fill(16,resp_datai(15)),resp_datai(15,0)),\n'
        '      (req_typi === MT_BU) -> Cat(Fill(24,0.U),resp_datai(7,0)),\n'
        '      (req_typi === MT_HU) -> Cat(Fill(16,0.U),resp_datai(15,0))\n'
        '   ))\n'
        '   async_data.io.dw.en := false.B\n'
        '   when (io.core_ports(DPORT).req.valid && (io.core_ports(DPORT).req.bits.fcn === M_XWR))\n'
        '   {\n'
        '      async_data.io.dw.en := true.B\n'
        '      async_data.io.dw.data := io.core_ports(DPORT).req.bits.data << (req_addri(1,0) << 3)\n'
        '      async_data.io.dw.addr := Cat(req_addri(31,2),0.asUInt(2.W))\n'
        '      async_data.io.dw.mask := Mux(req_typi === MT_B,1.U << req_addri(1,0),\n'
        '                              Mux(req_typi === MT_H,3.U << req_addri(1,0),15.U))\n'
        '   }\n'
        '   /////////////////\n'
    ),
    new=(
        '   /////////// DPORT \n'
        '   val req_addri = io.core_ports(DPORT).req.bits.addr\n'
        '\n'
        '   val req_typi   = io.core_ports(DPORT).req.bits.typ\n'
        '   val resp_datai = async_data.io.dataInstr(DPORT).data\n'
        '\n'
        '   // MMIO: any write to MMIO_BASE+0x00 transmits low byte via UART TX\n'
        '   //       any read  from MMIO_BASE     returns {31b0, tx_ready} in bit 0\n'
        '   val is_mmio_a         = req_addri >= MMIO_BASE\n'
        '   val uart_a            = Module(new UartTx(50000000, 115200))\n'
        '   uart_a.io.data.valid := io.core_ports(DPORT).req.valid &&\n'
        '                           (io.core_ports(DPORT).req.bits.fcn === M_XWR) && is_mmio_a\n'
        '   uart_a.io.data.bits  := io.core_ports(DPORT).req.bits.data(7, 0)\n'
        '   val uart_status_a     = Cat(0.U(31.W), uart_a.io.data.ready)\n'
        '   io.uart_tx           := uart_a.io.tx\n'
        '\n'
        '   io.core_ports(DPORT).resp.bits.data := Mux(is_mmio_a, uart_status_a,\n'
        '      MuxCase(resp_datai,Array(\n'
        '         (req_typi === MT_B) -> Cat(Fill(24,resp_datai(7)),resp_datai(7,0)),\n'
        '         (req_typi === MT_H) -> Cat(Fill(16,resp_datai(15)),resp_datai(15,0)),\n'
        '         (req_typi === MT_BU) -> Cat(Fill(24,0.U),resp_datai(7,0)),\n'
        '         (req_typi === MT_HU) -> Cat(Fill(16,0.U),resp_datai(15,0))\n'
        '      )))\n'
        '   async_data.io.dw.en := false.B\n'
        '   when (io.core_ports(DPORT).req.valid && (io.core_ports(DPORT).req.bits.fcn === M_XWR) && !is_mmio_a)\n'
        '   {\n'
        '      async_data.io.dw.en := true.B\n'
        '      async_data.io.dw.data := io.core_ports(DPORT).req.bits.data << (req_addri(1,0) << 3)\n'
        '      async_data.io.dw.addr := Cat(req_addri(31,2),0.asUInt(2.W))\n'
        '      async_data.io.dw.mask := Mux(req_typi === MT_B,1.U << req_addri(1,0),\n'
        '                              Mux(req_typi === MT_H,3.U << req_addri(1,0),15.U))\n'
        '   }\n'
        '   /////////////////\n'
    ),
    tag="async DPORT MMIO",
)

# 3c. uart_tx output in SyncScratchPadMemory IO bundle
patch(
    MEM,
    old=(
        '      val core_ports = Vec(num_core_ports, Flipped(new MemPortIo(data_width = conf.xprlen)) )\n'
        '      val debug_port = Flipped(new MemPortIo(data_width = 32))\n'
        '   })\n'
        '   val num_bytes_per_line = 8\n'
        '   val num_lines = num_bytes / num_bytes_per_line\n'
        '   println("\\n    Sodor Tile: creating Synchronous'
    ),
    new=(
        '      val core_ports = Vec(num_core_ports, Flipped(new MemPortIo(data_width = conf.xprlen)) )\n'
        '      val debug_port = Flipped(new MemPortIo(data_width = 32))\n'
        '      val uart_tx    = Output(Bool())\n'
        '   })\n'
        '   val num_bytes_per_line = 8\n'
        '   val num_lines = num_bytes / num_bytes_per_line\n'
        '   println("\\n    Sodor Tile: creating Synchronous'
    ),
    tag="sync IO uart_tx",
)

# 3d. UART logic + MMIO mux in SyncScratchPadMemory DPORT section
patch(
    MEM,
    old=(
        '   /////////// DPORT \n'
        '   val req_addri = io.core_ports(DPORT).req.bits.addr\n'
        '\n'
        '   val req_typi = Reg(UInt(3.W))\n'
        '   req_typi := io.core_ports(DPORT).req.bits.typ\n'
        '   val resp_datai = sync_data.io.dataInstr(DPORT).data\n'
        '\n'
        '   io.core_ports(DPORT).resp.bits.data := MuxCase(resp_datai,Array(\n'
        '      (req_typi === MT_B) -> Cat(Fill(24,resp_datai(7)),resp_datai(7,0)), \n'
        '      (req_typi === MT_H) -> Cat(Fill(16,resp_datai(15)),resp_datai(15,0)), \n'
        '      (req_typi === MT_BU) -> Cat(Fill(24,0.U),resp_datai(7,0)), \n'
        '      (req_typi === MT_HU) -> Cat(Fill(16,0.U),resp_datai(15,0)) \n'
        '   ))\n'
        '\n'
        '   sync_data.io.dw.en := false.B\n'
        '   when (io.core_ports(DPORT).req.valid && (io.core_ports(DPORT).req.bits.fcn === M_XWR))\n'
        '   {\n'
        '      sync_data.io.dw.en := true.B\n'
        '      sync_data.io.dw.data := io.core_ports(DPORT).req.bits.data << (req_addri(1,0) << 3)\n'
        '      sync_data.io.dw.addr := Cat(req_addri(31,2),0.asUInt(2.W))\n'
        '      sync_data.io.dw.mask := Mux(io.core_ports(DPORT).req.bits.typ === MT_B,1.U << req_addri(1,0),\n'
        '                              Mux(io.core_ports(DPORT).req.bits.typ === MT_H,3.U << req_addri(1,0),15.U))\n'
        '   }\n'
        '   /////////////////\n'
    ),
    new=(
        '   /////////// DPORT \n'
        '   val req_addri = io.core_ports(DPORT).req.bits.addr\n'
        '\n'
        '   val req_typi = Reg(UInt(3.W))\n'
        '   req_typi := io.core_ports(DPORT).req.bits.typ\n'
        '   val resp_datai = sync_data.io.dataInstr(DPORT).data\n'
        '\n'
        '   // MMIO: any write to MMIO_BASE+0x00 transmits low byte via UART TX\n'
        '   //       any read  from MMIO_BASE     returns {31b0, tx_ready} in bit 0\n'
        '   val is_mmio_s         = req_addri >= MMIO_BASE\n'
        '   val is_mmio_s_reg     = RegNext(is_mmio_s, false.B)\n'
        '   val uart_s            = Module(new UartTx(50000000, 115200))\n'
        '   uart_s.io.data.valid := io.core_ports(DPORT).req.valid &&\n'
        '                           (io.core_ports(DPORT).req.bits.fcn === M_XWR) && is_mmio_s\n'
        '   uart_s.io.data.bits  := io.core_ports(DPORT).req.bits.data(7, 0)\n'
        '   val uart_status_s     = Cat(0.U(31.W), uart_s.io.data.ready)\n'
        '   io.uart_tx           := uart_s.io.tx\n'
        '\n'
        '   io.core_ports(DPORT).resp.bits.data := Mux(is_mmio_s_reg, uart_status_s,\n'
        '      MuxCase(resp_datai,Array(\n'
        '         (req_typi === MT_B) -> Cat(Fill(24,resp_datai(7)),resp_datai(7,0)), \n'
        '         (req_typi === MT_H) -> Cat(Fill(16,resp_datai(15)),resp_datai(15,0)), \n'
        '         (req_typi === MT_BU) -> Cat(Fill(24,0.U),resp_datai(7,0)), \n'
        '         (req_typi === MT_HU) -> Cat(Fill(16,0.U),resp_datai(15,0)) \n'
        '      )))\n'
        '\n'
        '   sync_data.io.dw.en := false.B\n'
        '   when (io.core_ports(DPORT).req.valid && (io.core_ports(DPORT).req.bits.fcn === M_XWR) && !is_mmio_s)\n'
        '   {\n'
        '      sync_data.io.dw.en := true.B\n'
        '      sync_data.io.dw.data := io.core_ports(DPORT).req.bits.data << (req_addri(1,0) << 3)\n'
        '      sync_data.io.dw.addr := Cat(req_addri(31,2),0.asUInt(2.W))\n'
        '      sync_data.io.dw.mask := Mux(io.core_ports(DPORT).req.bits.typ === MT_B,1.U << req_addri(1,0),\n'
        '                              Mux(io.core_ports(DPORT).req.bits.typ === MT_H,3.U << req_addri(1,0),15.U))\n'
        '   }\n'
        '   /////////////////\n'
    ),
    tag="sync DPORT MMIO",
)

# ---------------------------------------------------------------------------
# 4. tile.scala  — full replacement (adds uart_tx to IO + wires memory port)
# ---------------------------------------------------------------------------

write(
    SODOR_1STAGE / "tile.scala",
    '''\
//**************************************************************************
// RISCV Processor Tile
//--------------------------------------------------------------------------
//

package Sodor
{

import chisel3._

import Common.{SodorConfiguration, DMIIO, AsyncScratchPadMemory, DebugModule}

class SodorTile(implicit val conf: SodorConfiguration) extends Module
{
   val io = IO(new Bundle {
      val dmi     = Flipped(new DMIIO())
      val uart_tx = Output(Bool())
   })

   // notice that while the core is put into reset, the scratchpad needs to be
   // alive so that the Debug Module can load in the program.
   val debug = Module(new DebugModule())
   val core   = Module(new Core())
   core.io := DontCare
   val memory = Module(new AsyncScratchPadMemory(num_core_ports = 2))
   core.io.dmem <> memory.io.core_ports(0)
   core.io.imem <> memory.io.core_ports(1)
   debug.io.debugmem <> memory.io.debug_port
   core.reset := debug.io.resetcore | reset.toBool
   debug.io.dmi <> io.dmi
   io.uart_tx := memory.io.uart_tx
}

}
''',
)

# ---------------------------------------------------------------------------
# 5. top.scala  — full replacement (adds uart_tx to Top IO)
# ---------------------------------------------------------------------------

write(
    SODOR_1STAGE / "top.scala",
    '''\
package Sodor

import chisel3._

import Common.{SodorConfiguration, SimDTM}

class Top extends Module
{
   val io = IO(new Bundle{
      val success = Output(Bool())
      val uart_tx = Output(Bool())
    })

   implicit val sodor_conf = SodorConfiguration()
   val tile = Module(new SodorTile)
   val dtm = Module(new SimDTM).connect(clock, reset.toBool, tile.io.dmi, io.success)
   io.uart_tx := tile.io.uart_tx
}

object elaborate {
  def main(args: Array[String]): Unit = {
    chisel3.Driver.execute(args, () => new Top)
  }
}
''',
)

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

print()
print("All changes applied. Next step:")
print("  cd sims/verilator && make rtl MK_TARGET_PROC=rv32_1stage 2>&1 | tail -40")
