"use client";

import * as React from "react";
import { ChevronRight, FileCode2, FileText, Folder, FolderOpen, TestTube2 } from "lucide-react";
import type { FileNode } from "@/lib/types";
import { cn, layerColor } from "@/lib/utils";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

function matches(node: FileNode, needle: string): boolean {
  if (!needle) return true;
  if (node.path.toLowerCase().includes(needle)) return true;
  return (node.children ?? []).some((child) => matches(child, needle));
}

function TreeRow({
  node,
  depth,
  selected,
  onSelect,
  expanded,
  toggle,
  filter,
}: {
  node: FileNode;
  depth: number;
  selected: string | null;
  onSelect: (path: string) => void;
  expanded: Set<string>;
  toggle: (path: string) => void;
  filter: string;
}) {
  if (!matches(node, filter)) return null;
  const isDir = node.type === "dir";
  const isOpen = expanded.has(node.path) || Boolean(filter);
  const isSelected = selected === node.path;

  return (
    <li>
      <button
        type="button"
        onClick={() => (isDir ? toggle(node.path) : onSelect(node.path))}
        className={cn(
          "group flex w-full items-center gap-1.5 rounded px-1.5 py-[3px] text-left transition-colors",
          isSelected ? "bg-primary/10 text-primary" : "hover:bg-secondary/50",
        )}
        style={{ paddingLeft: `${depth * 12 + 6}px` }}
        title={node.path}
      >
        {isDir ? (
          <ChevronRight className={cn("size-3 shrink-0 text-muted-foreground transition-transform", isOpen && "rotate-90")} />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        {isDir ? (
          isOpen ? (
            <FolderOpen className="size-3.5 shrink-0 text-sky-300/80" />
          ) : (
            <Folder className="size-3.5 shrink-0 text-sky-300/70" />
          )
        ) : node.language === "markdown" || node.language === "unknown" ? (
          <FileText className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <FileCode2 className="size-3.5 shrink-0 text-muted-foreground" style={{ color: node.layer ? layerColor(node.layer) : undefined }} />
        )}
        <span className={cn("truncate text-xs", isDir && "font-medium")}>{node.name}</span>
        {node.test ? <TestTube2 className="size-3 shrink-0 text-emerald-400/70" /> : null}
        {!isDir && !node.parsed ? (
          <span className="ml-auto shrink-0 text-[0.625rem] text-amber-300/80" title={node.parse_error ?? "not parsed"}>
            !
          </span>
        ) : null}
        {isDir && node.count ? <span className="ml-auto shrink-0 text-2xs text-muted-foreground">{node.count}</span> : null}
      </button>
      {isDir && isOpen ? (
        <ul>
          {(node.children ?? []).map((child) => (
            <TreeRow
              key={child.path}
              node={child}
              depth={depth + 1}
              selected={selected}
              onSelect={onSelect}
              expanded={expanded}
              toggle={toggle}
              filter={filter}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function FileTree({
  tree,
  selected,
  onSelect,
  truncated,
}: {
  tree: FileNode[];
  selected: string | null;
  onSelect: (path: string) => void;
  truncated?: boolean;
}) {
  const [filter, setFilter] = React.useState("");
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    // expand the first level so the tree is not a single collapsed row
    const initial = new Set<string>();
    tree.slice(0, 6).forEach((node) => node.type === "dir" && initial.add(node.path));
    setExpanded(initial);
  }, [tree]);

  React.useEffect(() => {
    if (!selected) return;
    const parts = selected.split("/");
    const parents: string[] = [];
    parts.slice(0, -1).forEach((_, index) => parents.push(parts.slice(0, index + 1).join("/")));
    setExpanded((current) => new Set([...current, ...parents]));
  }, [selected]);

  const toggle = (path: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border p-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="Filter files…"
            className="h-7 pl-8 text-xs"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-1.5 scrollbar-thin">
        <ul>
          {tree.map((node) => (
            <TreeRow
              key={node.path}
              node={node}
              depth={0}
              selected={selected}
              onSelect={onSelect}
              expanded={expanded}
              toggle={toggle}
              filter={filter.toLowerCase()}
            />
          ))}
        </ul>
        {tree.length === 0 ? <p className="p-4 text-center text-2xs text-muted-foreground">No files in this analysis.</p> : null}
      </div>
      {truncated ? (
        <p className="border-t border-border px-3 py-1.5 text-2xs text-amber-300/80">
          Tree truncated — the repository exceeded the file limit for the tree view.
        </p>
      ) : null}
    </div>
  );
}
