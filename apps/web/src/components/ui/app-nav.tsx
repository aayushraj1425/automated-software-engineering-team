"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { signOut } from "@/lib/auth-client";

/** The one top navigation bar shared by every workspace page. Before this, each
 * page hand-rolled its own header with the links in a different order and no way
 * to tell which page you were on. Here the order is fixed, the current page is
 * highlighted, and it sticks to the top as you scroll. */
const LINKS = [
  { href: "/repositories", label: "Repositories" },
  { href: "/planning", label: "Planning" },
  { href: "/runs", label: "Agent runs" },
  { href: "/knowledge", label: "Knowledge" },
  { href: "/docs", label: "Docs" },
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
] as const;

/** True when `pathname` is the link's page or a page nested under it (so a run
 * detail at /runs/abc still marks "Agent runs" as current). */
function isActive(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppNav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-10 flex items-center gap-2 border-b border-zinc-800 bg-zinc-950/80 px-4 backdrop-blur">
      <Link
        href="/chat"
        className="mr-1 shrink-0 px-2 py-3 text-sm font-semibold tracking-wide text-zinc-100"
      >
        ASEP
      </Link>
      <nav className="flex flex-1 items-center gap-1 overflow-x-auto py-2">
        {LINKS.map((link) => {
          const active = isActive(pathname, link.href);
          return (
            <Link
              key={link.href}
              href={link.href}
              aria-current={active ? "page" : undefined}
              className={`shrink-0 rounded-md px-3 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
              }`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
      <button
        type="button"
        onClick={() => void signOut({ fetchOptions: { onSuccess: () => location.assign("/") } })}
        className="shrink-0 px-3 py-1.5 text-sm text-zinc-500 transition-colors hover:text-zinc-200"
      >
        Sign out
      </button>
    </header>
  );
}
