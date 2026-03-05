/**
 * 测试 lsp_references 对【typedef 类型别名】的引用查找
 *
 * 场景：
 *  1. typedef 的类型名被用于变量声明、函数参数、返回值
 *  2. 确保所有用到该类型名的地方都能被追踪到
 */

typedef unsigned int uint32; // @ref_target: uint32

typedef struct {
    uint32 id;    // @ref_expect: uint32
    uint32 value; // @ref_expect: uint32
} Record;

uint32 create_id() { // @ref_expect: uint32
    return 1001;
}

void process(uint32 count) { // @ref_expect: uint32
    uint32 i = 0; // @ref_expect: uint32
    (void)count;
    (void)i;
}

int main() {
    uint32 x = create_id(); // @ref_expect: uint32
    process(x);
    return 0;
}
