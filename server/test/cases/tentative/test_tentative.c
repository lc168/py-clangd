/*
 * Test for tentative definitions (e.g. variables without initializers or extern keyword)
 * ensuring they are correctly captured as definitions and can be navigated to.
 */

void *initial_boot_params; // @def: initial_boot_params // @ref_target: initial_boot_params

static int my_static_var; // @def: my_static_var // @ref_target: my_static_var

void test_tentative() {
    // Test jumping and referencing tentative definitions
    initial_boot_params = 0; // @jump: initial_boot_params // @ref_expect: initial_boot_params
    my_static_var = 1;       // @jump: my_static_var // @ref_expect: my_static_var
}
