# Tests natifs du cœur du firmware.
#
# hb_core et hb_protocol sont du C99 pur : ils se compilent tels quels ici,
# sans carte ni chaîne d'outils AVR.

CC      ?= cc
CFLAGS  ?= -std=c99 -Wall -Wextra -Wpedantic -Wshadow -Wconversion \
           -Wno-sign-conversion -O2 -g
CPPFLAGS = -I../firmware/handbrake
LDLIBS   = -lm

BUILD   = build
FW      = ../firmware/handbrake
SOURCES = $(FW)/hb_core.c $(FW)/hb_protocol.c $(FW)/hb_record.c
BINS    = $(BUILD)/test_hb_core $(BUILD)/test_hb_protocol \
          $(BUILD)/test_hb_record

.PHONY: all test clean
all: $(BINS)

$(BUILD):
	mkdir -p $(BUILD)

$(BUILD)/test_%: test_%.c $(SOURCES) test_harness.h \
        $(FW)/hb_core.h $(FW)/hb_protocol.h $(FW)/hb_record.h $(FW)/config.h | $(BUILD)
	$(CC) $(CFLAGS) $(CPPFLAGS) -o $@ $< $(SOURCES) $(LDLIBS)

test: $(BINS)
	@rc=0; for t in $(BINS); do echo "== $$t"; ./$$t || rc=1; done; exit $$rc

clean:
	rm -rf $(BUILD)
