import subprocess

test_c = """
#define MAX(a,b) ((a) > (b) ? (a) : (b))
int main() {
    int x = 1;
    int y = 2;
    int z = /*PYCLANGD_START*/ MAX(x+1, y) /*PYCLANGD_END*/;
    return 0;
}
"""
with open("test_macro_marker.c", "w") as f:
    f.write(test_c)

cmd = ["clang", "-E", "-C", "test_macro_marker.c"]
result = subprocess.run(cmd, capture_output=True, text=True, check=True)

import re
match = re.search(r'/\*PYCLANGD_START\*/(.*?)/\*PYCLANGD_END\*/', result.stdout, re.DOTALL)
if match:
    print(f"EXPANDED: {match.group(1).strip()}")
else:
    print("NOT FOUND")
