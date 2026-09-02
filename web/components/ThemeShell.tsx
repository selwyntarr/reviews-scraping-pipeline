"use client";
import { Theme } from "@radix-ui/themes";
import { createContext, useContext, useEffect, useState } from "react";

type Mode = "light" | "dark";
const Ctx = createContext<{ mode: Mode; toggle: () => void }>({ mode: "light", toggle: () => {} });
export const useTheme = () => useContext(Ctx);

export function ThemeShell({ children }: { children: React.ReactNode }) {
  const [mode, setMode] = useState<Mode>("light");
  useEffect(() => {
    let m: Mode = window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    try { const s = localStorage.getItem("theme"); if (s === "dark" || s === "light") m = s; } catch {}
    setMode(m);
  }, []);
  const toggle = () => setMode((m) => { const n = m === "dark" ? "light" : "dark"; try { localStorage.setItem("theme", n); } catch {} return n; });
  return (
    <Ctx.Provider value={{ mode, toggle }}>
      <Theme appearance={mode} accentColor="indigo" grayColor="slate" radius="large" className={mode === "dark" ? "dark" : ""}>
        {children}
      </Theme>
    </Ctx.Provider>
  );
}
