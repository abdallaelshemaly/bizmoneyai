"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

import BizMoneyLoader from "@/components/BizMoneyLoader";
import { PUBLIC_ADMIN_PATHS, useAdminSession } from "@/hooks/useAdminSession";

export default function ProtectedAdminRoute({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { admin, loading } = useAdminSession();

  const isPublicPath = PUBLIC_ADMIN_PATHS.includes(pathname ?? "");

  useEffect(() => {
    if (loading) {
      return;
    }

    if (isPublicPath) {
      if (admin) {
        router.replace("/");
      }
      return;
    }

    if (!admin) {
      router.replace("/login");
    }
  }, [admin, isPublicPath, loading, router]);

  if (isPublicPath) {
    if (admin) {
      return null;
    }
    return <>{children}</>;
  }

  if (loading) {
    return <BizMoneyLoader fullScreen />;
  }

  if (!admin) {
    return null;
  }

  return <>{children}</>;
}
