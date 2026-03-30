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

	//vscode.window.showErrorMessage('!!! 插件正在激活 !!!');
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


	const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
	const workspaceRoot = workspaceFolder ? workspaceFolder.uri.fsPath : extPath;

	const serverOptions: ServerOptions = {
		command: pythonPath,
		args: [serverModule, '-d', workspaceRoot, '-s'],
		options: {
			env: {
				...process.env,
				PYTHONPATH: path.join(extPath, 'server'),
			},
		},
	};

	// 3. 使用 appendLine 进行打印
	outputChannel.appendLine("--- PyClangd 插件正在启动 ---");
	outputChannel.appendLine(`插件自动执行:${pythonPath} ${serverModule} -d ${workspaceRoot} -s`);

	const clientOptions: LanguageClientOptions = {
		documentSelector: [
			{ scheme: 'file', language: 'cpp' },
			{ scheme: 'file', language: 'c' },
			// 增加对普通文本或所有文件的支持！
			{ scheme: 'file', language: 'plaintext' },
			{ scheme: 'file', pattern: '**/*' } // 或者直接匹配工作区所有文件
		],
		// 使用你已经创建好的输出通道
		outputChannel: outputChannel,
		// ⭐ 核心配置：开启详细追踪模式
		traceOutputChannel: outputChannel,

		// 👇 添加这个中间件拦截器
		middleware: {
			provideDefinition: async (document, position, token, next) => {
				const result = await next(document, position, token);

				if (!result) {
					return result;
				}

				// 拦截 plaintext 或者是没有后缀的日志文件
				if (document.languageId === 'plaintext' || document.fileName.indexOf('.') === -1) {

					const locations = Array.isArray(result) ? result : [result];

					if (locations.length > 0) {
						const targetLoc = locations[0];

						// 类型收窄 (Type Guard)
						const targetUri = 'uri' in targetLoc ? targetLoc.uri : targetLoc.targetUri;
						const targetRange = 'range' in targetLoc ? targetLoc.range : (targetLoc.targetSelectionRange || targetLoc.targetRange);

						if (!targetUri) {
							return []; // 防御性编程，并加上大括号满足 ESLint
						}

						// 强行在最左侧 (ViewColumn.One) 打开
						const targetDoc = await vscode.workspace.openTextDocument(targetUri);

						await vscode.window.showTextDocument(targetDoc, {
							viewColumn: vscode.ViewColumn.One,
							selection: targetRange,
							preserveFocus: true
						});

						// 2. 🌟 核心修复：欺骗 VS Code 前端！
						// 不要返回 []，而是返回一个指向当前鼠标位置的 dummy 坐标。
						// 这样 VS Code 原生的 F12 会认为目标就在原地，右侧窗口就会死死钉在原地，绝对不会乱跳！
						const dummyLocation = new vscode.Location(document.uri, position);
						return [dummyLocation];
					}
				}

				// 普通 C/C++ 文件正常放行
				return result;
			}
		}

	};

	// =========================================================
	// 模块 2：注册命令 - 解析 Ftrace 生成搜索范围
	// =========================================================
	let generateScopeCmd = vscode.commands.registerTextEditorCommand('pyclangd.triggerGenerateScope', async (editor) => {
		const uri = editor.document.uri;
		vscode.window.showInformationMessage("🔍 正在解析 Ftrace 日志并映射源文件...");

		// 发送给 Python 后台
		const result: any = await client.sendRequest('workspace/executeCommand', {
			command: 'pyclangd.generate_scope',
			arguments: [{ file_path: uri.fsPath }]
		});

		if (result && result.error) {
			vscode.window.showErrorMessage(`❌ 解析失败: ${result.error}`);
		} else if (result && result.status === "success") {
			vscode.window.showInformationMessage("🎉 Ftrace 范围文件生成成功！");
		}
	});

	// =========================================================
	// 模块 3：注册命令 - 在 Ftrace 范围内搜索引用 (Peek View)
	// =========================================================
	let scopedSearchCmd = vscode.commands.registerTextEditorCommand('pyclangd.triggerScopedSearch', async (editor) => {
		const position = editor.selection.active;
		const uri = editor.document.uri;

		// 发送坐标给 Python 后台 (注意：行号列号 +1 对齐 Python 逻辑)
		const result: any = await client.sendRequest('workspace/executeCommand', {
			command: 'pyclangd.scoped_search',
			arguments: [{
				file_path: uri.fsPath,
				line: position.line + 1,
				col: position.character + 1
			}]
		});

		if (result && result.error) {
			vscode.window.showErrorMessage(result.error);
			return;
		}

		if (result && result.status === "success" && Array.isArray(result.data)) {
			const data = result.data;
			if (data.length === 0) {
				vscode.window.showInformationMessage("在 Ftrace 作用域内，没有找到该符号的引用。");
				return;
			}

			// 把 Python 返回的元组转换为 VS Code 原生的 Location 对象 (行号列号 -1 还原)
			const locations = data.map((r: any[]) => {
				const targetUri = vscode.Uri.file(r[0]);
				const range = new vscode.Range(
					new vscode.Position(r[1] - 1, r[2] - 1),
					new vscode.Position(r[3] - 1, r[4] - 1)
				);
				return new vscode.Location(targetUri, range);
			});

			// 呼出 VS Code 原生的“查看引用”悬浮小窗
			vscode.commands.executeCommand('editor.action.showReferences', uri, position, locations);
		}
	});

	// 把这两个命令注册进插件生命周期
	context.subscriptions.push(generateScopeCmd);
	context.subscriptions.push(scopedSearchCmd);

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
