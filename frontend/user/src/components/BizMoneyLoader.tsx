"use client";

import Image from "next/image";

type BizMoneyLoaderProps = {
  fullScreen?: boolean;
  minHeightClassName?: string;
  label?: string;
};

export default function BizMoneyLoader({
  fullScreen = false,
  minHeightClassName = "min-h-[18rem]",
  label = "",
}: BizMoneyLoaderProps) {
  const shellClassName = fullScreen
    ? "min-h-screen rounded-none"
    : `${minHeightClassName} rounded-[2rem]`;

  return (
    <div className={`relative isolate flex w-full items-center justify-center overflow-hidden px-6 py-10 ${shellClassName}`}>
      <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,_rgba(20,184,166,0.16),transparent_38%),radial-gradient(circle_at_bottom_left,_rgba(15,23,42,0.08),transparent_45%),linear-gradient(180deg,#f0fdf4_0%,#fefce8_100%)]" />
      <div className="absolute inset-0 opacity-70 [background-image:linear-gradient(135deg,rgba(255,255,255,0.24)_0,rgba(255,255,255,0)_28%,rgba(20,184,166,0.08)_100%)]" />

      <div className="relative flex flex-col items-center text-center">
        <div className="relative">
          <div className="absolute inset-3 rounded-full bg-emerald-400/25 blur-3xl" />
          <div className="bizmoney-loader-heartbeat relative rounded-full bg-white/88 p-2 shadow-[0_24px_60px_rgba(15,23,42,0.14)] ring-1 ring-emerald-100/80 backdrop-blur">
            <Image
              src="/assets/bizmoneyai-circle-logo.png"
              alt="BizMoneyAI logo"
              width={160}
              height={160}
              priority
              className="h-28 w-28 rounded-full sm:h-32 sm:w-32 md:h-36 md:w-36"
            />
          </div>
        </div>

        <div className="mt-5 space-y-2">
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.38em] text-teal-700/70">BizMoneyAI</p>
          {label ? <p className="text-sm text-slate-500">{label}</p> : null}
        </div>
      </div>

      <style jsx>{`
        @keyframes bizmoney-loader-heartbeat {
          0%,
          100% {
            transform: scale(1);
          }
          12% {
            transform: scale(1.06);
          }
          24% {
            transform: scale(1);
          }
          42% {
            transform: scale(1.03);
          }
          54% {
            transform: scale(1);
          }
        }

        .bizmoney-loader-heartbeat {
          animation: bizmoney-loader-heartbeat 1.5s ease-in-out infinite;
          transform-origin: center;
        }
      `}</style>
    </div>
  );
}
