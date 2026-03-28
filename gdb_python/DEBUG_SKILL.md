# Skill: GDB Debugging Expert

## 🧠 诊断逻辑
1. **崩溃定位：** 当程序产生 SIGSEGV 时，首先调用 `get_backtrace` 确定故障函数。
2. **状态检查：** 检查崩溃行的局部变量，特别是涉及指针操作的变量。
3. **内存审计：** 如果涉及内存分配，引导用户检查 `kmalloc`/`malloc` 的返回值。
4. **反汇编辅助：** 如果源码信息缺失，调用 `execute_gdb_command(command="disassemble")` 分析汇编逻辑。

## ⚠️ 安全约束
- 严禁执行 `shell` 命令。
- 仅允许对指定的测试二进制文件进行调试。
- 在执行 `-exec-run` 前必须确认断点已设置。