#define MY_MACRO 100 // @def: MY_MACRO

void bar(int x) {} // @def: bar

int main() {
    int x = MY_MACRO; // @jump: MY_MACRO
    bar(x); // @jump: bar
    return 0;
}
