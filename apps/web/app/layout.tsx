import type { Metadata, Viewport } from "next";
import Script from "next/script";
import "./globals.css";
import { ToastProvider } from "@/components/ui/states";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AnalysisProvider } from "@/components/providers/analysis-provider";
import { Sidebar } from "@/components/app/sidebar";
import { NavigationProvider, PageFrame } from "@/components/providers/navigation-provider";
import { RepoBar } from "@/components/app/repo-bar";
import { ThemeProvider } from "@/components/providers/theme-provider";

export const metadata: Metadata = {
  title: "RepoLens · codebase intelligence",
  icons: { icon: "/repolens-logo.jpg", shortcut: "/repolens-logo.jpg", apple: "/repolens-logo.jpg" },
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
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="min-h-svh font-sans">
        <Script
          id="repolens-theme-init"
          strategy="beforeInteractive"
          dangerouslySetInnerHTML={{
            __html: "try{var t=localStorage.getItem('repolens-theme')==='light'?'light':'dark';var r=document.documentElement;r.classList.remove('dark','light');r.classList.add(t)}catch(e){}",
          }}
        />
        <ThemeProvider>
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
        </ThemeProvider>
      </body>
    </html>
  );
}
