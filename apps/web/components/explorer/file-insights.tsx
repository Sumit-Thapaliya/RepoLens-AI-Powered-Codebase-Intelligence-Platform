"use client";

import * as React from "react";
import { ArrowDownLeft, ArrowUpRight, Braces, CornerRightDown, FunctionSquare, ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { FilePayload, SymbolInfo } from "@/lib/types";
import { cn } from "@/lib/utils";

export function FileInsights({
  file,
  onJump,
  onOpenFile,
  onImpact,
}: {
  file: FilePayload;
  onJump: (symbol: SymbolInfo) => void;
  onOpenFile: (path: string, line?: number | null) => void;
  onImpact: (path: string, symbol?: string | null) => void;
}) {
  const [tab, setTab] = React.useState("symbols");

  return (
    <div className="panel flex h-full min-h-0 flex-col overflow-hidden">
      <div className="panel-header">
        <span className="panel-title">File intelligence</span>
        <Button size="xs" variant="outline" onClick={() => onImpact(file.path)}>
          <ShieldAlert className="size-3" /> Impact
        </Button>
      </div>

      <Tabs value={tab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
        <div className="px-3 pt-3">
          <TabsList className="w-full">
            <TabsTrigger value="symbols" className="flex-1">
              Symbols ({file.symbols.length})
            </TabsTrigger>
            <TabsTrigger value="imports" className="flex-1">
              Imports ({file.imports.length})
            </TabsTrigger>
            <TabsTrigger value="used" className="flex-1">
              Used by ({file.dependents.length})
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-3 scrollbar-thin">
          <TabsContent value="symbols" className="mt-0 space-y-1.5">
            {file.symbols.length === 0 ? (
              <p className="py-6 text-center text-2xs text-muted-foreground">
                No symbols extracted — this file may be data, config or unsupported syntax.
              </p>
            ) : (
              file.symbols.map((symbol) => (
                <div key={symbol.id} className="rounded-lg border border-border bg-surface-muted/30 p-2.5">
                  <button type="button" className="w-full text-left" onClick={() => onJump(symbol)}>
                    <div className="flex items-center gap-2">
                      {symbol.kind === "class" ? (
                        <Braces className="size-3.5 shrink-0 text-violet-300" />
                      ) : (
                        <FunctionSquare className="size-3.5 shrink-0 text-sky-300" />
                      )}
                      <span className="mono truncate text-xs">{symbol.name}</span>
                      <Badge variant="outline" className="ml-auto shrink-0 font-normal">
                        L{symbol.start_line}
                      </Badge>
                    </div>
                    {symbol.signature ? (
                      <p className="mono mt-1 truncate text-2xs text-muted-foreground" title={symbol.signature}>
                        {symbol.signature}
                      </p>
                    ) : null}
                  </button>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-2xs text-muted-foreground">
                    <span>{symbol.loc} loc</span>
                    <span>·</span>
                    <span>complexity {symbol.complexity}</span>
                    {symbol.is_async ? <Badge variant="outline">async</Badge> : null}
                    {symbol.exported ? <Badge variant="outline">exported</Badge> : null}
                    {symbol.complexity >= 15 ? <Badge variant="warning">high complexity</Badge> : null}
                    <button
                      type="button"
                      className="ml-auto text-primary hover:underline"
                      onClick={() => onImpact(file.path, symbol.name)}
                    >
                      impact
                    </button>
                  </div>
                  {symbol.calls.length ? (
                    <p className="mt-1 truncate text-2xs text-muted-foreground/80" title={symbol.calls.map((call) => call.full).join(", ")}>
                      calls: {symbol.calls.slice(0, 6).map((call) => call.name).join(", ")}
                      {symbol.calls.length > 6 ? ` +${symbol.calls.length - 6}` : ""}
                    </p>
                  ) : null}
                </div>
              ))
            )}
          </TabsContent>

          <TabsContent value="imports" className="mt-0 space-y-1.5">
            {file.imports.length === 0 ? (
              <p className="py-6 text-center text-2xs text-muted-foreground">This file imports nothing that could be resolved.</p>
            ) : (
              file.imports.map((import_) => (
                <button
                  key={`${import_.path}-${import_.line}`}
                  type="button"
                  onClick={() => onOpenFile(import_.path, import_.line)}
                  className="flex w-full items-start gap-2 rounded-md border border-border/70 px-2.5 py-1.5 text-left transition-colors hover:border-primary/40"
                >
                  <ArrowUpRight className="mt-0.5 size-3 shrink-0 text-emerald-300/80" />
                  <span className="min-w-0">
                    <span className="mono block truncate text-2xs">{import_.path}</span>
                    <span className="text-2xs text-muted-foreground">
                      {import_.kind}
                      {import_.symbols.length ? ` · ${import_.symbols.slice(0, 4).join(", ")}` : ""}
                      {import_.line ? ` · line ${import_.line}` : ""}
                    </span>
                  </span>
                </button>
              ))
            )}
          </TabsContent>

          <TabsContent value="used" className="mt-0 space-y-1.5">
            {file.dependents.length === 0 ? (
              <p className="py-6 text-center text-2xs text-muted-foreground">
                Nothing in the analysed source imports this file. It may be an entry point, a config or dead code.
              </p>
            ) : (
              file.dependents.map((dependent) => (
                <button
                  key={`${dependent.path}-${dependent.line}`}
                  type="button"
                  onClick={() => onOpenFile(dependent.path, dependent.line)}
                  className="flex w-full items-start gap-2 rounded-md border border-border/70 px-2.5 py-1.5 text-left transition-colors hover:border-primary/40"
                >
                  <ArrowDownLeft className="mt-0.5 size-3 shrink-0 text-sky-300/80" />
                  <span className="min-w-0">
                    <span className="mono block truncate text-2xs">{dependent.path}</span>
                    <span className="text-2xs text-muted-foreground">
                      {dependent.kind}
                      {dependent.symbols.length ? ` · ${dependent.symbols.slice(0, 4).join(", ")}` : ""}
                      {dependent.line ? ` · line ${dependent.line}` : ""}
                    </span>
                  </span>
                </button>
              ))
            )}
          </TabsContent>
        </div>
      </Tabs>

      <div className={cn("border-t border-border px-3 py-2", "text-2xs text-muted-foreground")}>
        <span className="flex items-center gap-1.5">
          <CornerRightDown className="size-3" />
          {file.artifact_note ?? "Symbols, imports and reverse dependencies come from the stored parse result of this run."}
        </span>
      </div>
    </div>
  );
}
