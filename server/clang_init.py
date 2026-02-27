#!/usr/bin/env python3
import os
from cindex import Config

def setup_clang_library():
    # 如果已经加载过，直接跳过
    if Config.loaded:
        return
        
    # 获取当前文件所在的文件目录 (即 .../py-clangd/server)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 相对路径指向你的动态库目录
    lib_path = os.path.join(current_dir, "libs")
    
    try:
        Config.set_library_path(lib_path)
    except Exception:
        pass

setup_clang_library()
