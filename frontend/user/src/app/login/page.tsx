"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";

import api from "@/lib/api";

function BrandMark() {
  return (
    <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-400 to-emerald-700 text-4xl font-bold text-white shadow-[0_18px_40px_rgba(16,185,129,0.35)]">
      B
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

export default function LoginPage() {
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
      await api.post("/auth/login", form);
      router.push("/dashboard");
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Invalid email or password.";
      setError(String(msg));
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[radial-gradient(circle_at_10%_78%,rgba(52,211,153,0.22),transparent_5%),radial-gradient(circle_at_90%_88%,rgba(34,197,94,0.18),transparent_7%),linear-gradient(135deg,#fbfefc_0%,#f2fbf7_52%,#f8fcf8_100%)] px-4 py-10">
      <div className="pointer-events-none absolute -left-16 top-8 h-64 w-[34rem] rounded-[50%] border border-emerald-100/70" />
      <div className="pointer-events-none absolute -left-12 top-14 h-64 w-[34rem] rounded-[50%] border border-emerald-100/50" />
      <div className="pointer-events-none absolute -right-20 top-72 h-72 w-[34rem] rounded-[50%] border border-emerald-100/70" />
      <div className="pointer-events-none absolute bottom-8 left-28 h-3 w-3 rounded-full bg-emerald-300/70" />
      <div className="pointer-events-none absolute left-24 top-1/3 h-3 w-3 rounded-full bg-emerald-300/60" />
      <div className="pointer-events-none absolute right-20 top-[58%] h-3 w-3 rounded-full bg-emerald-300/60" />

      <section className="relative z-10 flex w-full max-w-[35rem] flex-col items-center">
        <div className="mb-10 flex flex-col items-center text-center">
          <BrandMark />
          <h1 className="mt-6 text-4xl font-extrabold tracking-normal text-slate-950 sm:text-5xl">
            BizMoney<span className="text-emerald-600">AI</span>
          </h1>
          <p className="mt-3 text-lg font-medium text-slate-500">Smart Finance. Smarter Decisions.</p>
        </div>

        <div className="w-full rounded-2xl border border-white/80 bg-white/95 p-7 shadow-[0_24px_70px_rgba(15,23,42,0.12)] backdrop-blur sm:p-9">
          <div className="mb-9 text-center">
            <h2 className="text-2xl font-bold text-slate-950">Welcome back</h2>
            <p className="mt-2 text-base font-medium text-slate-500">Sign in to your account</p>
          </div>
        {error && (
            <p className="mb-5 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-medium text-red-700">{error}</p>
        )}
          <form onSubmit={handleSubmit} className="space-y-5">
          <div>
              <label className="mb-3 block text-sm font-bold text-slate-950">Email</label>
              <div className="relative">
                <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500">
                  <MailIcon />
                </span>
                <input
                  type="email"
                  name="email"
                  autoComplete="email"
                  suppressHydrationWarning
                  placeholder="you@example.com"
                  className="h-14 w-full rounded-lg border border-slate-300 bg-white pl-12 pr-4 text-base text-slate-900 shadow-sm outline-none transition placeholder:text-slate-500 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  required
                />
              </div>
          </div>
          <div>
              <label className="mb-3 block text-sm font-bold text-slate-950">Password</label>
              <div className="relative">
                <span className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500">
                  <LockIcon />
                </span>
                <input
                  type={showPassword ? "text" : "password"}
                  name="password"
                  autoComplete="current-password"
                  suppressHydrationWarning
                  placeholder="********"
                  className="h-14 w-full rounded-lg border border-slate-300 bg-white pl-12 pr-12 text-base text-slate-900 shadow-sm outline-none transition placeholder:text-slate-500 focus:border-emerald-500 focus:ring-2 focus:ring-emerald-100"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  required
                />
                <button
                  type="button"
                  aria-label={showPassword ? "Hide password" : "Show password"}
                  onClick={() => setShowPassword((value) => !value)}
                  className="absolute right-4 top-1/2 -translate-y-1/2 bg-transparent p-0 text-slate-500 shadow-none ring-0 hover:text-slate-800 hover:opacity-100"
                >
                  <EyeIcon hidden={!showPassword} />
                </button>
              </div>
          </div>
            <label className="flex w-fit items-center gap-3 text-sm font-semibold text-slate-950">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
                className="h-5 w-5 rounded border-slate-300 p-0 text-emerald-600 focus:ring-emerald-500"
              />
              Remember me
            </label>
          <button
            type="submit"
              className="flex h-14 w-full items-center justify-center gap-3 rounded-lg bg-slate-950 text-base font-bold text-white shadow-[0_14px_30px_rgba(2,6,23,0.22)] transition hover:bg-slate-900 hover:opacity-100 disabled:opacity-60"
            disabled={loading}
            suppressHydrationWarning
          >
              <LockIcon />
            {loading ? "Signing in..." : "Sign in"}
          </button>
        </form>
        </div>
      </section>
    </main>
  );
}
