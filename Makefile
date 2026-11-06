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

# every source in src/, as next.py's rebuild check counts them, so make and next.py agree on what's stale
SRCS := $(wildcard src/*.cpp src/*.h src/*.inc)

$(LIB): $(SRCS)
	@mkdir -p lib
	$(CXX) $(CXXFLAGS) $(SHARED) -o $@ src/zxcore.cpp src/nextcore.cpp

test: $(LIB)
	./tests/run.sh

clean:
	rm -rf lib

.PHONY: test clean
