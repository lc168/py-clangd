
#define MAX(a,b) ((a) > (b) ? (a) : (b))
int main() {
    int x = 1;
    int y = 2;
    int z = /*PYCLANGD_START*/ MAX(x+1, y) /*PYCLANGD_END*/;
    return 0;
}
