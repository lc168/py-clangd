// 测试场景：SIMPLE_DEV_PM_OPS 宏参数跳转
// 复现 bug: SIMPLE_DEV_PM_OPS(name, suspend_fn, resume_fn)
// 中 suspend_fn 无法跳转到定义

struct device;

struct dev_pm_ops {
    int (*suspend)(struct device *dev);
    int (*resume)(struct device *dev);
};

#define SET_SYSTEM_SLEEP_PM_OPS(suspend_fn, resume_fn) \
    .suspend = suspend_fn, \
    .resume = resume_fn,

#define SIMPLE_DEV_PM_OPS(name, suspend_fn, resume_fn) \
    const struct dev_pm_ops name = { \
        SET_SYSTEM_SLEEP_PM_OPS(suspend_fn, resume_fn) \
    }

static int my_pm_suspend(struct device *dev) { return 0; } // @def: my_pm_suspend
static int my_pm_resume(struct device *dev) { return 0; }  // @def: my_pm_resume

static SIMPLE_DEV_PM_OPS(my_pm_ops, my_pm_suspend, my_pm_resume); // @jump: my_pm_suspend
