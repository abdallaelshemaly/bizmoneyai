"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import api from "@/lib/api";
const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/transactions", label: "Transactions" },
  { href: "/categories", label: "Categories" },
  { href: "/budgets", label: "Budgets" },
  { href: "/insights", label: "AI Insights" },
];
export default function Navbar({ userName }: { userName?: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const logout = async () => { await api.post("/auth/logout"); router.push("/login"); };
  return (
    <nav className="sticky top-0 z-50 flex items-center justify-between bg-ink px-6 py-3 shadow-md">
      <Link href="/dashboard" className="flex items-center gap-3 text-lg font-bold tracking-tight text-mint">
        <Image
          src="/assets/bizmoneyai-circle-logo.png"
          alt="BizMoneyAI logo"
          width={32}
          height={32}
          priority
          className="h-8 w-8 rounded-full"
        />
        <span>BizMoneyAI</span>
      </Link>
      <div className="flex items-center gap-4">
        {NAV.map(n => (
          <Link key={n.href} href={n.href}
            className={`text-sm font-medium transition-colors ${pathname.startsWith(n.href) ? "text-mint" : "text-slate-300 hover:text-white"}`}>
            {n.label}
          </Link>
        ))}
        {userName && <span className="hidden text-xs text-slate-400 sm:block">Hi, {userName}</span>}
        <button onClick={logout} className="ml-2 rounded bg-slate-700 px-3 py-1 text-xs text-white hover:bg-slate-600">Logout</button>
      </div>
    </nav>
  );
}
