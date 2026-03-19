// 测试场景：宏调用中的参数应该能正确跳转到定义和查找引用
// 复现 bug: platform_driver_register(&arm_sbsa_uart_platform_driver) 中
// arm_sbsa_uart_platform_driver 无法跳转到定义

// 模拟 platform_driver_register 宏
#define platform_driver_register(drv) \
    extern int __platform_driver_register(void*, void*); \
    __platform_driver_register(drv, (void*)0)

struct platform_driver { int x; };

static struct platform_driver my_driver = { .x = 1 }; // @def: my_driver  @ref_target: my_driver

int init(void) {
    platform_driver_register(&my_driver); // @jump: my_driver  @ref_expect: my_driver
    return 0;
}
