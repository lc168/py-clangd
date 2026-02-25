#include "test_multi.h"

int global_var = 100; // @def: global_var_def

int main() {
    global_func(); // @jump: global_func
    return global_var; // @jump: global_var_def
}
