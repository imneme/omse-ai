# omse-ai: `make` builds the headless core that speccy.py loads with ctypes.
# (speccy.py runs this itself when the library is missing or older than src/.)
# Needs a C++20 compiler; CXX=clang++ or CXX=g++ to choose one.
CXXFLAGS = -O3 -std=c++20 -Wall -fPIC

ifeq ($(shell uname -s),Darwin)
LIB = lib/libzxcore.dylib
SHARED = -dynamiclib
else
LIB = lib/libzxcore.so
SHARED = -shared
endif

$(LIB): src/zxcore.cpp src/nextcore.cpp src/nextregs_reset.inc src/z80.h src/ay38910.h src/sdcard.h src/next_audio.h src/next_dma.h \
		src/next_dma_bus.inc
	@mkdir -p lib
	$(CXX) $(CXXFLAGS) $(SHARED) -o $@ src/zxcore.cpp src/nextcore.cpp

test: $(LIB)
	./tests/run.sh

clean:
	rm -rf lib

.PHONY: test clean
