from mcp.server.fastmcp import FastMCP
from pygdbmi.gdbcontroller import GdbController

# 初始化 MCP
mcp = FastMCP("GDB_Expert")

# 初始化 GDB 控制器
# 建议在虚拟机或 Docker 中运行，因为它会启动一个真实的 GDB 进程
gdb = GdbController()

@mcp.tool()
def execute_gdb_command(command: str) -> list:
    """执行原生的 GDB 指令并返回解析后的 JSON 结果。"""
    # 示例输入: "-break-insert main", "-exec-run"
    response = gdb.write(command)
    return response

@mcp.tool()
def get_backtrace() -> str:
    """获取当前堆栈信息。"""
    response = gdb.write("-stack-list-frames")
    # 这里可以根据需要提取关键信息，精简返回给 AI 的 Token 数量
    return str(response)

@mcp.tool()
def read_variable(var_name: str) -> str:
    """读取当前上下文中的变量值。"""
    response = gdb.write(f"-data-evaluate-expression {var_name}")
    return str(response)

if __name__ == "__main__":
    mcp.run()