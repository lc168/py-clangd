import * as path from 'path';
import * as vscode from 'vscode';
import {
	LanguageClient,
	LanguageClientOptions,
	ServerOptions,
} from 'vscode-languageclient/node';

import { execSync } from 'child_process';
import * as fs from 'fs';

let client: LanguageClient;

// 1. 在 activate 函数外定义一个全局变量
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {

	vscode.window.showErrorMessage('!!! 插件正在激活 !!!');
    // 2. 创建输出通道
    outputChannel = vscode.window.createOutputChannel("PyClangd Info");

    //检查python环境确保环境，不存在就 安装一个
    const extPath = context.extensionPath;
    const venvPath = path.join(extPath, 'venv');
    const pythonPath = path.join(extPath, 'venv', 'bin', 'python');
	const serverModule = path.join(extPath, 'server', 'pyclangd_server.py');

    // 1. 检查 venv 是否存在
    if (!fs.existsSync(pythonPath)) {
        vscode.window.showInformationMessage('正在初始化 PyClangd Python 环境...');
        try {
            // 执行初始化脚本，比如执行项目里的 setup.sh 或直接运行命令
            // 建议在插件根目录放一个简单的 requirements.txt
            const requirements = path.join(extPath, 'requirements.txt');
            execSync(`python3 -m venv "${venvPath}" && "${pythonPath}" -m pip install -r "${requirements}"`);
            vscode.window.showInformationMessage('环境初始化成功！');
        } catch (err) {
            vscode.window.showErrorMessage('初始化 Python 环境失败，请手动配置。');
        }
    }

	// 获取libraryPath 的配置数据
	const libPath = vscode.workspace.getConfiguration('pyclangd').get<string>('libraryPath', '').trim();
	outputChannel.appendLine(`读取到的库路径: ${libPath}`);
	if (!libPath) {
		vscode.window.showErrorMessage(
			'PyClangd: 请先设置 libclang 库路径。打开设置，搜索 "pyclangd.libraryPath"，填写例如 /home/xxx/llvm22/lib 的路径。'
		);
		return;
	}

	const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
	const workspaceRoot = workspaceFolder ? workspaceFolder.uri.fsPath : extPath;

	const serverOptions: ServerOptions = {
		command: pythonPath,
		args: [serverModule, '-d', workspaceRoot, '-l', libPath, '-s'],
		options: {
			env: {
				...process.env,
				PYTHONPATH: path.join(extPath, 'server'),
			},
		},
	};

	// 3. 使用 appendLine 进行打印
    outputChannel.appendLine("--- PyClangd 插件正在启动 ---");
    outputChannel.appendLine(`插件自动执行:${pythonPath} ${serverModule} -d ${workspaceRoot} -l ${libPath} -s`);

    const clientOptions: LanguageClientOptions = {
      documentSelector: [
        { scheme: 'file', language: 'cpp' },
        { scheme: 'file', language: 'c' },
      ],
      // 使用你已经创建好的输出通道
      outputChannel: outputChannel, 
      // ⭐ 核心配置：开启详细追踪模式
      traceOutputChannel: outputChannel 
    };
   
	client = new LanguageClient(
		'pyclangd',
		'PyClangd Language Server',
		serverOptions,
		clientOptions
	); 

	client.start();
	vscode.window.showInformationMessage('PyClangd 启动成功！');
}

export function deactivate(): Thenable<void> | undefined {
	if (!client) { return undefined; }
	return client.stop();
}
