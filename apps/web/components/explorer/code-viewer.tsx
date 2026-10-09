"use client";

import * as React from "react";
import Editor, { type OnMount } from "@monaco-editor/react";
import { AlertTriangle, Loader2 } from "lucide-react";
import { monaco, setupMonaco } from "@/components/code/monaco-setup";
import { monacoLanguage } from "@/lib/utils";
import type { FilePayload } from "@/lib/types";

setupMonaco();

export function CodeViewer({
  file,
  targetLine,
  focusSymbol,
}: {
  file: FilePayload | null;
  targetLine?: number | null;
  focusSymbol?: { start: number; end: number } | null;
}) {
  const [ready, setReady] = React.useState(false);
  const decorationsRef = React.useRef<string[]>([]);
  type MonacoEditor = ReturnType<typeof monaco.editor.create>;

const editorRef = React.useRef<MonacoEditor | null>(null);

  const handleMount: OnMount = (editor) => {
    editorRef.current = editor;
    setReady(true);
  };

  React.useEffect(() => {
    const editor = editorRef.current;
    if (!editor || !file) return;
    const model = editor.getModel();
    if (!model) return;

    const lastLine = model.getLineCount();
    const startLine = Math.min(Math.max((focusSymbol?.start ?? targetLine ?? 0) || 1, 1), lastLine);
    const endLine = Math.min(Math.max(focusSymbol?.end ?? targetLine ?? startLine, startLine), lastLine);

    const range = {
      startLineNumber: startLine,
      startColumn: 1,
      endLineNumber: endLine,
      endColumn: model.getLineMaxColumn(endLine),
    };

    editor.revealLineInCenter(startLine);
    editor.setSelection(range);
    decorationsRef.current = editor.deltaDecorations(decorationsRef.current, [
      {
        range,
        options: {
          isWholeLine: true,
          className: "bg-primary/10",
          linesDecorationsClassName: "border-l-2 border-primary",
        },
      },
    ]);
  }, [file, targetLine, focusSymbol]);

  if (!file) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" /> Loading file…
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2">
        <div className="min-w-0">
          <p className="mono truncate text-xs">{file.path}</p>
          <p className="text-2xs text-muted-foreground">
            {monacoLanguage(file.language)} · {file.loc} lines · {(file.size_bytes / 1024).toFixed(1)} KB · layer: {file.layer}
            {file.parsed ? " · parsed" : " · not parsed"}
          </p>
        </div>
        {file.truncated ? (
          <span className="flex shrink-0 items-center gap-1 text-2xs text-amber-300">
            <AlertTriangle className="size-3" /> truncated for display
          </span>
        ) : null}
      </div>

      {file.parse_error ? (
        <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/5 px-4 py-2 text-2xs text-amber-200">
          <AlertTriangle className="size-3 shrink-0" />
          {file.parse_error}
        </div>
      ) : null}

      <div className="relative min-h-0 flex-1">
        <Editor
          height="100%"
          theme="repolens-dark"
          language={monacoLanguage(file.language)}
          value={file.content}
          onMount={handleMount}
          loading={
            <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" /> Loading editor…
            </div>
          }
          options={{
            readOnly: true,
            domReadOnly: true,
            minimap: { enabled: true, renderCharacters: false, maxColumn: 80 },
            fontFamily: "var(--font-mono)",
            fontSize: 12.5,
            lineHeight: 19,
            scrollBeyondLastLine: false,
            renderLineHighlight: "line",
            smoothScrolling: true,
            scrollbar: { verticalScrollbarSize: 10, horizontalScrollbarSize: 10, useShadows: false },
            padding: { top: 10, bottom: 16 },
            stickyScroll: { enabled: false },
            bracketPairColorization: { enabled: true },
            guides: { indentation: true },
            contextmenu: false,
            wordWrap: "off",
          }}
        />
        {!ready ? null : null}
      </div>

      {file.warnings?.length ? (
        <div className="border-t border-border px-4 py-1.5 text-2xs text-muted-foreground">
          {file.warnings.join(" · ")}
        </div>
      ) : null}
    </div>
  );
}
