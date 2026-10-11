"use client";

import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTheme } from "@/components/providers/theme-provider";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  const nextTheme = theme === "dark" ? "light" : "dark";

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="icon-sm"
          aria-label={`Switch to ${nextTheme} theme`}
          aria-pressed={theme === "light"}
          onClick={toggleTheme}
          className="rounded-lg border-border/80 bg-surface/60"
        >
          {theme === "dark" ? (
            <Sun className="size-4 text-amber-300 transition-transform duration-300 hover:rotate-45" />
          ) : (
            <Moon className="size-4 text-primary transition-transform duration-300 hover:-rotate-12" />
          )}
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom">Switch to {nextTheme} theme</TooltipContent>
    </Tooltip>
  );
}
