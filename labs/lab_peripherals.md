# Peripherals & MMIO Integration with Sodor

## Background

The Sodor core alone is not useful for a real chip — it can execute instructions but has no way to communicate with the outside world. The minimum needed to make a chip functional after tapeout is a way to receive/send data from/to a host. This lab adds that capability through **memory-mapped I/O (MMIO)**, where peripheral registers are placed at specific addresses in the CPU's address space. A store to such an address writes to a peripheral register; a load reads from one.

JTAG/DMI (for debug) and Serial TileLink (for FESVR-based host communication during bringup) are tracked as separate issues. This issue focuses on functional peripherals accessible from user-mode RISC-V code.

---

## Peripheral Survey

| Peripheral | Description | Why we'd want it | Complexity |
|---|---|---|---|
| **UART** | Universal Asynchronous Receiver/Transmitter. Sends/receives bits serially at a configured baud rate over two wires (TX, RX). | `printf`-style debugging after tapeout, communication with a host PC. This is the most common low-speed debug interface after JTAG. | Low — 2-3 control registers, simple shift register logic |
| **GPIO** | General Purpose Input/Output. CPU-controlled digital pins that can be individually set high/low or read. | Toggle LEDs, detect button presses, bit-bang other protocols. Very easy to test on a board. | Very Low — just a data register and direction register |
| **SPI** | Serial Peripheral Interface. Synchronous 4-wire (CLK, CS, MOSI, MISO) protocol. Full-duplex. | Access external SPI flash for program storage, interface with sensors. Much faster than UART. | Medium — needs a shift register and clock divider |
| **I2C** | Inter-Integrated Circuit. Two-wire (SDA, SCL) synchronous serial bus. Multi-master capable. | Communicate with a wide ecosystem of sensors, EEPROMs, ADCs. Lower pin count than SPI. | Medium-High — open-drain bus protocol, clock stretching edge cases |
| **Timer (TMR32)** | 32-bit counter/timer with compare and interrupt output. | Delays, PWM generation, watchdog, scheduling. Almost any embedded software needs a timer. | Low — counter register + compare register + control |
| **I2S** | Inter-IC Sound. Synchronous audio serial bus for PCM audio data. | Stream audio to/from a DAC/ADC. Very niche for a class tapeout. | Medium — high frequency, specific timing |
| **PWM** | Pulse Width Modulation. Timer-derived output with adjustable duty cycle. | Motor control, LED brightness, DAC approximation. Usually derived from a timer peripheral. | Low (usually bundled with timer) |

**Reference implementations available:**
- [`CF_UART`](https://github.com/chipfoundry/CF_UART) — SystemVerilog UART, configurable baud
- [`CF_SPI`](https://github.com/chipfoundry/CF_SPI) — SPI master
- [`CF_I2C`](https://github.com/chipfoundry/CF_I2C) — I2C master/slave
- [`CF_I2S`](https://github.com/chipfoundry/CF_I2S) — I2S interface
- [`CF_TMR32`](https://github.com/chipfoundry/CF_TMR32) — 32-bit timer
- [`CF_IP_UTIL`](https://github.com/chipfoundry/CF_IP_UTIL) — bus utilities (APB bridge, synchronizers)

---

## Chosen Peripheral: UART

**Rationale:** After tapeout, the first thing you'll want to do is type characters to/from the chip to verify it works. UART is universally supported (every laptop has a USB-UART adapter or terminal), requires only 2 signal wires, and is straightforward to validate. Every other peripheral requires specialized equipment or software; UART just needs a terminal emulator.

For software: anything from bare-metal `putchar()` up to a full RISC-V newlib `printf` works once UART TX is functional.

### What UART Is

A UART sends one character at a time as a serial bit stream:
- **Idle state**: TX line is high
- **Start bit**: TX goes low for one bit period (signals start of frame)
- **Data bits**: 8 bits, LSB first
- **Stop bit**: TX goes high for one bit period

The bit period is `1 / baud_rate`. For 115200 baud on a 25 MHz clock: `25_000_000 / 115200 ≈ 217` clock cycles per bit.

**Minimum register interface** (4 registers, each 32-bit word-aligned):

| Offset | Name | Access | Description |
|--------|------|--------|-------------|
| `+0x00` | `TXDATA` | W | Write a byte here to transmit; busy-stalls if TX FIFO full |
| `+0x04` | `RXDATA` | R | Read a byte; bit 31 set means no data available |
| `+0x08` | `TXCTRL` | R/W | `[0]` = TX enable, `[15:16]` = stop bits |
| `+0x0C` | `IE` / `IP` | R/W | Interrupt enable/pending (optional for MVP) |
| `+0x10` | `DIV` | R/W | Baud rate divisor (`clk_freq / baud_rate - 1`) |

This is essentially the [SiFive UART register map](https://static.dev.sifive.com/FE310-G000.pdf), which is what Spike/FESVR already emulates — meaning the same software works in simulation and on real hardware.

---

## MMIO Integration with Sodor

### Memory Map Plan

Sodor's scratchpad starts at `0x80000000` (defined in `src/common/consts.scala` as `PC_START`). The scratchpad is typically 1 MB (`0x80000000`–`0x800FFFFF`).

We'll place MMIO above the scratchpad in a dedicated region:

```
0x80000000 – 0x800FFFFF   Sodor scratchpad SRAM  (1 MB)
0x80100000 – 0x8010FFFF   MMIO region            (64 KB)
  0x80100000              UART base address
```

### Where to Make Changes

Run these commands on the server to find the relevant files in your Sodor submodule:

```bash
# See the current memory constants
cat generators/riscv-sodor/src/common/consts.scala | grep -A5 "MEM\|PC_START\|MEM_SIZE"

# See the scratchpad memory implementation
cat generators/riscv-sodor/src/common/memory.scala

# See how 1-stage top wires up memory
cat generators/riscv-sodor/src/rv32_1stage/top.scala
```

Paste the output here so we can write the exact Chisel changes. In the meantime, here is the general approach:

### Step 1 — Add MMIO constants to `consts.scala`

```scala
// Add to generators/riscv-sodor/src/common/consts.scala
val MMIO_BASE     = 0x80100000L
val MMIO_SIZE     = 0x00010000L  // 64 KB
val UART_BASE     = MMIO_BASE    // UART sits at start of MMIO region
```

### Step 2 — Create `uart.scala` in `src/common/`

```scala
// generators/riscv-sodor/src/common/uart.scala
package sodor.common

import chisel3._
import chisel3.util._

// Simple UART TX-only MVP (add RX as follow-up)
class UartTx(clockFreq: Int, baudRate: Int) extends Module {
  val io = IO(new Bundle {
    val tx   = Output(Bool())
    val data = Flipped(Decoupled(UInt(8.W)))  // write a byte to transmit
  })

  val DIV = (clockFreq / baudRate) - 1  // cycles per bit

  val idle :: start :: data :: stop :: Nil = Enum(4)
  val state   = RegInit(idle)
  val counter = RegInit(0.U(log2Ceil(DIV + 1).W))
  val shift   = RegInit(0.U(8.W))
  val bitIdx  = RegInit(0.U(3.W))

  io.tx          := true.B
  io.data.ready  := state === idle

  switch (state) {
    is (idle) {
      when (io.data.valid) {
        shift   := io.data.bits
        counter := DIV.U
        state   := start
      }
    }
    is (start) {
      io.tx := false.B
      when (counter === 0.U) { counter := DIV.U; bitIdx := 0.U; state := data }
      .otherwise             { counter := counter - 1.U }
    }
    is (data) {
      io.tx := shift(bitIdx)
      when (counter === 0.U) {
        counter := DIV.U
        when (bitIdx === 7.U) { state := stop }
        .otherwise            { bitIdx := bitIdx + 1.U }
      } .otherwise { counter := counter - 1.U }
    }
    is (stop) {
      when (counter === 0.U) { state := idle }
      .otherwise             { counter := counter - 1.U }
    }
  }
}

// MMIO register file that wraps UartTx
// Exposes a simple req/resp interface matching Sodor's MemPortIo style
class UartMMIO(clockFreq: Int, baudRate: Int) extends Module {
  val io = IO(new Bundle {
    val req_valid = Input(Bool())
    val req_addr  = Input(UInt(32.W))
    val req_fcn   = Input(UInt(2.W))   // 0=read, 1=write (matches Sodor M_XRD/M_XWR)
    val req_data  = Input(UInt(32.W))
    val resp_data = Output(UInt(32.W))
    val tx        = Output(Bool())     // physical pin
  })

  val uart = Module(new UartTx(clockFreq, baudRate))
  io.tx := uart.io.tx

  // TXDATA register offset 0x00
  val offset = io.req_addr(15, 0)  // lower 16 bits select register within MMIO region

  uart.io.data.valid := false.B
  uart.io.data.bits  := 0.U
  io.resp_data       := 0.U

  // TXDATA write (offset 0x00)
  when (io.req_valid && io.req_fcn === 1.U && offset === 0x00.U) {
    uart.io.data.valid := true.B
    uart.io.data.bits  := io.req_data(7, 0)
  }

  // STATUS read (offset 0x08): bit 0 = TX ready
  when (io.req_valid && io.req_fcn === 0.U && offset === 0x08.U) {
    io.resp_data := Cat(0.U(31.W), uart.io.data.ready)
  }
}
```

### Step 3 — Add address decode in `memory.scala`

In `ScratchPadMemory` (or its wrapper in `top.scala`), add an MMIO mux before the SRAM access:

```scala
// Inside ScratchPadMemory or top-level memory module
val uart = Module(new UartMMIO(CoreDef.CLOCK_FREQ, 115200))

// Decode MMIO vs SRAM
val is_mmio = io.dmem.req.bits.addr >= MMIO_BASE.U

// Wire UART MMIO port
uart.io.req_valid := io.dmem.req.valid && is_mmio
uart.io.req_addr  := io.dmem.req.bits.addr
uart.io.req_fcn   := io.dmem.req.bits.fcn
uart.io.req_data  := io.dmem.req.bits.data

// Suppress SRAM access for MMIO addresses
val sram_req_valid = io.dmem.req.valid && !is_mmio

// Mux the response back to the core
io.dmem.resp.bits.data := Mux(RegNext(is_mmio), uart.io.resp_data, sram_resp_data)

// Expose UART TX as a top-level IO pin
io.uart_tx := uart.io.tx
```

### Step 4 — Add `uart_tx` to `Top` IO

```scala
// In top.scala, add to the Top module IO bundle:
val uart_tx = Output(Bool())
// Wire: top.io.uart_tx := mem.io.uart_tx  (or however the memory is instantiated)
```

### Step 5 — Add `uart_tx` to the Verilator harness

In `generators/riscv-sodor/sim/emulator.cpp` (or the top-level `.v` harness), connect `uart_tx` to a `printf` that prints received bytes, so simulation output shows UART traffic.

```cpp
// In emulator.cpp tick loop, after each clock edge:
// (Verilator will expose top->uart_tx)
// For simulation, use a software UART decoder to capture bytes:
static SoftUart soft_uart(115200, SIM_CLOCK_FREQ);
char c;
if (soft_uart.tick(top->uart_tx, &c)) {
    putchar(c);  // print to stdout when a full byte is received
}
```

Alternatively, use Verilog `$fwrite` in a testbench bind to capture TX bytes without changing the C++ harness.

---

## MMIO Software Test

Once the hardware is integrated, write a minimal C test to validate:

```c
// tests/uart_hello/uart_hello.c
#define UART_BASE  0x80100000UL
#define UART_TXDATA (*((volatile unsigned int *)(UART_BASE + 0x00)))
#define UART_STATUS (*((volatile unsigned int *)(UART_BASE + 0x08)))

void uart_putc(char c) {
    while (!(UART_STATUS & 1));  // wait for TX ready
    UART_TXDATA = (unsigned int)c;
}

void uart_puts(const char *s) {
    while (*s) uart_putc(*s++);
}

int main(void) {
    uart_puts("Hello from Sodor!\n");
    return 0;
}
```

Compile with the RISC-V toolchain:

```bash
riscv64-unknown-elf-gcc -march=rv32i -mabi=ilp32 -nostdlib \
  -Tlink.ld -o uart_hello.elf tests/uart_hello/uart_hello.c
```

Run in simulation and verify the output appears in the emulator stdout.

---

## Next Steps After MVP

1. **Add UART RX** — implement the receiver shift register for bidirectional comms
2. **Add a timer** (`CF_TMR32` or a simple Chisel counter) — software needs it for delays and round-trip timing
3. **Add GPIO** — test digital output (toggle a pin, verify with simulation waveform)
4. **APB bus fabric** — if we add >2 peripherals, route them through an APB mux (see `CF_IP_UTIL`) instead of manually decoding each one
5. **Interrupt controller** — wire UART RX and timer compare to RISC-V `mip` CSR via a PLIC or direct wire

---

## Commands to Run on the Server

To inspect the exact current Sodor memory interface before writing the Chisel patch:

```bash
# From your 151t-forge checkout on eda-X:
cat generators/riscv-sodor/src/common/consts.scala
cat generators/riscv-sodor/src/common/memory.scala
cat generators/riscv-sodor/src/rv32_1stage/top.scala
# Also look at the MemPortIo bundle definition:
grep -n "MemPortIo\|MemReq\|MemResp\|M_XRD\|M_XWR" generators/riscv-sodor/src/common/*.scala
```

Paste the output here and we can write the exact diff.
