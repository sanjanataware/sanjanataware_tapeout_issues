https://tear0202.hatenablog.com/entry/2020/07/14/234606

---

## Sodor Core Variant Generation — How It Works

*Investigating [issue: "We don't know exactly what the toolchain is doing and whether we HAVE to generate all the core variant folders"]*

### The five core variants

`generators/riscv-sodor/build.sbt` declares six SBT sub-projects:

| SBT project   | Source dir             | Description                                      |
|---------------|------------------------|--------------------------------------------------|
| `common`      | `src/common/`          | Shared CSR, memory, and utility code             |
| `rv32_1stage` | `src/rv32_1stage/`     | Single-cycle ISA simulator                       |
| `rv32_2stage` | `src/rv32_2stage/`     | 2-stage pipeline                                 |
| `rv32_3stage` | `src/rv32_3stage/`     | 3-stage pipeline (Harvard or Princeton memory)   |
| `rv32_5stage` | `src/rv32_5stage/`     | 5-stage pipeline (bypassed or interlocked)       |
| `rv32_ucode`  | `src/rv32_ucode/`      | Bus-based microcoded implementation              |

`common` is a dependency of every core variant. No root-level `.aggregate(...)` is used, so projects are independent of one another.

### What actually gets generated when you run `make rtl` or `make`

Both Forge Makefiles (`sims/verilator/Makefile` and `vlsi/Makefile`) drive SBT with:

```
sbt "project <MK_TARGET_PROC>" "run --target-dir <output>"
```

This syntax explicitly selects ONE sub-project before running. SBT then:

1. Loads `build.sbt` and resolves all project *definitions* (reads the file, no compilation yet).
2. Switches context to the chosen sub-project.
3. Compiles `common` (the only dependency).
4. Compiles the chosen variant.
5. Runs `object elaborate { def main(...) }` from that variant's `top.scala`, which
   calls `chisel3.Driver.execute` and writes a single `Top.v` to the output directory.

**No other core variant is compiled or elaborated.** The other four sub-projects are never
touched. SBT may create their base directories (e.g., `rv32_1stage/`) as part of project
resolution, but they contain at most an empty `target/` folder and can be ignored.

### How to control which core gets generated

Both Makefiles expose `MK_TARGET_PROC` (overridable on the command line):

```bash
# Simulation (default: rv32_1stage)
cd sims/verilator
make MK_TARGET_PROC=rv32_5stage rtl

# VLSI (default: rv32_5stage)
cd vlsi
make MK_TARGET_PROC=rv32_1stage <target>
```

Valid values: `rv32_1stage`, `rv32_2stage`, `rv32_3stage`, `rv32_5stage`, `rv32_ucode`.
Both Makefiles now validate this variable and error early on an unrecognised value.

### Is it harmful to leave multiple variant folders around?

No. The generated RTL lives under `sims/verilator/build/generated-src/<variant>/` and
`vlsi/build/<variant>-rtl/`. Running `make clean` / `make distclean` removes them. SBT
build-artifact directories (`rv32_*/target/`) can be wiped with `sbt clean` from inside
the sodor submodule. None of this affects correctness; it is purely an aesthetic concern.

### When would ALL variants be built?

Only if you ran Sodor's own `Makefile` directly (from inside `generators/riscv-sodor/`),
which sets `targets := $(all_targets)` and loops over every variant. Forge's Makefiles
never call Sodor's root `Makefile`; they invoke SBT directly with a specific project.
