
#define MAX(a,b) ((a) > (b) ? (a) : (b));\
a=8;\
b = 9;

#define MULTI_LINE_MACRO(x) \
    int a_##x = 1;          \
    int b_##x = 2;          \
    int c_##x = a_##x + b_##x;



  

int k = 10;
int main() {
    int x = 1;
    int y = 2;
    int z = MAX(x+1, y);
    int z1 = MAX(x+2, y+1);
    MULTI_LINE_MACRO(1)
    return 0;
}

#include "test_macro.h"
MAX2(1,2)
#include "test_macro.h"
MAX2(1,2)
