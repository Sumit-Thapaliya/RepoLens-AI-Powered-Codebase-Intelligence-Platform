"use client";

import * as React from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import {
  Blocks,
  Boxes,
  Database,
  FileCode2,
  Gauge,
  GitBranch,
  LayoutDashboard,
  Route,
  Settings2,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAnalysisContext } from "@/components/providers/analysis-provider";
import { useNavigation } from "@/components/providers/navigation-provider";

const NAV = [
  { section: "Repository", items: [
    { href: "/", label: "Overview", icon: LayoutDashboard },
    { href: "/architecture", label: "Architecture", icon: Boxes },
    { href: "/workflows", label: "Workflows", icon: GitBranch },
    { href: "/dependencies", label: "Dependencies", icon: Blocks },
  ]},
  { section: "Backend surface", items: [
    { href: "/apis", label: "APIs", icon: Route },
    { href: "/database", label: "Database", icon: Database },
  ]},
  { section: "Investigate", items: [
    { href: "/explorer", label: "Code Explorer", icon: FileCode2 },
    { href: "/search", label: "Search", icon: Sparkles },
    { href: "/quality", label: "Quality", icon: Gauge },
    { href: "/impact", label: "Impact Analysis", icon: ShieldAlert },
  ]},
];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { analysis, repo, complete } = useAnalysisContext();
  const { pendingHref, startNavigation } = useNavigation();
  const currentHref = pendingHref ?? pathname;

  // Compile/fetch every sidebar page ahead of time so the first click is quick.
  React.useEffect(() => {
    for (const group of NAV) for (const item of group.items) router.prefetch(item.href);
    router.prefetch("/docs");
  }, [router]);

  return (
    <aside className="sticky top-0 hidden h-svh w-60 shrink-0 flex-col border-r border-border bg-surface/60 backdrop-blur-sm lg:flex">
      <Link href="/" className="flex items-center gap-2.5 px-5 py-4">
        <Image
          src="/repolens-logo.jpg"
          alt=""
          width={40}
          height={40}
          priority
          className="size-10 shrink-0 rounded-xl border border-primary/30 object-cover shadow-[0_0_16px_rgba(34,211,238,0.16)]"
        />
        <span className="flex flex-col leading-none">
          <span className="text-sm font-semibold tracking-tight">RepoLens</span>
          <span className="text-2xs text-muted-foreground">codebase intelligence</span>
        </span>
      </Link>

      <div className="mx-4 mb-3 rounded-lg border border-border bg-surface-muted/60 px-3 py-2.5">
        <p className="text-2xs uppercase tracking-wider text-muted-foreground">Active repository</p>
        {repo ? (
          <>
            <p className="mt-1 truncate text-xs font-medium" title={repo.full_name}>
              {repo.full_name}
            </p>
            <p className="mono mt-0.5 truncate text-2xs text-muted-foreground">
              {analysis?.branch || repo.default_branch}
              {analysis?.commit_sha ? ` @ ${analysis.commit_sha.slice(0, 7)}` : ""}
            </p>
          </>
        ) : (
          <p className="mt-1 text-xs text-muted-foreground">No analysis yet</p>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto px-3 pb-4 scrollbar-thin">
        {NAV.map((group) => (
          <div key={group.section} className="mb-4">
            <p className="px-2 pb-1.5 text-2xs font-medium uppercase tracking-wider text-muted-foreground/70">
              {group.section}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = currentHref === item.href;
                const disabled = !complete && item.href !== "/";
                const Icon = item.icon;
                return (
                  <li key={item.href}>
                    <Link
                      href={disabled ? "#" : item.href}
                      aria-disabled={disabled}
                      aria-current={active ? "page" : undefined}
                      onClick={(event) => {
                        if (disabled) {
                          event.preventDefault();
                          return;
                        }
                        startNavigation(item.href);
                      }}
                      className={cn(
                        "group flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[0.8125rem] transition-colors",
                        active
                          ? "bg-primary/10 text-primary shadow-[inset_0_0_0_1px_hsl(var(--primary)/0.25)]"
                          : disabled
                            ? "cursor-not-allowed text-muted-foreground/40"
                            : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                      )}
                    >
                      <Icon className="size-4 shrink-0" />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>

      <div className="border-t border-border px-4 py-3">
        <Link
          href="/docs"
          className={cn(
            "flex items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
            currentHref === "/docs" ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
          onClick={() => startNavigation("/docs")}
        >
          <Settings2 className="size-3.5" /> Generated docs & export
        </Link>
        <p className="mono mt-2 truncate text-2xs text-muted-foreground/60" title={analysis?.id}>
          {analysis ? `run ${analysis.id}` : "idle"}
        </p>
      </div>
    </aside>
  );
}
