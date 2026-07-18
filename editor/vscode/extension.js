// editor/vscode/extension.js — клиент LSP для EATLang
// (docs/plans/LSP_PLAN.md, этап 0). Запускает сервер на самом EATLang
// (editor/lsp/LspMain.eat) и общается с ним по JSON-RPC поверх stdio.
//
// Подсветка (grammars/languages в package.json) декларативна и работает
// независимо от этой активации — если сервер не поднялся (нет uv или
// node_modules), редактор всё равно красит синтаксис.
//
// Чистый JavaScript: TS-сборка не нужна, требуется лишь
// `npm install` (тянет vscode-languageclient) — см. README.

const { workspace, window } = require("vscode");

let LanguageClient;
try {
    ({ LanguageClient } = require("vscode-languageclient/node"));
} catch (e) {
    LanguageClient = null;
}

let client;

function activate(context) {
    if (!LanguageClient) {
        window.showWarningMessage(
            "EATLang: vscode-languageclient не установлен — выполните " +
                "npm install в editor/vscode. Подсветка работает без сервера."
        );
        return;
    }

    const folder =
        workspace.workspaceFolders && workspace.workspaceFolders.length > 0
            ? workspace.workspaceFolders[0].uri.fsPath
            : process.cwd();

    const cfg = workspace.getConfiguration("eatlang");
    const command = cfg.get("server.command", "uv");
    const args = cfg.get("server.args", [
        "run",
        "python",
        "-m",
        "eatc",
        "run",
        "--lib",
        ".",
        "editor/lsp/LspMain.eat",
    ]);

    // cwd = корень воркспейса: сервер грузит editor/lsp/ и lib/ путями
    // относительно него. Предполагается, что воркспейс — репозиторий
    // EATLang (этап 0; упаковка автономного сервера — поздний этап).
    const options = {
        cwd: folder,
        env: Object.assign({}, process.env, { PYTHONPATH: "src" }),
    };
    const executable = { command, args, options };

    const serverOptions = { run: executable, debug: executable };
    const clientOptions = {
        documentSelector: [{ scheme: "file", language: "eat" }],
        synchronize: {
            fileEvents: workspace.createFileSystemWatcher("**/*.eat"),
        },
    };

    client = new LanguageClient(
        "eatLsp",
        "EATLang LSP",
        serverOptions,
        clientOptions
    );
    client.start();
}

function deactivate() {
    return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
