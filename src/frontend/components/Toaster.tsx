"use client";

// Sonner with our tokens — calling the project's tokens directly via
// CSS vars rather than hardcoded colors so dark mode "just works"
// without a second variant. Position is bottom-right desktop / top
// (centered) on narrow screens — mirrors Linear / claude.ai placement
// so users don't go hunting for confirmations.

import { Toaster as Sonner } from "sonner";

export function Toaster() {
  return (
    <Sonner
      theme="system"
      position="bottom-right"
      mobileOffset={{ top: "1rem", left: "1rem", right: "1rem" }}
      gap={8}
      toastOptions={{
        // The unstyled `toast.<x>` helpers paint via CSS vars Sonner
        // exposes; binding them to our design tokens keeps the look
        // consistent with the rest of the app.
        unstyled: false,
        classNames: {
          toast: "bg-[--color-bg-elev]! text-[--color-fg]! border-[--color-border-strong]! rounded-[--radius-md]! shadow-md!",
          description: "text-[--color-fg-muted]!",
          actionButton: "bg-[--color-fg]! text-[--color-bg]!",
          cancelButton: "bg-[--color-bg-sunken]! text-[--color-fg]!",
        },
      }}
    />
  );
}
