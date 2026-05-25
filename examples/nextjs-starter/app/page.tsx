/**
 * Dashboard — server component.
 *
 * Server-side fetch via the typed client. If the session is missing
 * (no cookies) or the refresh-on-401 dance also fails, we redirect
 * to /login.
 *
 * Notice: no "use client" anywhere in this file. The form below
 * uses a server action to sign out.
 */
import { redirect } from "next/navigation";
import { auth, PlynthApiError, type PlynthUser } from "@/lib/plynth";
import { signOutAction } from "./login/actions";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  let me: PlynthUser;
  try {
    me = await auth.me();
  } catch (err) {
    if (err instanceof PlynthApiError && err.status === 401) {
      redirect("/login");
    }
    throw err;
  }

  return (
    <main className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Welcome back</h1>
          <p className="text-sm text-slate-500">
            Signed in via Plynth as <code>{me.email}</code>
          </p>
        </div>
        <form action={signOutAction}>
          <button
            type="submit"
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
          >
            Sign out
          </button>
        </form>
      </header>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-4 text-lg font-semibold">Identity</h2>
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="Email" value={me.email} />
          <Field label="Full name" value={me.full_name ?? "—"} />
          <Field label="User ID" value={me.id} mono />
          <Field
            label="Active"
            value={me.is_active ? "yes" : "no"}
          />
          <Field
            label="Product"
            value={me.product_slug ?? me.product_id}
            mono
          />
          <Field
            label="Tenant"
            value={me.tenant_slug ?? me.tenant_id}
            mono
          />
        </dl>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-slate-800 dark:bg-slate-900">
        <h2 className="mb-4 text-lg font-semibold">Permissions</h2>
        {me.permissions.length === 0 ? (
          <p className="text-sm text-slate-500">No permissions granted.</p>
        ) : (
          <ul className="flex flex-wrap gap-2">
            {me.permissions.map((p) => (
              <li
                key={p}
                className="rounded bg-slate-100 px-2 py-1 font-mono text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300"
              >
                {p}
              </li>
            ))}
          </ul>
        )}
      </section>

      <footer className="text-center text-xs text-slate-400">
        See{" "}
        <code>lib/plynth.ts</code> for the API client and{" "}
        <code>app/page.tsx</code> for this server-side fetch.
      </footer>
    </main>
  );
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd
        className={
          mono
            ? "font-mono text-sm break-all text-slate-900 dark:text-slate-100"
            : "text-sm text-slate-900 dark:text-slate-100"
        }
      >
        {value}
      </dd>
    </div>
  );
}
