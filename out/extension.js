"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.activate = activate;
exports.deactivate = deactivate;
const path = __importStar(require("path"));
const vscode = __importStar(require("vscode"));
const node_1 = require("vscode-languageclient/node");
let client;
// 1. 在 activate 函数外定义一个全局变量
let outputChannel;
function activate(context) {
    vscode.window.showErrorMessage('!!! 插件正在激活 !!!');
    // 2. 创建输出通道
    outputChannel = vscode.window.createOutputChannel("PyClangd Info");
    // 扩展安装目录（内含 server/、venv/）
    const extPath = context.extensionPath;
    const pythonPath = path.join(extPath, 'venv', 'bin', 'python');
    const serverModule = path.join(extPath, 'server', 'server.py');
    const libPath = vscode.workspace.getConfiguration('pyclangd').get('libraryPath', '').trim();
    outputChannel.appendLine(`读取到的库路径: ${libPath}`);
    if (!libPath) {
        vscode.window.showErrorMessage('PyClangd: 请先设置 libclang 库路径。打开设置，搜索 "pyclangd.libraryPath"，填写例如 /home/xxx/llvm22/lib 的路径。');
        return;
    }
    const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
    const workspaceRoot = workspaceFolder ? workspaceFolder.uri.fsPath : extPath;
    const serverOptions = {
        command: pythonPath,
        args: [serverModule, '-d', workspaceRoot, '-s', '-l', libPath],
        options: {
            env: {
                ...process.env,
                PYTHONPATH: path.join(extPath, 'server'),
            },
        },
    };
    // 3. 使用 appendLine 进行打印
    outputChannel.appendLine("--- PyClangd 插件正在启动 ---");
    outputChannel.appendLine(`Python 路径: ${path.join(context.extensionPath, 'venv', 'bin', 'python')}`);
    const clientOptions = {
        documentSelector: [
            { scheme: 'file', language: 'cpp' },
            { scheme: 'file', language: 'c' },
        ],
        // 使用你已经创建好的输出通道
        outputChannel: outputChannel,
        // ⭐ 核心配置：开启详细追踪模式
        traceOutputChannel: outputChannel
    };
    client = new node_1.LanguageClient('pyclangd', 'PyClangd Language Server', serverOptions, clientOptions);
    client.start();
    vscode.window.showInformationMessage('PyClangd 启动成功！');
}
function deactivate() {
    if (!client) {
        return undefined;
    }
    return client.stop();
}
//# sourceMappingURL=extension.js.map