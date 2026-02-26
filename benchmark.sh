#!/bin/bash

# 配置路径
PYTHON_BIN="/home/lc/sda/work/py-clangd/venv/bin/python3"
SERVER_PATH="/home/lc/sda/work/py-clangd/server/pyclangd_server.py"
LIB_PATH="/home/lc/llvm22/lib"
KERNEL_DIR="/home/lc/fg_kernel/linux-6.6.127"
RESULTS_FILE="/home/lc/sda/work/py-clangd/benchmark_results.txt"

# 线程测试列表
#THREAD_LIST=(8 16 28 32 48 64 96 128)
THREAD_LIST=(16 18 19 20 24 25 26 27)

echo "=== PyClangd Indexing Benchmark ===" > $RESULTS_FILE
echo "System Info: $(uname -a)" >> $RESULTS_FILE
echo "Thread List: ${THREAD_LIST[@]}" >> $RESULTS_FILE
echo "-----------------------------------" >> $RESULTS_FILE

cd $KERNEL_DIR

for j in "${THREAD_LIST[@]}"; do
    echo "Testing -j $j ..."
    
    # 清理环境
    rm -rf pyclangd_index.db*
    pkill -9 python3 2>/dev/null
    
    # 记录开始时间
    START_TIME=$(date +%s.%N)
    
    # 执行索引
    $PYTHON_BIN $SERVER_PATH -d ./ -l $LIB_PATH -j $j > /dev/null 2>&1
    
    # 记录结束时间
    END_TIME=$(date +%s.%N)
    
    # 计算耗时
    DURATION=$(echo "$END_TIME - $START_TIME" | bc)
    
    echo "-j $j: $DURATION seconds" >> $RESULTS_FILE
    echo "Completed -j $j in $DURATION seconds"
    
    # 休息一下，让系统内存回收
    sleep 5
done

echo "-----------------------------------" >> $RESULTS_FILE
echo "Benchmark Finished." >> $RESULTS_FILE
cat $RESULTS_FILE
