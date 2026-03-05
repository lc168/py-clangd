
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define MULTI_LINE_MACRO(x) addv4(x, x)

int addv1(int a,  int b){
    return a+b;
}

int addv2(int a,  int b){
    addv1(a, b);
    return a+b;
}

int addv3(int a,  int b){
    addv1(a, b);
    addv2(a, b);
    return a+b;
}

int addv4(int a,  int b){
    addv1(a, b);
    addv2(a, b);
    addv3(a, b);
    return a+b;
}


int k = 10;
int main() {
    int x = 1;
    int y = 2;
    int z = MAX(x+1, y);
    int z1 = MAX(x+2, y+1);
    MULTI_LINE_MACRO(1)
    MULTI_LINE_MACRO(2)
    return 0;
}

