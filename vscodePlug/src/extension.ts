import * as path from 'path';
import * as vscode from 'vscode';
import {
	LanguageClient,
	LanguageClientOptions,
	ServerOptions,
	TransportKind
} from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(context: vscode.ExtensionContext) {
	// 关键点：server.py 的相对位置是从编译后的 out/extension.js 开始算的
	// 所以路径是 ../../server/server.py
	// const serverModule = context.asAbsolutePath(
	// 	path.join('..', 'server', 'server.py')
	// );

	// 获取虚拟环境中的 Python 路径
	// 假设你的目录结构是:
	// PyClangd/
	// ├── venv/
	// ├── server/
	// └── vscode/

	// 这里的路径根据你的实际存放位置调整，重点是找到 venv/bin/python
	const pythonPath = context.asAbsolutePath(path.join('..', 'venv', 'bin', 'python'));
	const serverModule = context.asAbsolutePath(path.join('..', 'server', 'server.py'));

	const serverOptions: ServerOptions = {
		command: pythonPath, // 使用虚拟环境中的 Python 路径
		args: [serverModule],
		options: {
			env: {
				...process.env,
				// 确保 Python 能够找到 server 目录下的 database.py 和 cindex.py
				PYTHONPATH: context.asAbsolutePath(path.join('..'))
			}
		}
	};

	const clientOptions: LanguageClientOptions = {
		documentSelector: [
			{ scheme: 'file', language: 'cpp' },
			{ scheme: 'file', language: 'c' }
		]
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