#ifndef KERNEL_HEADERS_H
#define KERNEL_HEADERS_H

#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>

// [1-32: Previously added basic kernel struct and single-layer macro tests, kept to ensure regression]
extern int global_sys_status; // @def: global_sys_status_decl
#define DEFINE_PER_CPU(type, name) type name
#define DECLARE_PER_CPU(type, name) extern type name
DECLARE_PER_CPU(int, runqueues); // @def: runqueues_decl
#define EXPORT_SYMBOL(sym) // @def: EXPORT_SYMBOL
#define EXPORT_SYMBOL_GPL(sym) // @def: EXPORT_SYMBOL_GPL
struct task_struct { int pid; void* stack; }; // @def: task_pid:pid
#define KERNEL_VERSION 6 // @def: KERNEL_VERSION
struct wait_queue_head { int lock; };
#define DECLARE_WAIT_QUEUE_HEAD(name) struct wait_queue_head name 
struct nested_dev { struct { int dev_id; } info; }; // @def: ns_dev_id:dev_id

#define offsetof(TYPE, MEMBER) ((size_t) &((TYPE *)0)->MEMBER)
#define container_of(ptr, type, member) ({ /* @def: container_of */ \
    const typeof( ((type *)0)->member ) *__mptr = (ptr);    \
    (type *)( (char *)__mptr - offsetof(type,member) );})

struct list_head { struct list_head *next, *prev; }; // @def: list_head_next:next
#define list_entry(ptr, type, member) container_of(ptr, type, member) // @def: list_entry

static inline void init_task(struct task_struct *t) { t->pid = 0; } // @def: init_task
typedef int (*device_init_fn)(struct nested_dev *dev); // @def: device_init_fn:device_init_fn

struct complex_dev {
    union { int dma_addr; void *virt_addr; }; // @def: dma_addr:dma_addr
    unsigned int flags; // @def: flags:flags
};

#define module_param(name, type, perm) static int __param_##name __attribute__((unused)) // @def: module_param
#define likely(x)   __builtin_expect(!!(x), 1) // @def: likely
#define unlikely(x) __builtin_expect(!!(x), 0) // @def: unlikely
#define ALIGN(x, a)     __ALIGN_MASK(x, (typeof(x))(a) - 1) // @def: ALIGN
#define __ALIGN_MASK(x, mask)   (((x) + (mask)) & ~(mask))
#define BIT(nr)         (1UL << (nr)) // @def: BIT
#define min(x, y) ({ typeof(x) _min1 = (x); typeof(y) _min2 = (y); (void) (&_min1 == &_min2); _min1 < _min2 ? _min1 : _min2; }) // @def: min

typedef struct spinlock { union { int rlock; }; } spinlock_t; // @def: spinlock_t:spinlock_t // @def: rlock:rlock
#define DEFINE_SPINLOCK(x)  spinlock_t x = { .rlock = 0 } // @def: DEFINE_SPINLOCK
typedef struct { int counter; /* @def: counter:counter */ } atomic_t; // @def: atomic_t:atomic_t
#define ATOMIC_INIT(i)  { (i) } // @def: ATOMIC_INIT
#define ARRAY_SIZE(arr) (sizeof(arr) / sizeof((arr)[0]) + 0) // @def: ARRAY_SIZE
#define __init
#define __exit
#define __read_mostly

struct device_node {
    const char *name; // @def: dev_node_name:name
    const char *type;
    struct device_node *parent; // @def: dev_node_parent:parent
    struct device_node *child;
    struct device_node *sibling;
};

#define rcu_dereference(p) (p) // @def: rcu_dereference
#define rcu_assign_pointer(p, v) do { (p) = (v); } while (0) // @def: rcu_assign_pointer

#define IS_ERR_VALUE(x) unlikely((unsigned long)(void *)(x) >= (unsigned long)-4095)
static inline long PTR_ERR(const void *ptr) { return (long) ptr; } // @def: PTR_ERR
static inline bool IS_ERR(const void *ptr) { return IS_ERR_VALUE((unsigned long)ptr); } // @def: IS_ERR

struct work_struct { atomic_t data; struct list_head entry; void (*func)(struct work_struct *work); }; // @def: work_func:func
#define DECLARE_WORK(n, f) struct work_struct n = { .data = ATOMIC_INIT(0), .func = (f) } // @def: DECLARE_WORK

struct inode;
struct file;
struct file_operations {
    int (*open) (struct inode *, struct file *); // @def: fops_open:open
    int (*read) (struct file *, char *, size_t, int *); // @def: fops_read:read
};

#define _IOC(dir,type,nr,size) (((dir) << 30) | ((type) << 8) | ((nr) << 0) | ((size) << 16))
#define _IO(type,nr)        _IOC(0, (type), (nr), 0)    // @def: _IO
#define _IOR(type,nr,size)  _IOC(2, (type), (nr), sizeof(size)) // @def: _IOR
#define MY_DEV_MAGIC 'M'
#define MY_DEV_IOCTL_GET    _IOR(MY_DEV_MAGIC, 1, int) // @def: MY_DEV_IOCTL_GET

struct completion { unsigned int done; /* @def: comp_done:done */ struct wait_queue_head wait; /* @def: comp_wait:wait */ };
#define DECLARE_COMPLETION(work) struct completion work = { 0, { 0 } } // @def: DECLARE_COMPLETION

struct kref { atomic_t refcount; }; // @def: kref_refcount:refcount
static inline void kref_init(struct kref *kref) { kref->refcount.counter = 1; } // @def: kref_init

#define BUG_ON(condition) do { if (unlikely(condition)) while(1); } while (0) // @def: BUG_ON
#define WARN_ON(condition) ({ int __ret_warn_on = !!(condition); if (unlikely(__ret_warn_on)) {} __ret_warn_on; }) // @def: WARN_ON

struct flex_array_data { int count; int payload[]; }; // @def: flex_payload:payload
extern int syscall_table_size __read_mostly; // @def: syscall_table_size_decl

// ---------------------------------------------------------
// 高级复杂度区: 宏套宏 (Macros wrapping Macros)
// ---------------------------------------------------------

// 33. SYSCALL_DEFINE hierarchy (System Call definition)
struct pt_regs;

#define SYSCALL_DEFINE1(name, t1, a1) int sys_##name(t1 a1) // @def: SYSCALL_DEFINE1
#define SYSCALL_DEFINE2(name, t1, a1, t2, a2) int sys_##name(t1 a1, t2 a2) // @def: SYSCALL_DEFINE2
#define SYSCALL_DEFINE3(name, t1, a1, t2, a2, t3, a3) int sys_##name(t1 a1, t2 a2, t3 a3) // @def: SYSCALL_DEFINE3
#define SYSCALL_DEFINE(name) SYSCALL_DEFINE1(name, int, arg1) // @def: SYSCALL_DEFINE

// 34. initcall hierarchy (Module initialization layers)
typedef int (*initcall_t)(void); // @def: initcall_t:initcall_t

#define __define_initcall(fn, id) \
    static initcall_t __initcall_##fn##id __attribute__((__used__)) \
    __attribute__((__section__(".initcall" #id ".init"))) = fn // @def: __define_initcall

#define core_initcall(fn)       __define_initcall(fn, 1) // @def: core_initcall
#define postcore_initcall(fn)   __define_initcall(fn, 2)
#define arch_initcall(fn)       __define_initcall(fn, 3)
#define subsys_initcall(fn)     __define_initcall(fn, 4) // @def: subsys_initcall
#define fs_initcall(fn)         __define_initcall(fn, 5) // @def: fs_initcall
#define device_initcall(fn)     __define_initcall(fn, 6)
#define late_initcall(fn)       __define_initcall(fn, 7) // @def: late_initcall

#define module_init(x)  __define_initcall(x, 1) // @def: module_init
#define module_exit(x)  __define_initcall(x, 0) // @def: module_exit

// 35. Platform driver and Device Driver macros
struct device {
    struct device *parent; // @def: dev_parent:parent
    void *platform_data; // @def: dev_pdata:platform_data
};

struct platform_driver {
    int (*probe)(struct device *); // @def: pdrv_probe:probe
    int (*remove)(struct device *);
    const char *driver_name;
};

#define module_platform_driver(platform_driver) /* @def: module_platform_driver */ \
    static int __init platform_driver_init(void) \
    { \
        return 0; \
    } \
    module_init(platform_driver_init); \
    static int __exit platform_driver_exit(void) \
    { return 0; \
    } \
    module_exit(platform_driver_exit);

// 36. DEVICE_ATTR macros (Sysfs)
struct device_attribute {
    const char *name;
    int (*show)(struct device *dev, char *buf); // @def: dattr_show:show
    int (*store)(struct device *dev, const char *buf, size_t count); // @def: dattr_store:store
};

#define __ATTR(_name, _mode, _show, _store) { /* @def: __ATTR */ \
    .name = __stringify(_name), \
    .show = _show,                  \
    .store  = _store,               \
}

#define __ATTR_RO(_name) { /* @def: __ATTR_RO */ \
    .name = __stringify(_name), \
    .show = _name##_show, \
}

#define DEVICE_ATTR(_name, _mode, _show, _store) /* @def: DEVICE_ATTR */ \
    struct device_attribute dev_attr_##_name = __ATTR(_name, _mode, _show, _store)

#define DEVICE_ATTR_RO(_name) /* @def: DEVICE_ATTR_RO */ \
    struct device_attribute dev_attr_##_name = __ATTR_RO(_name)

#define __stringify_1(x...) #x
#define __stringify(x...)   __stringify_1(x) // @def: __stringify

// 37. DECLARE_BITMAP and related bitops
#define BITS_PER_BYTE 8
#define BITS_TO_LONGS(nr)   (((nr) + BITS_PER_BYTE * sizeof(long) - 1) / (BITS_PER_BYTE * sizeof(long)))
#define DECLARE_BITMAP(name,bits) /* @def: DECLARE_BITMAP */ \
    unsigned long name[BITS_TO_LONGS(bits)]

// 38. THIS_MODULE dummy typical of kernel
struct module;
extern struct module __this_module;
#define THIS_MODULE (&__this_module) // @def: THIS_MODULE

#include "test_kernel_headers_part2.h"
#endif
