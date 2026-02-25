// test_typedef.c
// @def: MyInt
typedef int MyInt;

struct Point {
    // @def: p_x
    MyInt x;
    // @def: p_y
    MyInt y;
};

int main() {
    // @jump: MyInt
    MyInt a = 1;
    struct Point p;
    // @jump: p_x
    p.x = 2;
    return 0;
}
