/**
 * /login — client form, server action.
 *
 * The form posts to a server action (`loginAction`) which calls the
 * platform via the typed client and writes the resulting tokens into
 * HttpOnly cookies before redirecting to `/`.
 */
"use client";

import Link from "next/link";
import { useFormState, useFormStatus } from "react-dom";
import { loginAction, INITIAL_AUTH_STATE } from "./actions";

export default function LoginPage() {
  const [state, formAction] = useFormState(loginAction, INITIAL_AUTH_STATE);

  return (
    <main className="mx-auto max-w-md space-y-6">
      <header>
        <h1 className="text-2xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-slate-500">
          Sign in to your Plynth-backed account.
        </p>
      </header>

      <form action={formAction} className="space-y-4">
        <Field
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          required
        />
        <Field
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
        />
        <Field
          label="Tenant slug (only if your email is in multiple tenants)"
          name="tenant_slug"
          type="text"
          autoComplete="off"
        />

        {state.error ? (
          <p
            role="alert"
            className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-200"
          >
            {state.error}
          </p>
        ) : null}

        <SubmitButton />
      </form>

      <p className="text-center text-sm text-slate-500">
        New here?{" "}
        <Link href="/signup" className="font-medium underline">
          Create an account
        </Link>
      </p>
    </main>
  );
}

function Field({
  label,
  name,
  type,
  required,
  autoComplete,
}: {
  label: string;
  name: string;
  type: string;
  required?: boolean;
  autoComplete?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium">{label}</span>
      <input
        name={name}
        type={type}
        required={required}
        autoComplete={autoComplete}
        className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 dark:border-slate-700 dark:bg-slate-900"
      />
    </label>
  );
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="w-full rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60 dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white"
    >
      {pending ? "Signing in…" : "Sign in"}
    </button>
  );
}
