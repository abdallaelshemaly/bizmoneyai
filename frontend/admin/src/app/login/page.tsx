"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import api from "@/lib/api";

function AdminMark() {
  return (
    <div className="flex h-20 w-20 items-center justify-center rounded-[1.35rem] bg-gradient-to-br from-emerald-400 via-emerald-600 to-emerald-800 shadow-[0_22px_55px_rgba(16,185,129,0.28)]">
      <svg className="h-11 w-11 text-white" aria-hidden="true" viewBox="0 0 24 24" fill="none">
        <path d="M12 11.25a3.25 3.25 0 1 0 0-6.5 3.25 3.25 0 0 0 0 6.5Z" fill="currentColor" />
        <path d="M5.75 18.25c.75-3.05 3.1-4.5 6.25-4.5s5.5 1.45 6.25 4.5c.15.62-.36 1.25-1 1.25H6.75c-.64 0-1.15-.63-1-1.25Z" fill="currentColor" />
      </svg>
    </div>
  );
}

function MailIcon() {
  return (
    <svg className="h-5 w-5" aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="M4.75 6.75h14.5v10.5H4.75z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="m5.25 7.25 6.75 5 6.75-5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg className="h-5 w-5" aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="M7.75 10.75h8.5v7.5h-8.5z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="M9.25 10.75V8.9a2.75 2.75 0 0 1 5.5 0v1.85" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M12 14.25v1.5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}

function EyeIcon({ hidden }: { hidden: boolean }) {
  return (
    <svg className="h-5 w-5" aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path
        d="M3.75 12s2.85-5.25 8.25-5.25S20.25 12 20.25 12 17.4 17.25 12 17.25 3.75 12 3.75 12Z"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M12 14.25a2.25 2.25 0 1 0 0-4.5 2.25 2.25 0 0 0 0 4.5Z" stroke="currentColor" strokeWidth="1.7" />
      {hidden && <path d="m5 19 14-14" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />}
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg className="h-5 w-5" aria-hidden="true" viewBox="0 0 24 24" fill="none">
      <path d="M12 3.75 18.25 6v5.4c0 4.05-2.5 7.35-6.25 8.85-3.75-1.5-6.25-4.8-6.25-8.85V6L12 3.75Z" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />
      <path d="m9.75 11.9 1.55 1.55 3.25-3.35" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function AdminLoginPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      await api.post("/admin/auth/login", form);
      router.push("/");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Invalid admin email or password.";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_50%_10%,rgba(20,184,166,0.12),transparent_20%),radial-gradient(circle_at_52%_78%,rgba(16,185,129,0.12),transparent_22%),linear-gradient(135deg,#031126_0%,#071a34_48%,#061329_100%)] px-4 py-10 text-white">
      <div className="pointer-events-none absolute left-8 top-28 h-44 w-44 rounded-[2rem] border border-white/5" />
      <div className="pointer-events-none absolute right-8 top-10 grid grid-cols-4 gap-5 opacity-20">
        {Array.from({ length: 24 }).map((_, index) => (
          <span key={index} className="h-1.5 w-1.5 rounded-full bg-slate-400" />
        ))}
      </div>
      <div className="pointer-events-none absolute -bottom-24 right-0 h-72 w-[48rem] rounded-[50%] border border-emerald-300/10" />
      <div className="pointer-events-none absolute -bottom-16 right-10 h-72 w-[48rem] rounded-[50%] border border-emerald-300/10" />
      <div className="pointer-events-none absolute bottom-28 left-8 grid grid-cols-8 gap-4 opacity-10">
        {Array.from({ length: 48 }).map((_, index) => (
          <span key={index} className="h-1 w-1 rounded-full bg-emerald-200" />
        ))}
      </div>

      <section className="relative z-10 flex w-full max-w-[42rem] flex-col items-center">
        <AdminMark />
        <div className="mt-7 rounded-full border border-white/15 bg-white/[0.03] px-8 py-3 text-sm font-bold uppercase tracking-[0.22em] text-emerald-300 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
          ADMIN PORTAL
        </div>
        <div className="mt-6 text-center">
          <h1 className="text-4xl font-extrabold tracking-normal text-white sm:text-5xl">Admin Sign In</h1>
          <p className="mt-4 text-lg font-medium text-slate-200">Access the BizMoneyAI Admin Console</p>
        </div>

        <div className="mt-7 w-full rounded-3xl border border-white/15 bg-white/[0.045] p-7 shadow-[0_28px_80px_rgba(0,0,0,0.3)] backdrop-blur sm:p-9">
          {error && <p className="mb-5 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm font-medium text-red-100">{error}</p>}
          <form onSubmit={handleSubmit} className="space-y-6">
          <div>
              <label className="mb-3 block text-sm font-bold text-slate-100">Email</label>
              <div className="relative">
                <span className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-slate-200">
                  <MailIcon />
                </span>
                <input
                  type="email"
                  name="email"
                  placeholder="admin@example.com"
                  autoComplete="email"
                  className="h-16 w-full rounded-lg border border-white/15 bg-[#071a34]/70 pl-14 pr-5 text-base text-white outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/15"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                />
              </div>
          </div>
          <div>
              <label className="mb-3 block text-sm font-bold text-slate-100">Password</label>
              <div className="relative">
                <span className="pointer-events-none absolute left-5 top-1/2 -translate-y-1/2 text-slate-200">
                  <LockIcon />
                </span>
                <input
                  type={showPassword ? "text" : "password"}
                  name="password"
                  placeholder="********"
                  autoComplete="current-password"
                  className="h-16 w-full rounded-lg border border-white/15 bg-[#071a34]/70 pl-14 pr-14 text-base text-white outline-none transition placeholder:text-slate-400 focus:border-emerald-400 focus:ring-2 focus:ring-emerald-400/15"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute right-5 top-1/2 -translate-y-1/2 bg-transparent p-0 text-slate-200 shadow-none ring-0 hover:text-white hover:opacity-100"
                >
                  <EyeIcon hidden={!showPassword} />
                </button>
              </div>
          </div>
            <label className="flex w-fit items-center gap-3 text-sm font-semibold text-slate-100">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-5 w-5 rounded border-white/30 bg-transparent p-0 text-emerald-500 focus:ring-emerald-400"
              />
              Remember me
            </label>
          <button
              type="submit"
              className="flex h-16 w-full items-center justify-center gap-3 rounded-lg bg-gradient-to-r from-emerald-500 to-emerald-600 text-lg font-bold text-white shadow-[0_18px_40px_rgba(16,185,129,0.28)] transition hover:from-emerald-400 hover:to-emerald-600 hover:opacity-100 disabled:opacity-60"
              disabled={loading}
            >
              <ShieldIcon />
              {loading ? "Signing in..." : "Sign in as Admin"}
          </button>
        </form>
        </div>

        <div className="mt-9 flex items-center gap-3 text-base font-medium text-slate-400">
          <LockIcon />
          <span>Secure admin access</span>
        </div>
      </section>
    </main>
  );
}
