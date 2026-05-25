"use server";

/**
 * Server actions for the auth flows.
 *
 * Server actions run on the Node runtime, so they have access to
 * `cookies()` (in lib/session.ts) and can call the platform with the
 * shared service URL — credentials never round-trip through the browser
 * except in the original form POST.
 */
import { redirect } from "next/navigation";
import { auth, PlynthApiError } from "@/lib/plynth";

export type AuthFormState = {
  error: string | null;
};

const INITIAL: AuthFormState = { error: null };

export async function loginAction(
  _prev: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const tenantSlug = String(formData.get("tenant_slug") ?? "").trim();

  if (!email || !password) {
    return { error: "Email and password are required." };
  }

  try {
    await auth.login({
      email,
      password,
      tenant_slug: tenantSlug || undefined,
    });
  } catch (err) {
    return { error: friendlyError(err) };
  }
  redirect("/");
}

export async function registerIndividualAction(
  _prev: AuthFormState,
  formData: FormData,
): Promise<AuthFormState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const fullName = String(formData.get("full_name") ?? "").trim();

  if (!email || !password) {
    return { error: "Email and password are required." };
  }
  if (password.length < 12) {
    return { error: "Password must be at least 12 characters." };
  }

  try {
    await auth.registerIndividual({
      email,
      password,
      full_name: fullName || undefined,
    });
  } catch (err) {
    return { error: friendlyError(err) };
  }
  redirect("/");
}

export async function signOutAction(): Promise<void> {
  await auth.logout();
  redirect("/login");
}

export { INITIAL as INITIAL_AUTH_STATE };

function friendlyError(err: unknown): string {
  if (err instanceof PlynthApiError) {
    // Branch on .code per platform contract; .message is informational.
    switch (err.code) {
      case "unauthorized":
        return "Wrong email or password.";
      case "validation_failed":
        return "Please check the fields and try again.";
      case "conflict":
        return "An account with that email already exists for this product.";
      case "rate_limited":
        return "Too many attempts. Slow down and try again shortly.";
      default:
        return err.message || "Something went wrong. Please try again.";
    }
  }
  return "Network error. Please try again.";
}
