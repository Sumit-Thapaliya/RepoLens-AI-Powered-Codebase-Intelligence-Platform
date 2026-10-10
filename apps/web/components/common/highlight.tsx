import * as React from "react";

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Renders `text` with every occurrence of the query words wrapped in <mark>.
 * Words shorter than two characters are ignored, so "a" does not highlight everything.
 */
export function Highlight({ text, query }: { text: string; query: string }) {
  const words = Array.from(new Set(query.split(/\s+/).map((word) => word.trim()).filter((word) => word.length >= 2)));
  if (!text || words.length === 0) return <>{text}</>;

  const pattern = new RegExp(`(${words.map(escapeRegExp).join("|")})`, "gi");
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, index) =>
        index % 2 === 1 ? (
          <mark key={index} className="rounded-sm bg-primary/25 px-0.5 text-foreground">
            {part}
          </mark>
        ) : (
          <React.Fragment key={index}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}
