使用llvm pass 技术 在内核的 log输出前面加上 [文件名称+行号]的代码 和 具体操作过程

1. build.sh,编译代码KernelLogEnhancer.cpp -> libKernelLogEnhancer.so

2 那现在的关键在于，我如何使用 我自己编译的llvm23去编译现在的 arm64内核代码呢？

我之前是aarch64-linux-gnu-gcc编译的
编译指令是：
make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-Wno-error -Wno-dangling-pointer -Wno-address -Wno-implicit-function-declaration" Image -j20


llvm23编译内核的指令是：
# 1. 设置 LLVM 路径
export LLVM_PATH=/home/lc/llvm23/bin
export PATH=$LLVM_PATH:$PATH

make ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu- olddefconfig
make ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu- defconfig_v2

make ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu- menuconfig

# 2. 执行编译
make ARCH=arm64 LLVM=1 LLVM_IAS=1 CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS="-g -fpass-plugin=/home/lc/py-clangd/add_kernel_pl/libKernelLogEnhancer.so -Wno-error" Image -j20

