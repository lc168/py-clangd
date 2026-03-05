enum Color {
    RED, // @def: RED
    BLUE // @def: BLUE
};

union Data {
    int i; // @def: d_i
    float f; // @def: d_f
};

int main() {
    enum Color c = BLUE; // @jump: BLUE
    union Data d;
    d.i = 10; // @jump: d_i
    return 0;
}
