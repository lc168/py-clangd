// 测试场景1：SIMPLE_DEV_PM_OPS 宏参数跳转（复现 amba-pl011.c:2710 bug）
// 测试场景2：宏调用处点击宏名本身（SIMPLE_DEV_PM_OPS / SET_SYSTEM_SLEEP_PM_OPS）能否跳到 #define

struct device;

struct dev_pm_ops {
    int (*suspend)(struct device *dev);
    int (*resume)(struct device *dev);
};

#define SET_SYSTEM_SLEEP_PM_OPS(suspend_fn, resume_fn) .suspend = suspend_fn, .resume = resume_fn,  // @def: SET_SYSTEM_SLEEP_PM_OPS

#define SIMPLE_DEV_PM_OPS(name, suspend_fn, resume_fn) const struct dev_pm_ops name = { SET_SYSTEM_SLEEP_PM_OPS(suspend_fn, resume_fn) }  // @def: SIMPLE_DEV_PM_OPS

static int my_pm_suspend(struct device *dev) { return 0; } // @def: my_pm_suspend
static int my_pm_resume(struct device *dev) { return 0; }  // @def: my_pm_resume

// 场景1: 点击宏参数 my_pm_suspend 应跳到其函数定义
static SIMPLE_DEV_PM_OPS(my_pm_ops, my_pm_suspend, my_pm_resume); // @jump: my_pm_suspend

// 场景2: 点击宏名 SIMPLE_DEV_PM_OPS 应跳到 #define
void use_macro(void) {
    SIMPLE_DEV_PM_OPS(my_pm_ops2, my_pm_suspend, my_pm_resume); // @jump: SIMPLE_DEV_PM_OPS
}

// 场景3: 直接调用 SET_SYSTEM_SLEEP_PM_OPS，点击宏名应跳到 #define
struct dev_pm_ops my_ops2 = {
    SET_SYSTEM_SLEEP_PM_OPS(my_pm_suspend, my_pm_resume) // @jump: SET_SYSTEM_SLEEP_PM_OPS
};
