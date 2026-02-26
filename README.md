# PyClangd

**PyClangd** 是一个基于 **LLVM 22 (libclang)** 和 **Python** 构建的轻量级、高性能 C/C++ 语言服务器（Language Server Protocol, LSP），并提供原生的 VS Code 插件支持。

与原生 `clangd` 相比，PyClangd 创新性地引入了 **SQLite 持久化索引**，旨在解决超大型 C/C++ 代码库（如 Linux 内核源码）在解析和跳转时面临的内存占用过大、全量索引慢等痛点，提供 **100% 确定且精准** 的代码分析与跨文件跳转能力。

## ✨ 核心特性

- **极致的准确性**：底层基于编译器的前端引擎 `libclang`，AST 解析结果与真实编译过程一致，无论是复杂的 C++ 模板还是深层宏定义，都能精准跳转，告别 AI 辅助编程中的“幻觉”定位。
- **轻量级持久化索引**：摒弃传统 LSP 将索引全部驻留在内存的方式，采用 SQLite 将项目符号（Symbols）和 USR (Unified Symbol Resolution) 索引进行持久化存储。极其适合在本地分析数百万行级别的超大工程（如 Linux Kernel）。
- **完善的 LSP 支持**：目前已支持 `textDocument/definition` (跳转到定义)、`textDocument/references` (查找所有引用) 等核心跨文件代码导航功能。
- **构建系统集成**：完美兼容并支持解析标准的 `compile_commands.json` (例如通过 Bear 构建的 C/C++ 编译数据库)。
- **纯本地私有化**：整个解析与查询过程完全在本地（单机）运行，无需依赖云端算力，满足金融、底层架构等高保密业务场景的绝对安全需求。

## 🛠️ 项目架构

项目采用前后端分离架构，通过标准 LSP 协议通信：

- **服务端 (Backend)**：`server/`，纯 Python 实现。核心依赖 `cindex.py` (LLVM 绑定) 和 `sqlite3`。负责 AST 解析、并发索引构建与 LSP 请求处理。
- **客户端 (Frontend)**：`src/`，基于 TypeScript 编写的 VS Code 插件，负责与服务端建立管道并提供无缝的编辑器级代码导航体验。

```text
PyClangd/
├── server/           # Python 后端语言服务器
│   ├── pyclangd_server.py # LSP 协议处理、消息循环与并发调度
│   ├── database.py   # SQLite 持久层：构建 USR 到文件、引用的映射结构
│   └── test/         # 测试框架及单测用例 (支持定义/引用/保存等系统级集成测试)
├── src/              # VS Code 插件源码 (TypeScript)
│   └── extension.ts  # 插件入口点 & LSP 客户端注册
├── package.json      # VS Code 插件元数据与依赖配置
└── requirements.txt  # Python 后端运行依赖
```

## 🚀 快速开始

### 1. 环境准备

目前 PyClangd 依赖本地的 **LLVM 22** 工具链，请确保您的系统中已安装对应版本的 LLVM/Clang。

```bash
# 获取源码
git clone https://gitee.com/lc168/py-clangd.git
cd py-clangd
```

### 2. 插件前端配置

```bash
# 安装 Node.js 依赖
npm install

# 构建 VS Code 插件并在后台监听修改
npm run watch
```

### 3. 后端环境配置

```bash
# 创建并激活 Python 虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 4. 在 VS Code 中配置与使用

1. 按下 `F5` 或通过 VS Code 的 **Run and Debug** 面板运行。这会启动一个新的 "扩展开发宿主" 窗口。
2. 在新窗口的设置（Settings）中搜索 `pyclangd.libraryPath` 参数，指向您环境中的 libclang 库目录。例如：`/home/lc/llvm22/lib`。
3. 打开任意包含 `compile_commands.json` 的标准 C/C++ 项目，即可享受低内存、高精度的代码跳转与引用查询体验！

### (可选) 后端独立运行模式

如果您希望脱离 VS Code 验证解析性能，或对服务端组件进行测试调试：

```bash
# 以当前目录为工作区启动后端引擎，使用16线程并发建库 
./venv/bin/python3 ./server/pyclangd_server.py -d ./ -l /home/lc/llvm22/lib -j 16
```

## 🎯 愿景与设计理念

为什么在 AI 编程助手繁荣的今天，我们仍需要深度定制一个 C/C++ LSP？

1.  **容错率为零的要求**：基于大模型的概率预测可以提供优秀的业务片段续写，但在面对操作系统内核等极其复杂的宏展开、模板递归时往往无能为力。开发者需要的是严谨点击即可无缝追踪溯源的“手术刀”，而非概率性猜测。
2.  **企业级数据隔离**：许多核心工业、底层架构代码绝对禁止联网，无法采用公有云端进行语义分析。轻巧快速的本地化索引引擎是对云端 AI 的战略互补。
3.  **大模型的结构化“眼睛”**：未来的高阶自动化编程势必依赖工程全局背景。单纯给予原文件上下文会令大模型陷入混乱；依靠 PyClangd 抽取出结构化 AST、精准的符号继承树和依赖关系网络喂给大语言模型，能成倍提升 AI 对巨型工程的整体感知能力。

---
*PyClangd - 专注解决超大 C/C++ 巨型项目的本地解析性能瓶颈。*
