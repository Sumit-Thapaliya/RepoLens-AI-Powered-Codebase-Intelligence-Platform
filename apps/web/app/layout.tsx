import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ToastProvider } from "@/components/ui/states";
import { TooltipProvider } from "@/components/ui/tooltip";
import { AnalysisProvider } from "@/components/providers/analysis-provider";
import { Sidebar } from "@/components/app/sidebar";
import { RepoBar } from "@/components/app/repo-bar";

export const metadata: Metadata = {
  title: "RepoLens · AI codebase intelligence",
  icons: { icon: "/favicon.svg" },
  description:
    "Analyse any public GitHub repository: architecture, workflows, APIs, database models, dependencies and grounded AI answers.",
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
              <div className="flex min-h-svh w-full">
                <Sidebar />
                <div className="flex min-w-0 flex-1 flex-col">
                  <RepoBar />
                  <main className="flex-1">{children}</main>
                  <footer className="border-t border-border px-4 py-3 text-2xs text-muted-foreground lg:px-6">
                    RepoLens analyses public GitHub repositories. Every number shown is derived from parsed source —
                    heuristics are labelled, and AI answers cite the files they came from.
                  </footer>
                </div>
              </div>
            </AnalysisProvider>
          </TooltipProvider>
        </ToastProvider>
      </body>
    </html>
  );
}
