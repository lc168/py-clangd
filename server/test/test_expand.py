import subprocess
import os
import shlex

def get_expanded_macro(file_path, line_num, compiler_args):
    """
    Use clang -E to get the expanded macro at a specific line.
    """
    cmd = ["clang", "-E", "-P"] + compiler_args + [file_path]
    
    try:
        # Run clang -E
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # In a real implementation we would need to parse the -E output 
        # (which doesn't have #line markers if we use -P) 
        # Actually -P removes linemarkers. We WANT linemarkers to find the right line!
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error: {e.stderr}")
        return None

# Test with a simple C file
test_c = """
#define MAX(a,b) ((a) > (b) ? (a) : (b))
int main() {
    int x = 1;
    int y = 2;
    int z = MAX(x+1, y);
    return 0;
}
"""
with open("test_macro.c", "w") as f:
    f.write(test_c)

cmd = ["clang", "-E", "test_macro.c"]
result = subprocess.run(cmd, capture_output=True, text=True, check=True)

lines = result.stdout.splitlines()
for i, line in enumerate(lines):
    if "int z =" in line:
        print(f"Found on line {i}: {line}")

