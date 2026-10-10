"use client";

import * as React from "react";
import { usePathname } from "next/navigation";

/**
 * Keeps the current page visible while Next.js completes navigation. Cached page
 * data then renders immediately, with only a thin progress indicator during routing.
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

/** Keeps the page mounted and shows a thin route progress indicator while navigation is pending. */
export function PageFrame({ children }: { children: React.ReactNode }) {
  const { pendingHref } = useNavigation();
  return (
    <>
      {pendingHref ? (
        <div aria-hidden="true" className="fixed inset-x-0 top-0 z-[100] h-0.5 overflow-hidden bg-primary/10">
          <div className="h-full w-1/3 animate-pulse bg-primary" />
        </div>
      ) : null}
      {children}
    </>
  );
}
