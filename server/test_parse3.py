import sys
import os

sys.path.append('/home/lc/py-clangd/server')
import clang_init
from cindex import Index, CursorKind

source = """
extern void *extern_var;
void *tentative_var;
void *init_var = 0;
"""

with open("test_snippet3.c", "w") as f:
    f.write(source)

idx = Index.create()
tu = idx.parse("test_snippet3.c", args=["-fsyntax-only"])

for node in tu.cursor.walk_preorder():
    if node.kind == CursorKind.VAR_DECL:
        print(f"--- {node.spelling} ---")
        print(f"Is def: {node.is_definition()}")
        
        # Test how to distinguish extern vs tentative
        print(f"Storage class: {node.storage_class}")
        
        # The referenced node of a declaration is usually itself.
        referenced = node.referenced
        print(f"Referenced is self? {referenced == node}")
        
        # node.get_definition()
        defn = node.get_definition()
        print(f"node.get_definition() is self? {defn == node if defn else 'None'}")
