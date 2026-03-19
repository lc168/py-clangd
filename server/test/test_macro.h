#define MAX(a,b) ((a) > (b) ? (a) : (b))

int test_func(int a, int b) {
    return MAX(a,b);
}

#define Func2(a, b)  MAX(a,b);test_func(a,b);