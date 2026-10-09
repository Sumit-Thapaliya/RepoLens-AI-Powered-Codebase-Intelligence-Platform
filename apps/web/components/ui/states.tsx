"use client";

import * as React from "react";
import { AlertTriangle, Ban, CheckCircle2, Info, Loader2, RefreshCw, SearchX, XCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api";

/* ------------------------------------------------------------------- states */

export function LoadingState({ label = "Loading", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-14 text-sm text-muted-foreground", className)}>
      <Loader2 className="size-4 animate-spin" />
      {label}…
    </div>
  );
}

export function EmptyState({
  icon: Icon = SearchX,
  title,
  detail,
  action,
  className,
}: {
  icon?: React.ComponentType<{ className?: string }>;
  title: string;
  detail?: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center gap-2 px-6 py-14 text-center", className)}>
      <div className="rounded-full border border-border bg-surface-muted p-3">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium">{title}</p>
      {detail ? <p className="max-w-md text-xs leading-relaxed text-muted-foreground">{detail}</p> : null}
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "Something went wrong",
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const message = error instanceof Error ? error.message : String(error ?? "Unknown error");
  return (
    <div className={cn("m-5 rounded-lg border border-destructive/30 bg-destructive/5 p-4", className)}>
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-destructive" />
        <div className="min-w-0 flex-1 space-y-1.5">
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="break-words text-xs leading-relaxed text-muted-foreground">{message}</p>
          {apiError?.hint ? <p className="text-xs text-muted-foreground/90">{apiError.hint}</p> : null}
          {apiError?.code ? (
            <p className="mono text-2xs uppercase tracking-wider text-muted-foreground/70">code: {apiError.code}</p>
          ) : null}
          {onRetry ? (
            <Button variant="outline" size="xs" className="mt-1" onClick={onRetry}>
              <RefreshCw /> Retry
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("relative overflow-hidden rounded-md bg-surface-muted/80", className)} />;
}

export function SkeletonCard({ lines = 3, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("panel p-5", className)}>
      <Skeleton className="h-3.5 w-28" />
      <div className="mt-4 space-y-2.5">
        {Array.from({ length: lines }).map((_, index) => (
          <Skeleton key={index} className={cn("h-2.5", index % 3 === 0 ? "w-full" : index % 3 === 1 ? "w-4/5" : "w-2/3")} />
        ))}
      </div>
    </div>
  );
}

export function StatusPill({ status, className }: { status: string; className?: string }) {
  const config: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; className: string }> = {
    queued: { label: "Queued", icon: Loader2, className: "border-slate-500/30 bg-slate-500/10 text-slate-300" },
    running: { label: "Running", icon: Loader2, className: "border-sky-500/30 bg-sky-500/10 text-sky-300" },
    complete: { label: "Complete", icon: CheckCircle2, className: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" },
    failed: { label: "Failed", icon: XCircle, className: "border-rose-500/30 bg-rose-500/10 text-rose-300" },
    cancelled: { label: "Cancelled", icon: Ban, className: "border-amber-500/30 bg-amber-500/10 text-amber-300" },
  };
  const entry = config[status] ?? { label: status, icon: Info, className: "border-border bg-secondary text-muted-foreground" };
  const Icon = entry.icon;
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-2xs font-medium", entry.className, className)}>
      <Icon className={cn("size-3", (status === "running" || status === "queued") && "animate-spin")} />
      {entry.label}
    </span>
  );
}

/* -------------------------------------------------------------------- toast */

type Toast = { id: string; title: string; detail?: string; tone: "info" | "success" | "error" };

const ToastContext = React.createContext<{ push: (toast: Omit<Toast, "id">) => void }>({ push: () => {} });

export function useToast() {
  return React.useContext(ToastContext);
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);

  const push = React.useCallback((toast: Omit<Toast, "id">) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((current) => [...current, { ...toast, id }]);
    setTimeout(() => setToasts((current) => current.filter((entry) => entry.id !== id)), 6000);
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-5 right-5 z-[100] flex w-80 flex-col gap-2">
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "animate-in-fade pointer-events-auto flex items-start gap-2.5 rounded-lg border bg-popover/95 p-3 shadow-lg backdrop-blur",
              toast.tone === "error" ? "border-destructive/40" : toast.tone === "success" ? "border-emerald-500/40" : "border-border",
            )}
          >
            {toast.tone === "error" ? (
              <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />
            ) : toast.tone === "success" ? (
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-400" />
            ) : (
              <Info className="mt-0.5 size-4 shrink-0 text-primary" />
            )}
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium">{toast.title}</p>
              {toast.detail ? <p className="mt-0.5 break-words text-2xs leading-relaxed text-muted-foreground">{toast.detail}</p> : null}
            </div>
            <button
              type="button"
              className="text-muted-foreground transition-colors hover:text-foreground"
              onClick={() => setToasts((current) => current.filter((entry) => entry.id !== toast.id))}
            >
              <X className="size-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/* ------------------------------------------------------------------- misc */

export function InlineNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <p className={cn("rounded-md border border-border bg-surface-muted/50 px-3 py-2 text-2xs leading-relaxed text-muted-foreground", className)}>
      {children}
    </p>
  );
}

export function SectionHeading({
  title,
  detail,
  right,
  className,
}: {
  title: string;
  detail?: string;
  right?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-end justify-between gap-4", className)}>
      <div>
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {detail ? <p className="mt-0.5 text-xs text-muted-foreground">{detail}</p> : null}
      </div>
      {right}
    </div>
  );
}
