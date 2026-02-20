import * as path from 'path';
import { ExtensionContext } from 'vscode';
import { LanguageClient, ServerOptions, TransportKind } from 'vscode-languageclient/node';

let client: LanguageClient;

export function activate(context: ExtensionContext) {
	// 指向 server/server.py
	const serverModule = context.asAbsolutePath(path.join('server', 'server.py'));

	const serverOptions: ServerOptions = {
		command: "python3",
		args: [serverModule],
		transport: TransportKind.stdio
	};

	const clientOptions = {
		documentSelector: [
			{ scheme: 'file', language: 'cpp' },
			{ scheme: 'file', language: 'c' }
		]
	};

	client = new LanguageClient('PyClangd', 'PyClangd Language Server', serverOptions, clientOptions);
	client.start();
}

export function deactivate() {
	if (!client) return undefined;
	return client.stop();
}