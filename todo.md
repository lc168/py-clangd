# 1 调整测试架构，换成多文件索引json, 然后直接使用database.py的函数查表，函数是封装的sql语句
#      测试整个索引函数，而不是一个函数
#      调整compile_commands.json的读取方式
#   考虑怎么解决头文件，不被分析的问题, 
        方案1，从哪里跳转来的？
        方案2，直接查询compile_commands.json文件
        方案3， make -Bn进行数据分析
        方案4，在parse分析的时候，记录头文件（最可能）

# 2 仔细研究和分析清楚，目前的代码
# 3   主要是pares解析出来的数据是什么，通过简单的例子好好分析一下 
# 4   好好考虑一下，数据库的表结构，


# 新功能
 # 无效宏区域暗淡，
 # 宏展开后的代码高亮
 # 函数调用关系图的绘制
 # 结构体成员的跳转？？

# 将libclangd移动到，插件内部，避免这种 -I /xxx 的外部依赖
# 需要ubuntu24？？否则不能使用？

# 我发现libclangd库是在我的代码中是一个很大的问题，
# 出于对新llvm新版本特性的需要，和未来深度定制的需要，我自己编译了llmv22/libclangd库，
# 但是这样导致的后果是，我的代码中大量硬编码了：lib_path 这种代码
    lib_path = find_lib_path()
    from cindex import Config
    try:
        Config.set_library_path(lib_path)
    except Exception: pass

# 我应该怎么解决，让代码更加简洁呢？
# 1 直接把我编译的llvm22安装到整个系统的环境变量中
# 2 直接把我编译的llmv22放到插件目录下面，直接集成到插件中


