#define MULTI_LINE_MACRO(x) \
    int a_##x = 1;          \
    int b_##x = 2;          \
    int c_##x = a_##x + b_##x;

int main() {
    MULTI_LINE_MACRO(1)
    return c_1;
}
