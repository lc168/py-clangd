import sys
import os
import json
import shlex

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind
from database import Database

def dump_ast(file_path):
    # Find the compile command
    workspace_dir = '/home/lc/gf_rk3568_kernel/kernel'
    cc_path = os.path.join(workspace_dir, "compile_commands.json")
    
    with open(cc_path, 'r') as f:
        commands = json.load(f)
        
    cmd_info = None
    for cmd in commands:
        if file_path.endswith(cmd.get('file', '')):
            cmd_info = cmd
            break
            
    if not cmd_info:
        print("Command not found for", file_path)
        return
        
    directory = cmd_info.get('directory', '')
    raw_args = cmd_info.get('arguments')
    if not raw_args:
        command_str = cmd_info.get('command', '')
        if command_str: raw_args = shlex.split(command_str)
        else: raw_args = []
        
    compiler_args = Database._clean_compiler_args(raw_args, directory, file_path)
    
    idx = Index.create()
    tu = idx.parse(file_path, args=compiler_args, options=0x01)
    
    for diag in tu.diagnostics:
        print("Diag:", diag)
        
    print("----- AST Walk -----")
    for node in tu.cursor.walk_preorder():
        if not node.location.file: continue
        if "initial_boot_params" in (node.spelling or ""):
            print(f"Found: {node.kind} {node.spelling} at line {node.location.line} col {node.location.column} extent {node.extent.start.line}:{node.extent.start.column}-{node.extent.end.line}:{node.extent.end.column}")

dump_ast("/home/lc/gf_rk3568_kernel/kernel/drivers/of/fdt.c")
