import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind

source = """
extern void *extern_var;
void *tentative_var;
static void *tentative_static;
void *init_var = 0;
"""

with open("test_snippet5.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet5.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if not node.location.file:
        continue
    
    kind = node.kind
    is_def = node.is_definition()
    if not is_def and kind == CursorKind.VAR_DECL:
        if node.storage_class.name != 'EXTERN':
            is_def = True

    if is_def or kind == CursorKind.MACRO_DEFINITION:
        usr = node.get_usr()
        if usr:
            print(f"DEF: {node.spelling} {node.storage_class.name}")
        continue
    
    is_ref_node = (
        kind.is_declaration() or
        kind.is_reference() or
        kind in (
            CursorKind.DECL_REF_EXPR, 
            CursorKind.MEMBER_REF_EXPR, 
            CursorKind.MACRO_INSTANTIATION,
            CursorKind.CALL_EXPR
        )
    )

    if is_ref_node:
        callee = node.referenced
        if callee:
            usr = callee.get_usr()
            if usr:
                print(f"REF: {node.spelling} (to {callee.spelling})")
        continue
