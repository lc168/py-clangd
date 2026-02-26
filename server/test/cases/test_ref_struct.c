/**
 * 测试 lsp_references 对【struct 字段】的引用查找
 *
 * 场景：
 *  1. 同一个 struct 的字段在多个不同函数体中被读写
 *  2. 两个 struct 各自有同名字段 `value`，引用查找必须精准区分，不相互干扰
 */

struct Point {
    int x; // @ref_target: point_x
    int y;
};

struct Rect {
    int x; // @ref_target: rect_x
    int width;
    int height;
};

void init_point(struct Point *p) {
    p->x = 0; // @ref_expect: point_x
    p->y = 0;
}

void move_point(struct Point *p, int dx) {
    p->x += dx; // @ref_expect: point_x
}

int get_point_x(struct Point *p) {
    return p->x; // @ref_expect: point_x
}

void init_rect(struct Rect *r) {
    r->x = 10; // @ref_expect: rect_x
    r->width = 100;
}

int get_rect_x(struct Rect *r) {
    return r->x; // @ref_expect: rect_x
}
