cmake_minimum_required(VERSION 3.15)
project(PyClangd-Core)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# 1. 明确指定 LLVM 23 的路径
set(LLVM_INSTALL_DIR "/home/lc/llvm23")
list(APPEND CMAKE_PREFIX_PATH "${LLVM_INSTALL_DIR}")

find_package(Clang REQUIRED CONFIG)

# 2. 【核心修复】同步 LLVM 的编译选项
# 这会自动处理 -fno-rtti 以及其他必要的宏定义
include_directories(${CLANG_INCLUDE_DIRS})
add_definitions(${CLANG_DEFINITIONS})

# 如果上面的 add_definitions 没起作用，手动强制关闭 RTTI
if(NOT LLVM_ENABLE_RTTI)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fno-rtti")
endif()

set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} -fuse-ld=lld")
add_executable(PyClangd-Core main.cpp)

# 3. 修正链接逻辑
# 使用 clang-cpp (你已确认存在) 
# 使用 ${LLVM_AVAILABLE_LIBS} 代替写死的 LLVM，它会自动展开成 libLLVMSupport.a 等一长串库
target_link_libraries(PyClangd-Core
    PRIVATE
    clang-cpp
    LLVMSupport
    #${LLVM_AVAILABLE_LIBS}
)

