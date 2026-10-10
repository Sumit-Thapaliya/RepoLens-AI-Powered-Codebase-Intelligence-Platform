import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/states";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AnalysisProvider } from "@/components/providers/analysis-provider";
import { Sidebar } from "@/components/app/sidebar";
import { NavigationProvider, PageFrame } from "@/components/providers/navigation-provider";
import { RepoBar } from "@/components/app/repo-bar";

export const metadata: Metadata = {
  title: "RepoLens · codebase intelligence",
  icons: { icon: "/favicon.svg" },
  description:
    "Analyze GitHub repositories with static architecture, workflow, API, database, dependency, search and impact insights.",
};

export const viewport: Viewport = {
  themeColor: "#0b0d12",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-svh font-sans">
        <ToastProvider>
          <TooltipProvider delayDuration={200}>
            <AnalysisProvider>
              <NavigationProvider>
                <div className="flex min-h-svh w-full">
                  <Sidebar />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <RepoBar />
                    <main className="flex-1">
                      <PageFrame>{children}</PageFrame>
                    </main>
                    <footer className="border-t border-border px-4 py-3 text-2xs text-muted-foreground lg:px-6">
                      RepoLens statically analyzes GitHub repositories. Every number comes from parsed source;
                      heuristic findings are labelled, and nothing is sent to a language model.
                    </footer>
                  </div>
                </div>
              </NavigationProvider>
            </AnalysisProvider>
          </TooltipProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
