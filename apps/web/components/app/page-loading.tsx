import { Loader2 } from "lucide-react";
import { Skeleton, SkeletonCard } from "@/components/ui/states";

/** Placeholder for the page area while a page is loading. The sidebar and top bar stay on screen. */
export function PageLoading() {
  return (
    <div className="space-y-5 p-4 lg:p-6" role="status" aria-live="polite" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-5 w-56" />
        <Skeleton className="h-3 w-96 max-w-full" />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <SkeletonCard key={index} lines={2} />
        ))}
      </div>

      <SkeletonCard lines={10} />

      <p className="flex items-center gap-2 text-2xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" /> Loading page…
      </p>
    </div>
  );
}
