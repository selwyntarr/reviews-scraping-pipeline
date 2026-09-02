import type { Metadata } from "next";
import "./globals.css";
import { ThemeShell } from "@/components/ThemeShell";

export const metadata: Metadata = {
  title: "Venue Insight Explorer",
  description: "Manhattan venues with mood, best-time and insider details extracted from open sources.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body><ThemeShell>{children}</ThemeShell></body>
    </html>
  );
}
