// test_multi.c
#include "test_multi.h"

int global_var = 100;

int main() {
    // @jump: global_func
    global_func();
    // @jump: global_var
    return global_var;
}
