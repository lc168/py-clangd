# PyClangd

PyClangd 是一个基于 **LLVM 22** 的轻量级 C/C++ 语言服务器（LSP），使用 Python 编写后端逻辑，并为 VS Code 提供插件支持。

它旨在通过 `libclang` 的强大 AST 分析能力与 SQLite 的持久化索引，实现精准的跨文件代码跳转与分析。

## 🚀 核心特性

- **跨文件跳转**：利用 USR (Unified Symbol Resolution) 技术，在全项目范围内精准定位函数定义。
- **LLVM 22 支持**：针对最新版本的 Clang AST 特性进行优化。
- **轻量级索引**：使用 SQLite 存储符号信息，无需像原生 clangd 那样占用大量内存进行实时全量索引。
- **Bear 集成**：完美适配 `compile_commands.json` 编译数据库。

## 📂 项目结构

```text
PyClangd/
├── server/           # Python 语言服务器 (Backend)
│   ├── cindex.py     # LLVM 22 Python Bindings
│   ├── database.py   # SQLite 索引逻辑
│   ├── indexer.py    # 项目符号扫描器
│   └── server.py     # LSP 协议实现
├── vscode/           # VS Code 扩展 (Frontend)
│   ├── src/          # TypeScript 源码
│   └── package.json  # 插件元数据
└── pyclangd_index.db # 运行生成的索引数据库
```
