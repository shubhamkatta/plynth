import type { HttpClient } from "../http.js";
import type { TokenStore } from "../auth.js";
import type {
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  GoogleLoginRequest,
  LoginRequest,
  LogoutRequest,
  MeResponse,
  PasswordChangeRequest,
  RegisterIndividualRequest,
  RegisterRequest,
  ResetPasswordRequest,
  Tokens,
} from "../types.js";

export class AuthResource {
  constructor(
    private readonly http: HttpClient,
    private readonly store: TokenStore,
  ) {}

  async register(req: RegisterRequest): Promise<Tokens> {
    const tokens = await this.http.request<Tokens>({
      method: "POST",
      path: "/api/v1/auth/register",
      body: req,
      skipAuth: true,
      idempotent: true,
    });
    await this.store.set(tokens);
    return tokens;
  }

  async registerIndividual(req: RegisterIndividualRequest): Promise<Tokens> {
    const tokens = await this.http.request<Tokens>({
      method: "POST",
      path: "/api/v1/auth/register-individual",
      body: req,
      skipAuth: true,
      idempotent: true,
    });
    await this.store.set(tokens);
    return tokens;
  }

  async login(req: LoginRequest): Promise<Tokens> {
    const tokens = await this.http.request<Tokens>({
      method: "POST",
      path: "/api/v1/auth/login",
      body: req,
      skipAuth: true,
    });
    await this.store.set(tokens);
    return tokens;
  }

  async google(req: GoogleLoginRequest): Promise<Tokens> {
    const tokens = await this.http.request<Tokens>({
      method: "POST",
      path: "/api/v1/auth/google",
      body: req,
      skipAuth: true,
    });
    await this.store.set(tokens);
    return tokens;
  }

  async logout(req: LogoutRequest = {}): Promise<void> {
    const tokens = await this.store.get();
    const body: LogoutRequest = {
      ...req,
      refresh_token: req.refresh_token ?? tokens?.refresh_token,
    };
    await this.http.request<void>({
      method: "POST",
      path: "/api/v1/auth/logout",
      body,
    });
    await this.store.clear();
  }

  async me(): Promise<MeResponse> {
    return this.http.request<MeResponse>({
      method: "GET",
      path: "/api/v1/auth/me",
    });
  }

  async changePassword(req: PasswordChangeRequest): Promise<void> {
    await this.http.request<void>({
      method: "POST",
      path: "/api/v1/auth/password",
      body: req,
    });
  }

  async forgotPassword(req: ForgotPasswordRequest): Promise<ForgotPasswordResponse> {
    return this.http.request<ForgotPasswordResponse>({
      method: "POST",
      path: "/api/v1/auth/password/forgot",
      body: req,
      skipAuth: true,
    });
  }

  async resetPassword(req: ResetPasswordRequest): Promise<void> {
    await this.http.request<void>({
      method: "POST",
      path: "/api/v1/auth/password/reset",
      body: req,
      skipAuth: true,
    });
  }
}
