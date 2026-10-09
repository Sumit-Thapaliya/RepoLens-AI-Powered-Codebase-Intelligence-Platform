"use client";

/**
 * Monaco setup for a *read-only* code viewer.
 *
 * Only the editor API plus the monarch grammars the product needs are bundled -
 * the heavy language services (TypeScript/JSON/CSS/HTML workers) are left out on
 * purpose: RepoLens never edits code and never needs type-checking, so shipping
 * ~10 MB of workers would only slow the app down. Syntax highlighting, folding,
 * bracket colourisation and line navigation all work without them.
 */
import * as monaco from "monaco-editor/esm/vs/editor/editor.api";

import "monaco-editor/esm/vs/basic-languages/python/python.contribution";
import "monaco-editor/esm/vs/basic-languages/typescript/typescript.contribution";
import "monaco-editor/esm/vs/basic-languages/javascript/javascript.contribution";
import "monaco-editor/esm/vs/basic-languages/go/go.contribution";
import "monaco-editor/esm/vs/basic-languages/java/java.contribution";
import "monaco-editor/esm/vs/basic-languages/kotlin/kotlin.contribution";
import "monaco-editor/esm/vs/basic-languages/ruby/ruby.contribution";
import "monaco-editor/esm/vs/basic-languages/php/php.contribution";
import "monaco-editor/esm/vs/basic-languages/rust/rust.contribution";
import "monaco-editor/esm/vs/basic-languages/csharp/csharp.contribution";
import "monaco-editor/esm/vs/basic-languages/cpp/cpp.contribution";
import "monaco-editor/esm/vs/basic-languages/sql/sql.contribution";
import "monaco-editor/esm/vs/basic-languages/mysql/mysql.contribution";
import "monaco-editor/esm/vs/basic-languages/pgsql/pgsql.contribution";
import "monaco-editor/esm/vs/basic-languages/yaml/yaml.contribution";
import "monaco-editor/esm/vs/basic-languages/markdown/markdown.contribution";
import "monaco-editor/esm/vs/basic-languages/shell/shell.contribution";
import "monaco-editor/esm/vs/basic-languages/dockerfile/dockerfile.contribution";
import "monaco-editor/esm/vs/basic-languages/html/html.contribution";
import "monaco-editor/esm/vs/basic-languages/css/css.contribution";
import "monaco-editor/esm/vs/basic-languages/xml/xml.contribution";
import "monaco-editor/esm/vs/basic-languages/ini/ini.contribution";
import "monaco-editor/esm/vs/basic-languages/lua/lua.contribution";

import { loader } from "@monaco-editor/react";

let configured = false;

export function setupMonaco() {
  if (configured || typeof window === "undefined") return;
  configured = true;

  // The core worker handles text-model operations. It is created from an inline
  // blob so the viewer keeps a single, tiny bundle: everything RepoLens shows is
  // read-only, so the worker's advanced services are never required.
  self.MonacoEnvironment = {
    getWorker() {
      const source = "self.onmessage = function () {};";
      const blob = new Blob([source], { type: "application/javascript" });
      return new Worker(URL.createObjectURL(blob));
    },
  };

  loader.config({ monaco });

  monaco.editor.defineTheme("repolens-dark", {
    base: "vs-dark",
    inherit: true,
    rules: [
      { token: "comment", foreground: "6b7688", fontStyle: "italic" },
      { token: "keyword", foreground: "c792ea" },
      { token: "string", foreground: "a5d6a7" },
      { token: "number", foreground: "f78c6c" },
      { token: "type", foreground: "82aaff" },
      { token: "function", foreground: "82aaff" },
      { token: "class", foreground: "ffcb6b" },
      { token: "decorator", foreground: "f78c6c" },
      { token: "delimiter", foreground: "8b98ab" },
    ],
    colors: {
      "editor.background": "#0f1319",
      "editor.foreground": "#dbe4f0",
      "editorLineNumber.foreground": "#4a5568",
      "editorLineNumber.activeForeground": "#8fa1bb",
      "editor.lineHighlightBackground": "#151b25",
      "editor.selectionBackground": "#1d3a4d",
      "editorGutter.background": "#0f1319",
      "editorIndentGuide.background1": "#1c232e",
      "editorWidget.background": "#111620",
      "editorWidget.border": "#232a36",
      "scrollbarSlider.background": "#232a3680",
      "minimap.background": "#0d1117",
    },
  });
}

export { monaco };
