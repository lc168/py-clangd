# 自动获取 LLVM 23 的编译选项
export LLVM_DIR=/home/lc/llvm23
export PATH=$LLVM_DIR/bin:$PATH

LLVM_FLAGS=$(llvm-config --cxxflags --ldflags --libs)

clang++ -shared -fPIC -O3 \
    $LLVM_FLAGS \
    KernelLogEnhancer.cpp \
    -o libKernelLogEnhancer.so