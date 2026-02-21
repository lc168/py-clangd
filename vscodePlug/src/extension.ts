import * as path from 'path';
import * as vscode from 'vscode';
import {
	LanguageClient,
	LanguageClientOptions,
	ServerOptions,
} from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
	// 扩展安装目录（内含 server/、venv/）
	const extPath = context.extensionPath;
	const pythonPath = path.join(extPath, 'venv', 'bin', 'python');
	const serverModule = path.join(extPath, 'server', 'server.py');

	const libPath = vscode.workspace.getConfiguration('pyclangd').get<string>('libraryPath', '').trim();
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

	const clientOptions: LanguageClientOptions = {
		documentSelector: [
			{ scheme: 'file', language: 'cpp' },
			{ scheme: 'file', language: 'c' },
		],
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
