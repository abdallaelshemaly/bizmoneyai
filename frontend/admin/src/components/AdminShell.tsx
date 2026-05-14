"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAdminSession } from "@/hooks/useAdminSession";

type AdminShellProps = {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
};

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", blurb: "Overview" },
  { href: "/users", label: "Users", blurb: "Accounts" },
  { href: "/transactions", label: "Transactions", blurb: "Monitoring" },
  { href: "/categories", label: "Categories", blurb: "Taxonomy" },
  { href: "/budgets", label: "Budgets", blurb: "Controls" },
  { href: "/insights", label: "Insights", blurb: "AI output" },
  { href: "/logs", label: "Logs", blurb: "System events" },
];

export default function AdminShell({
  title,
  actions,
  children,
}: AdminShellProps) {
  const pathname = usePathname();
  const { admin, logout } = useAdminSession();

  if (!admin) {
    return null;
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(15,23,42,0.06),_transparent_28%),linear-gradient(180deg,_#f8fafc_0%,_#eef2ff_100%)]">
      <div className="grid min-h-screen lg:grid-cols-[280px_1fr]">
        <aside className="border-b border-slate-800 bg-slate-950 px-5 py-6 text-slate-100 lg:border-b-0 lg:border-r">
          <div className="mb-8">
            <div className="flex items-center gap-3">
              <Image
                src="/assets/bizmoneyai-circle-logo.png"
                alt="BizMoneyAI logo"
                width={34}
                height={34}
                priority
                className="h-[34px] w-[34px] rounded-full"
              />
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-emerald-300">BizMoneyAI</p>
                <h1 className="mt-1 text-2xl font-semibold">Admin Console</h1>
              </div>
            </div>
          </div>

          <nav className="flex flex-col gap-2">
            {NAV_ITEMS.map((item) => {
              const isActive = item.href === "/" ? pathname === item.href : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-2xl border px-4 py-3 transition ${
                    isActive
                      ? "border-emerald-400/60 bg-emerald-500/10 text-white"
                      : "border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-700 hover:bg-slate-900"
                  }`}
                >
                  <div className="font-medium">{item.label}</div>
                </Link>
              );
            })}
          </nav>

          <div className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
            <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Signed in</p>
            <p className="mt-2 font-medium text-white">{admin.name}</p>
            <p className="text-sm text-slate-400">{admin.email}</p>
          </div>
        </aside>

        <div className="flex min-h-screen flex-col">
          <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/85 px-6 py-5 backdrop-blur">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Admin workspace</p>
                <h2 className="mt-2 text-3xl font-semibold text-slate-950">{title}</h2>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {actions}
                <button onClick={logout} className="bg-slate-950 px-4 py-2 text-sm">
                  Logout
                </button>
              </div>
            </div>
          </header>

          <main className="flex-1 px-6 py-6 lg:px-8">{children}</main>
        </div>
      </div>
    </div>
  );
}
