"use client";

import * as React from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * Small, dependency-free Markdown renderer for the subset RepoLens emits
 * (headings, lists, fenced code, tables, blockquotes, inline emphasis and links).
 * Everything is rendered as React nodes - no HTML injection.
 */

type Inline = React.ReactNode;

function renderInline(text: string, keyPrefix = ""): Inline[] {
  const nodes: Inline[] = [];
  // order matters: code, bold, italic, links
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let index = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) nodes.push(text.slice(lastIndex, match.index));
    const token = match[0];
    const key = `${keyPrefix}-i${index++}`;
    if (token.startsWith("`")) {
      nodes.push(
        <code key={key} className="mono rounded bg-surface-muted px-1.5 py-0.5 text-[0.78rem] text-primary">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**")) {
      nodes.push(
        <strong key={key} className="font-semibold text-foreground">
          {renderInline(token.slice(2, -2), key)}
        </strong>,
      );
    } else if (token.startsWith("*")) {
      nodes.push(
        <em key={key} className="italic">
          {renderInline(token.slice(1, -1), key)}
        </em>,
      );
    } else {
      const label = token.slice(1, token.indexOf("]"));
      const href = token.slice(token.indexOf("(") + 1, -1);
      const internal = href.startsWith("/");
      nodes.push(
        internal ? (
          <Link key={key} href={href} className="text-primary underline underline-offset-2">
            {label}
          </Link>
        ) : (
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-primary underline underline-offset-2"
          >
            {label}
          </a>
        ),
      );
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) nodes.push(text.slice(lastIndex));
  return nodes;
}

export function Markdown({ content, className }: { content: string; className?: string }) {
  const blocks = React.useMemo(() => parse(content || ""), [content]);

  return (
    <div className={cn("markdown-body", className)}>
      {blocks.map((block, index) => (
        <React.Fragment key={index}>{renderBlock(block, index)}</React.Fragment>
      ))}
    </div>
  );
}

function renderBlock(block: Block, index: number): React.ReactNode {
  if (block.type === "heading") {
    const text = renderInline(block.text, `h${index}`);
    if (block.level <= 1) return <h1>{text}</h1>;
    if (block.level === 2) return <h2>{text}</h2>;
    return <h3>{text}</h3>;
  }

  if (block.type === "code") {
    return (
      <pre className="mono">
        <code>{block.text}</code>
      </pre>
    );
  }

  if (block.type === "list") {
    const items = block.items.map((item, itemIndex) => (
      <li key={itemIndex}>{renderInline(item, `l${index}-${itemIndex}`)}</li>
    ));
    return block.ordered ? <ol>{items}</ol> : <ul>{items}</ul>;
  }

  if (block.type === "quote") {
    return <blockquote>{renderInline(block.text, `q${index}`)}</blockquote>;
  }

  if (block.type === "table") {
    return (
      <div className="mb-4 overflow-x-auto">
        <table>
          <thead>
            <tr>
              {block.header.map((cell, cellIndex) => (
                <th key={cellIndex}>{renderInline(cell, `th${index}-${cellIndex}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {row.map((cell, cellIndex) => (
                  <td key={cellIndex}>{renderInline(cell, `td${index}-${rowIndex}-${cellIndex}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (block.type === "hr") {
    return <hr className="my-5 border-border" />;
  }

  return <p>{renderInline(block.text, `p${index}`)}</p>;
}

type Block =
  | { type: "heading"; level: number; text: string }
  | { type: "paragraph"; text: string }
  | { type: "code"; text: string; language?: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "quote"; text: string }
  | { type: "table"; header: string[]; rows: string[][] }
  | { type: "hr" };

function parse(markdown: string): Block[] {
  const lines = markdown.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let index = 0;

  const flushParagraph = (buffer: string[]) => {
    if (buffer.length) {
      blocks.push({ type: "paragraph", text: buffer.join(" ").trim() });
      buffer.length = 0;
    }
  };

  const paragraph: string[] = [];

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      flushParagraph(paragraph);
      index += 1;
      continue;
    }

    if (line.startsWith("```")) {
      flushParagraph(paragraph);
      const language = line.slice(3).trim() || undefined;
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1;
      blocks.push({ type: "code", text: code.join("\n"), language });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line);
    if (heading) {
      flushParagraph(paragraph);
      blocks.push({ type: "heading", level: heading[1].length, text: heading[2].trim() });
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line.trim())) {
      flushParagraph(paragraph);
      blocks.push({ type: "hr" });
      index += 1;
      continue;
    }

    if (line.trimStart().startsWith(">")) {
      flushParagraph(paragraph);
      const quote: string[] = [];
      while (index < lines.length && lines[index].trimStart().startsWith(">")) {
        quote.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      blocks.push({ type: "quote", text: quote.join(" ") });
      continue;
    }

    if (/^\s*\|.+\|\s*$/.test(line)) {
      flushParagraph(paragraph);
      const tableLines: string[] = [];
      while (index < lines.length && /^\s*\|.+\|\s*$/.test(lines[index])) {
        tableLines.push(lines[index]);
        index += 1;
      }
      const split = (row: string) =>
        row.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim());
      const header = split(tableLines[0]);
      const rows = tableLines.slice(2).map(split);
      blocks.push({ type: "table", header, rows });
      continue;
    }

    const bullet = /^\s*([-*+])\s+(.*)$/.exec(line);
    const ordered = /^\s*(\d+)[.)]\s+(.*)$/.exec(line);
    if (bullet || ordered) {
      flushParagraph(paragraph);
      const isOrdered = Boolean(ordered);
      const items: string[] = [];
      while (index < lines.length) {
        const current = lines[index];
        const bulletMatch = /^\s*([-*+])\s+(.*)$/.exec(current);
        const orderedMatch = /^\s*(\d+)[.)]\s+(.*)$/.exec(current);
        if (isOrdered ? orderedMatch : bulletMatch) {
          items.push((isOrdered ? orderedMatch![2] : bulletMatch![2]).trim());
          index += 1;
          // continuation lines (indented)
          while (index < lines.length && /^\s{2,}\S/.test(lines[index]) && !/^\s*([-*+]|\d+[.)])\s+/.test(lines[index])) {
            items[items.length - 1] += " " + lines[index].trim();
            index += 1;
          }
        } else {
          break;
        }
      }
      blocks.push({ type: "list", ordered: isOrdered, items });
      continue;
    }

    paragraph.push(line.trim());
    index += 1;
  }

  flushParagraph(paragraph);
  return blocks;
}
