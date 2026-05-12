"use client";
import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import api from "@/lib/api";

export type AuthUser = { user_id: number; name: string; email: string; is_active: boolean; created_at: string };

const PUBLIC_PATHS = ["/login"];

export function useAuth() {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<AuthUser>("/auth/me")
      .then(r => setUser(r.data))
      .catch(() => {
        setUser(null);
        if (!PUBLIC_PATHS.includes(pathname ?? "")) router.push("/login");
      })
      .finally(() => setLoading(false));
  }, [router, pathname]);

  const logout = async () => {
    try { await api.post("/auth/logout"); } catch {}
    setUser(null);
    router.push("/login");
  };

  return { user, loading, logout };
}
