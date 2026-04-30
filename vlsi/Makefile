#########################################################################################
# vlsi makefile
#########################################################################################

#########################################################################################
# general path variables
#########################################################################################
base_dir=$(abspath ..)
vlsi_dir=$(abspath .)
sim_dir=$(abspath .)

#########################################################################################
# vlsi types and rules
#########################################################################################
sim_name           ?= vcs # needed for GenerateSimFiles, but is unused
tech_name          ?= sky130
tech_dir           ?= $(if $(filter $(tech_name),sky130 asap7 nangate45),\
                        $(shell python3 -c "import os, hammer.technology.$(tech_name);\
						print(os.path.dirname(hammer.technology.$(tech_name).__file__))"),\
                        $(vlsi_dir)/hammer-$(tech_name)-plugin/hammer/$(tech_name))
SMEMS_COMP         ?= $(tech_dir)/sram-compiler.json
SMEMS_CACHE        ?= $(tech_dir)/sram-cache.json
SMEMS_HAMMER       ?= $(build_dir)/$(long_name).mems.hammer.json
SRAM_CACHE_SCRIPT  ?= $(vlsi_dir)/hammer/hammer/technology/sky130/extra/sram22/sram-cache-gen.py
AVAILABLE_SRAM_CACHE ?= $(OBJ_DIR)/available-sram-cache.json
SRAM_CACHE_CONF    ?= $(OBJ_DIR)/available-sram-cache.yml
SRAM22_MACROS      ?= /home/ff/ee198/ee198-20/sky130_col/sram22_sky130_macros

ifdef USE_SRAM_COMPILER
	TOP_MACROCOMPILER_MODE ?= -l $(SMEMS_COMP) --use-compiler -hir $(SMEMS_HAMMER) --mode strict
else
	TOP_MACROCOMPILER_MODE ?= -l $(SMEMS_CACHE) -hir $(SMEMS_HAMMER) --mode strict
endif

HOSTNAME := $(shell hostname)
IS_TOP_RUN ?= 1

ifeq ($(findstring bwrc,$(HOSTNAME)),bwrc)
	PLATFORM ?= -bwrc
else ifeq ($(findstring eda, $(HOSTNAME)), eda)
	PLATFORM ?= -inst
endif

ENV_YML            ?= $(vlsi_dir)/env.yml
TECH_CONF          ?= tech-$(tech_name)$(PLATFORM).yml
TOOLS_CONF         ?= tools$(PLATFORM).yml
CHIP_CONF         ?= design.yml
INPUT_CONFS        ?= $(TOOLS_CONF) $(TECH_CONF) $(CHIP_CONF)
PIN_MAP            ?= pin-map-ofo.yml

ifeq ($(IS_TOP_RUN),1)
	HAMMER_EXEC        ?= ./hammer-driver 
else
	HAMMER_EXEC        ?= ./example-vlsi-sky130
endif

VLSI_TOP           ?= SodorTile
VLSI_MODEL_DUT_NAME ?= chiptop0
# If overriding, this should be relative to $(vlsi_dir)
VLSI_OBJ_DIR       ?= build
export USE_CHISEL6        = 1

OBJ_DIR          ?= $(vlsi_dir)/$(VLSI_OBJ_DIR)/$(VLSI_TOP)

#########################################################################################
# general rules
#########################################################################################
.PHONY: default all
default: all

all: drc lvs

#########################################################################################
# process RTL
#########################################################################################
MK_TARGET_PROC ?= rv32_5stage
RTL_TARGET_DIR = $(vlsi_dir)/build/$(MK_TARGET_PROC)-rtl
SODOR_TOP_V = $(RTL_TARGET_DIR)/Top.v
SODOR_VSRCS = $(wildcard $(base_dir)/generators/riscv-sodor/vsrc/*.sv) \
              $(wildcard $(base_dir)/generators/riscv-sodor/vsrc/*.v)
# Trigger Sodor elaboration directly via sbt
$(SODOR_TOP_V): $(SODOR_VSRCS)
	mkdir -p $(RTL_TARGET_DIR)
	cd $(base_dir)/generators/riscv-sodor && sbt "project $(MK_TARGET_PROC)" "runMain Sodor.elaborate --target-dir $(RTL_TARGET_DIR)"
	cp $(base_dir)/generators/riscv-sodor/vsrc/*.sv $(RTL_TARGET_DIR)/ 2>/dev/null || true
	cp $(base_dir)/generators/riscv-sodor/vsrc/sram22_2048x32m8w8.stub.v $(RTL_TARGET_DIR)/ 2>/dev/null || true

#########################################################################################
# srams
#########################################################################################
SRAM_GENERATOR_CONF = $(OBJ_DIR)/sram_generator-input.yml
SRAM_CONF=$(OBJ_DIR)/sram_generator-output.json

## SRAM Generator
.PHONY: sram_generator srams
srams: sram_generator
sram_generator: $(SRAM_CONF)

$(AVAILABLE_SRAM_CACHE): $(SRAM_CACHE_SCRIPT)
	mkdir -p $(dir $@)
	python3 $(SRAM_CACHE_SCRIPT) $(SRAM22_MACROS) $@

$(SRAM_CACHE_CONF): $(AVAILABLE_SRAM_CACHE)
	mkdir -p $(dir $@)
	echo "vlsi.inputs.sram_parameters: \"$(AVAILABLE_SRAM_CACHE)\"" > $@
	echo "vlsi.inputs.sram_parameters_meta: [\"transclude\", \"json2list\"]" >> $@

$(SRAM_GENERATOR_CONF): $(SRAM_CACHE_CONF)
	mkdir -p $(dir $@)
	echo "# SRAM generator uses the installed SRAM22 inventory via $(SRAM_CACHE_CONF)" > $@

$(SRAM_CONF): $(SYN_CONF) $(SRAM_CACHE_CONF) $(SRAM_GENERATOR_CONF)
	cd $(vlsi_dir) && $(HAMMER_EXEC) -e $(ENV_YML) $(foreach x,$(INPUT_CONFS) $(SRAM_CACHE_CONF) $(SYN_CONF) $(SRAM_GENERATOR_CONF), -p $(x)) --obj_dir $(OBJ_DIR) -o $@ sram_generator

#########################################################################################
# synthesis input configuration
#########################################################################################
SYN_CONF = $(OBJ_DIR)/inputs.yml
GENERATED_CONFS = $(SYN_CONF) $(SRAM_CONF)

$(SYN_CONF): $(SODOR_TOP_V)
	mkdir -p $(dir $@)
	echo "sim.inputs:" > $@
	echo "  input_files:" >> $@
	for f in $$(find $(RTL_TARGET_DIR) -name "*.v" -o -name "*.sv"); do \
		echo "    - \"$$f\"" >> $@; \
	done
	echo "  input_files_meta: 'append'" >> $@
	echo "synthesis.inputs:" >> $@
	echo "  top_module: $(VLSI_TOP)" >> $@
	echo "  input_files:" >> $@
	for f in $$(find $(RTL_TARGET_DIR) -name "*.v" -o -name "*.sv"); do \
		echo "    - \"$$f\"" >> $@; \
	done

#########################################################################################
# AUTO BUILD FLOW
#########################################################################################

.PHONY: buildfile
buildfile: $(OBJ_DIR)/hammer.d
# Tip: Set HAMMER_D_DEPS to an empty string to avoid unnecessary RTL rebuilds
# TODO: make this dependency smarter so that we don't need this at all
HAMMER_D_DEPS ?= $(GENERATED_CONFS)
$(OBJ_DIR)/hammer.d: $(HAMMER_D_DEPS)
	$(HAMMER_EXEC) -e $(ENV_YML) $(foreach x,$(INPUT_CONFS) $(GENERATED_CONFS), -p $(x)) --obj_dir $(OBJ_DIR) build

-include $(OBJ_DIR)/hammer.d

#########################################################################################
# general cleanup rule
#########################################################################################
.PHONY: clean
clean:
	rm -rf $(VLSI_OBJ_DIR) hammer-vlsi*.log __pycache__ output.json $(GENERATED_CONFS) $(CLASSPATH_CACHE) $(gen_dir) $(SIM_CONF) $(SIM_DEBUG_CONF) $(SIM_TIMING_CONF) $(POWER_CONF)
