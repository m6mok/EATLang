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

const { workspace, window, Uri } = require("vscode");
const fs = require("fs");
const path = require("path");

let LanguageClient;
try {
    ({ LanguageClient } = require("vscode-languageclient/node"));
} catch (e) {
    LanguageClient = null;
}

let client;

// Корень воркспейса (репозиторий EATLang): пути import — от него.
function repoRoot() {
    return workspace.workspaceFolders && workspace.workspaceFolders.length > 0
        ? workspace.workspaceFolders[0].uri.fsPath
        : process.cwd();
}

// Транзитивное замыкание импортов в ТОПОЛОГИЧЕСКОМ порядке
// (docs/plans/LSP_PLAN.md, этапы 1b/1c): сервер на EATLang не читает файлы,
// поэтому клиент (у Node есть FS) собирает зависимости открытого файла и
// шлёт их серверу. Пост-порядок DFS по `from "canon"` (канонический путь от
// корня, dedupe) даёт зависимости «раньше зависимых» — как требует поток
// #module. startText — текст открытого файла (в памяти, учитывает
// несохранённые правки import-строк); зависимости берутся с диска.
function moduleOrder(rootDir, startText) {
    const seen = new Set();
    const out = [];
    const IMPORT = /from\s+"([^"]+)"/g;
    const visit = function (text, depth) {
        if (depth > 64) {
            return;
        }
        let m;
        const re = new RegExp(IMPORT.source, "g");
        while ((m = re.exec(text)) !== null) {
            const canon = m[1];
            if (seen.has(canon)) {
                continue;
            }
            seen.add(canon);
            let dtext;
            try {
                dtext = fs.readFileSync(path.join(rootDir, canon), "utf8");
            } catch (e) {
                continue;
            }
            visit(dtext, depth + 1);
            out.push({ canon: canon, text: dtext });
        }
    };
    visit(startText, 0);
    return out;
}

// Отправить серверу корпус зависимостей (eat/module) и топологический
// порядок потока (eat/order) для документа .eat: order[0] — Rt (модуль 0),
// далее зависимости «раньше зависимых». Сервер пересчитывает диагностику
// модульным анализом и резолвит переходы к определению по корпусу.
function sendClosure(doc) {
    if (!client || !doc || doc.languageId !== "eat") {
        return;
    }
    const rootDir = repoRoot();
    const deps = moduleOrder(rootDir, doc.getText());
    const send = function (canon, text) {
        client
            .sendNotification("eat/module", {
                path: canon,
                uri: Uri.file(path.join(rootDir, canon)).toString(),
                text: text,
            })
            .catch(function () {});
    };
    const rtPath = "selfhost/Rt.eat";
    let rtOk = true;
    try {
        send(rtPath, fs.readFileSync(path.join(rootDir, rtPath), "utf8"));
    } catch (e) {
        rtOk = false;
    }
    for (const d of deps) {
        send(d.canon, d.text);
    }
    const paths = [];
    if (rtOk) {
        paths.push(rtPath);
    }
    for (const d of deps) {
        paths.push(d.canon);
    }
    client
        .sendNotification("eat/order", {
            uri: doc.uri.toString(),
            paths: paths,
        })
        .catch(function () {});
}

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

    // Запуск — через editor/lsp/serve.sh: он линкует фазы плоской
    // склейкой (модуль 0) и пересобирает build/JsonFlat.eat.
    //
    // Берём ТОЛЬКО явно заданное пользователем значение (inspect →
    // global/workspace/folder), игнорируя дефолт из package.json: VS Code
    // кеширует дефолты манифеста агрессивно, и после смены линковки на
    // складку старый дефолт `run --lib . LspMain.eat` пытался бы собрать
    // один файл (→ «неизвестный тип Lsp»). Если пользователь ничего не
    // переопределял — форсим serve.sh.
    const cfg = workspace.getConfiguration("eatlang");
    const pick = (key) => {
        const i = cfg.inspect(key) || {};
        return (
            i.workspaceFolderValue ?? i.workspaceValue ?? i.globalValue
        );
    };
    const command = pick("server.command") || "bash";
    const args = pick("server.args") || ["editor/lsp/serve.sh"];

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

    // После старта — корпус зависимостей для кросс-файлового go-to-def
    // (этап 1b): на открытие/правку .eat считаем замыкание импортов и шлём
    // его серверу (eat/module). Правки дебаунсим (300 мс).
    client.start().then(function () {
        workspace.textDocuments.forEach(sendClosure);
        context.subscriptions.push(
            workspace.onDidOpenTextDocument(sendClosure)
        );
        let timer = null;
        context.subscriptions.push(
            workspace.onDidChangeTextDocument(function (e) {
                if (timer) {
                    clearTimeout(timer);
                }
                timer = setTimeout(function () {
                    sendClosure(e.document);
                }, 300);
            })
        );
    });
}

function deactivate() {
    return client ? client.stop() : undefined;
}

module.exports = { activate, deactivate };
