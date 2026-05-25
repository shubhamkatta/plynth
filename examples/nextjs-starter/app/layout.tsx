import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Plynth Next.js Starter",
  description:
    "Minimal Next.js 14 (App Router) integration of the Plynth platform.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-slate-50 text-slate-900 antialiased dark:bg-slate-950 dark:text-slate-100">
        <div className="mx-auto max-w-3xl px-6 py-10">{children}</div>
      </body>
    </html>
  );
}
