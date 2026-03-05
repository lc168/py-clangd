CC = clang
CXX = clang++
CFLAGS = -xc -I.
CXXFLAGS = -xc++ -std=c++17 -I.

# Find all C and C++ files in the current directory
C_SOURCES = $(wildcard *.c)
CXX_SOURCES = $(wildcard *.cpp)

# Define corresponding object files
OBJECTS = $(C_SOURCES:.c=.o) $(CXX_SOURCES:.cpp=.o)

all: $(OBJECTS)

# Rule for compiling C files
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# Rule for compiling C++ files
%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f *.o pyclangd_index.db compile_commands.json

.PHONY: all clean
