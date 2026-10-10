"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { PageLoading } from "@/components/app/page-loading";

/**
 * Makes sidebar navigation feel instant. On click, the target is recorded here at once:
 * the sidebar highlights it and the page area shows a loading view. The real page
 * replaces the loading view when the route has loaded (when the pathname changes).
 */

/* If a route never loads, give up after this long and show the old page again. */
const NAVIGATION_TIMEOUT_MS = 15000;

interface NavigationContextValue {
  pendingHref: string | null;
  startNavigation: (href: string) => void;
}

const NavigationContext = React.createContext<NavigationContextValue>({
  pendingHref: null,
  startNavigation: () => {},
});

export function NavigationProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [pendingHref, setPendingHref] = React.useState<string | null>(null);

  // The target page is now on screen.
  React.useEffect(() => {
    setPendingHref(null);
  }, [pathname]);

  React.useEffect(() => {
    if (!pendingHref) return;
    const timer = setTimeout(() => setPendingHref(null), NAVIGATION_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [pendingHref]);

  const startNavigation = React.useCallback(
    (href: string) => {
      if (href !== pathname) setPendingHref(href);
    },
    [pathname],
  );

  const value = React.useMemo(() => ({ pendingHref, startNavigation }), [pendingHref, startNavigation]);
  return <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>;
}

export function useNavigation(): NavigationContextValue {
  return React.useContext(NavigationContext);
}

/** Shows the loading view while a navigation is pending; otherwise the page. */
export function PageFrame({ children }: { children: React.ReactNode }) {
  const { pendingHref } = useNavigation();
  return pendingHref ? <PageLoading /> : <>{children}</>;
}
