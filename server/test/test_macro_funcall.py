#!/usr/bin/env python3
import os
import sys
# 保持你的路径添加不变
sys.path.append("/home/lc/py-clangd/server")
import clang_init
from cindex import Index, CursorKind, TranslationUnit

def extract_symbols_and_refs(node, kong=""):
        definitions = []
        references = set() # 用 set 去重
             

        if not node.location.file:
            return definitions, list(references)
        
        kind = node.kind
        
        # ==========================================
        # 🎯 提取定义 (Definitions)
        # ==========================================
        if (kind.is_declaration() and node.is_definition()) or kind == CursorKind.MACRO_DEFINITION:
            usr = node.get_usr()
            if usr:
                definitions.append((
                    usr, 
                    kind.name,
                    node.location.file.name, 
                    node.extent.start.line, 
                    node.extent.start.column,
                    node.extent.end.line,
                    node.extent.end.column
                ))
                print(f"{kong}definitions={definitions}")


        # ==========================================
        # 🎯 提取引用 (References) - 100% 滴水不漏版
        # ==========================================
        # 1. kind.is_reference() 涵盖了: TYPE_REF, LABEL_REF, NAMESPACE_REF, TEMPLATE_REF 等纯引用节点
        # 2. 表达式里的引用需要单点指定: DECL_REF_EXPR(变量/函数引用), MEMBER_REF_EXPR(结构体 p->x 引用)
        # 3. 宏展开: MACRO_INSTANTIATION
        
        is_ref_node = (
            kind.is_reference() or 
            kind in (
                CursorKind.DECL_REF_EXPR, 
                CursorKind.MEMBER_REF_EXPR, 
                CursorKind.MACRO_INSTANTIATION
            )
        )

        if is_ref_node:
            callee = node.referenced
            if callee and callee != node:
                usr = callee.get_usr()
                if usr:
                    references.add((
                        usr,
                        kind.name,
                        node.location.file.name, 
                        node.extent.start.line, 
                        node.extent.start.column,
                        node.extent.end.line,
                        node.extent.end.column
                    ))
                print(f"{kong}references={references}")

        return definitions, list(references)

gFunction = None; #保留记录上一个函数定义的 Cursor 对象
gdepth = 0; #全局 depth 变量，记录当前遍历的深度
def show1(node, depth=0):
    global gFunction, gdepth

    # kong = ">" * depth
    # file = node.location.file if node.location else "None"
    # ref_usr = node.referenced.get_usr() if node.referenced else "None"
    # usr = node.get_usr() if node else "None"
    #    #打印一下准备存入数据库的数据
    # print(f"ref_usr:[{ref_usr}]usr:[{usr}] 2|spelling:[{node.spelling}] 3|kind:[{node.kind}] 4|{file}:{node.location.line}:{node.location.column} 5|depth=[{depth}]")
    #extract_symbols_and_refs(node, kong)
    if node.kind == CursorKind.FUNCTION_DECL:
        gFunction = node.get_usr()
        gdepth = depth
    
    if node.kind == CursorKind.CALL_EXPR and depth > gdepth:
        print(f"Call:{gFunction} -> {node.referenced.get_usr()}")

    
    for child in node.get_children():
        show1(child, depth + 1)


# 确保使用正确的 Flag
# PARSE_DETAILED_PROCESSING_RECORD = 1
idx = Index.create()
tu = idx.parse("test_funcall.c", options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)

# 解析完成后检查诊断信息
for diag in tu.diagnostics:
    # level: Error/Warning/Note
    print(f"{diag.severity}: {diag.spelling} "
          f"at {diag.location.file}:{diag.location.line}")

show1(tu.cursor)