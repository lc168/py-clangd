typedef int MyInt; // @def: MyInt:MyInt

struct Point {
    MyInt x; // @def: p_x:x
    MyInt y; // @def: p_y:y
};

int main() {
    MyInt a = 1; // @jump: MyInt:MyInt
    struct Point p;
    p.x = 2; // @jump: p_x:x
    return 0;
}
