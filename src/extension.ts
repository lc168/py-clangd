import * as path from 'path';
import * as vscode from 'vscode';
import {
	LanguageClient,
	LanguageClientOptions,
	ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient;

// 1. 在 activate 函数外定义一个全局变量
let outputChannel: vscode.OutputChannel;

export function activate(context: vscode.ExtensionContext) {

	vscode.window.showErrorMessage('!!! 插件正在激活 !!!');
    // 2. 创建输出通道
    outputChannel = vscode.window.createOutputChannel("PyClangd Info");

	// 扩展安装目录（内含 server/、venv/）
	const extPath = context.extensionPath;
	const pythonPath = path.join(extPath, 'venv', 'bin', 'python');
	const serverModule = path.join(extPath, 'server', 'server.py');

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
