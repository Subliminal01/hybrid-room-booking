const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export type UserRole = "worker" | "host" | "admin";
export type WorkspaceStatus = "draft" | "active" | "paused";
export type WorkspaceReviewStatus = "pending" | "approved" | "rejected";
export type BookingStatus = "pending" | "confirmed" | "cancelled" | "expired";
export type AuditAction =
  | "admin_bootstrapped"
  | "user_profile_updated"
  | "password_changed"
  | "workspace_created"
  | "workspace_reviewed"
  | "booking_paid"
  | "booking_cancelled"
  | "payment_failed"
  | "payment_refunded";

export type AvailabilityRule = {
  id: string;
  workspace_id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
};

export type BlackoutDate = {
  id: string;
  workspace_id: string;
  blackout_date: string;
  reason: string | null;
};

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  phone_number: string | null;
  is_active: boolean;
  email_verified_at: string | null;
};

export type TokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
  user: User;
};

export type TimeSlot = {
  start_at: string;
  end_at: string;
};

export type Workspace = {
  id: string;
  owner_id?: string;
  title: string;
  description: string | null;
  address_line: string;
  city: string;
  state: string | null;
  country: string;
  postal_code?: string | null;
  photo_url: string | null;
  daily_price: string;
  estimated_total_price?: string;
  matched_slot_count?: number;
  matched_slots?: TimeSlot[];
  currency: string;
  capacity: number;
  status?: WorkspaceStatus;
  review_status?: WorkspaceReviewStatus;
  amenities: Record<string, unknown>;
  availability_rules?: AvailabilityRule[];
  blackout_dates?: BlackoutDate[];
};

export type Booking = {
  id: string;
  booking_group_id: string;
  user_id: string;
  workspace_id: string;
  start_at: string;
  end_at: string;
  status: BookingStatus;
  total_price: string;
  rota_label: string | null;
  notes: string | null;
  expires_at: string | null;
  workspace: {
    id: string;
    title: string;
    address_line: string;
    city: string;
    photo_url: string | null;
    currency: string;
  } | null;
  user: {
    id: string;
    full_name: string;
    email: string;
  } | null;
};

export type BookingCreateResponse = {
  bookings: Booking[];
  total_price: string;
};

export type Payment = {
  id: string;
  booking_id: string;
  created_at: string;
  updated_at: string;
  amount: string;
  currency: string;
  status: "pending" | "succeeded" | "failed" | "refunded";
  provider: string;
  provider_reference: string;
  provider_checkout_reference: string | null;
  paid_at: string | null;
  refunded_at: string | null;
};

export type BookingGroupCheckout = {
  booking_group_id: string;
  bookings: Booking[];
  payments: Payment[];
  total_paid: string;
};

export type PaymentCheckoutSession = {
  booking_group_id: string;
  payments: Payment[];
  total_amount: string;
  currency: string;
  provider: string;
  checkout_reference: string;
  checkout_url: string;
  checkout_payload: Record<string, unknown>;
};

export type BookingGroupCancel = {
  booking_group_id: string;
  bookings: Booking[];
  refunded_payments: Payment[];
  total_refunded: string;
};

export type BookingGroupReceipt = {
  booking_group_id: string;
  receipt_number: string;
  supplier: {
    name: string;
    email: string | null;
    address: string | null;
  };
  customer: {
    name: string;
    email: string | null;
    address: string | null;
  };
  host: {
    name: string;
    email: string | null;
    address: string | null;
  };
  workspace_title: string;
  workspace_address: string;
  line_items: {
    booking_id: string;
    description: string;
    service_date: string;
    start_at: string;
    end_at: string;
    quantity: number;
    unit_price: string;
    amount: string;
  }[];
  payment_summary: {
    payment_id: string;
    provider: string;
    provider_reference: string;
    provider_checkout_reference: string | null;
    status: "pending" | "succeeded" | "failed" | "refunded";
    amount: string;
    paid_at: string | null;
    refunded_at: string | null;
  }[];
  bookings: Booking[];
  payments: Payment[];
  subtotal: string;
  tax_total: string;
  total_paid: string;
  total_refunded: string;
  net_paid: string;
  currency: string;
  issued_at: string;
  paid_at: string | null;
};

export type HostRevenueSummary = {
  total_paid: string;
  total_refunded: string;
  gross_revenue: string;
  platform_commission_rate: string;
  platform_commission: string;
  host_net_revenue: string;
  pending_payout: string;
  pending_hold_value: string;
  confirmed_booking_count: number;
  cancelled_booking_count: number;
  pending_booking_count: number;
  paid_payment_count: number;
  currency: string;
};

export type BookingPage = {
  items: Booking[];
  total: number;
  limit: number;
  offset: number;
};

export type AuditEvent = {
  id: string;
  actor_user_id: string | null;
  action: AuditAction;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

export type AuditEventPage = {
  items: AuditEvent[];
  total: number;
  limit: number;
  offset: number;
};

export type UserPage = {
  items: User[];
  total: number;
  limit: number;
  offset: number;
};

export type PaymentPage = {
  items: Payment[];
  total: number;
  limit: number;
  offset: number;
};

export type PaymentProviderStatus = {
  provider: string;
  ready: boolean;
  webhook_url: string;
  required_settings: string[];
  missing_settings: string[];
  manual_confirmation_enabled: boolean;
};

export type EmailStatus = {
  provider: string;
  ready: boolean;
  from_address: string;
  smtp_host: string | null;
  smtp_port: number | null;
  smtp_use_tls: boolean;
  smtp_use_ssl: boolean;
  required_settings: string[];
  missing_settings: string[];
  test_supported: boolean;
};

export type StorageStatus = {
  provider: string;
  ready: boolean;
  durable: boolean;
  public_base_url: string | null;
  required_settings: string[];
  missing_settings: string[];
};

type RequestOptions = {
  token?: string;
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
};

type ApiErrorBody = {
  detail?: unknown;
  error_code?: string;
  request_id?: string;
};

export class ApiError extends Error {
  status: number;
  errorCode: string | null;
  requestId: string | null;

  constructor(message: string, options: {
    status: number;
    errorCode?: string | null;
    requestId?: string | null;
  }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.errorCode = options.errorCode ?? null;
    this.requestId = options.requestId ?? null;
  }
}

function errorMessageFromDetail(detail: unknown, fallback: string) {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const firstError = detail[0] as { msg?: unknown };
    if (typeof firstError.msg === "string") {
      return firstError.msg;
    }
  }
  return fallback;
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers: {
      "Content-Type": "application/json",
      ...(options.token ? { Authorization: `Bearer ${options.token}` } : {}),
      ...options.headers,
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    let errorCode: string | null = null;
    let requestId = response.headers.get("X-Request-ID");
    try {
      const body = (await response.json()) as ApiErrorBody;
      message = errorMessageFromDetail(body.detail, message);
      if (typeof body.error_code === "string") {
        errorCode = body.error_code;
      }
      if (typeof body.request_id === "string") {
        requestId = body.request_id;
      }
    } catch {
      // Keep status message when backend returns no JSON body.
    }
    if (requestId) {
      console.warn("API request failed", { path, status: response.status, requestId });
    }
    throw new ApiError(message, {
      status: response.status,
      errorCode,
      requestId,
    });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export function reportClientError(payload: {
  message: string;
  source?: string;
  url?: string | null;
  stack?: string | null;
  component_stack?: string | null;
  user_agent?: string | null;
}) {
  return fetch(`${API_BASE_URL}/monitoring/client-errors`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      source: "frontend",
      ...payload,
    }),
    keepalive: true,
  }).catch(() => undefined);
}

async function apiFormRequest<T>(path: string, token: string, body: FormData): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body,
  });

  if (!response.ok) {
    let message = `Request failed with ${response.status}`;
    let errorCode: string | null = null;
    let requestId = response.headers.get("X-Request-ID");
    try {
      const errorBody = (await response.json()) as ApiErrorBody;
      message = errorMessageFromDetail(errorBody.detail, message);
      if (typeof errorBody.error_code === "string") {
        errorCode = errorBody.error_code;
      }
      if (typeof errorBody.request_id === "string") {
        requestId = errorBody.request_id;
      }
    } catch {
      // Keep status message when backend returns no JSON body.
    }
    if (requestId) {
      console.warn("API form request failed", { path, status: response.status, requestId });
    }
    throw new ApiError(message, {
      status: response.status,
      errorCode,
      requestId,
    });
  }

  return response.json() as Promise<T>;
}

export function register(payload: {
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
}) {
  return apiRequest<TokenResponse>("/auth/register", {
    method: "POST",
    body: payload,
  });
}

export function login(payload: { email: string; password: string }) {
  return apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    body: payload,
  });
}

export function refreshSession(refreshToken: string) {
  return apiRequest<TokenResponse>("/auth/refresh", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export function logoutSession(refreshToken: string) {
  return apiRequest<void>("/auth/logout", {
    method: "POST",
    body: { refresh_token: refreshToken },
  });
}

export function updateMe(token: string, payload: {
  full_name?: string;
  phone_number?: string | null;
}) {
  return apiRequest<User>("/auth/me", {
    token,
    method: "PATCH",
    body: payload,
  });
}

export function changePassword(token: string, payload: {
  current_password: string;
  new_password: string;
}) {
  return apiRequest<void>("/auth/password", {
    token,
    method: "POST",
    body: payload,
  });
}

export function requestEmailVerification(token: string) {
  return apiRequest<{ message: string; verification_token: string | null }>("/auth/email-verification/request", {
    token,
    method: "POST",
  });
}

export function confirmEmailVerification(token: string) {
  return apiRequest<User>("/auth/email-verification/confirm", {
    method: "POST",
    body: { token },
  });
}

export function requestPasswordReset(email: string) {
  return apiRequest<{ message: string; reset_token: string | null }>("/auth/password-reset/request", {
    method: "POST",
    body: { email },
  });
}

export function confirmPasswordReset(payload: { token: string; new_password: string }) {
  return apiRequest<User>("/auth/password-reset/confirm", {
    method: "POST",
    body: payload,
  });
}

export function searchWorkspaces(payload: {
  city?: string;
  min_daily_price?: string;
  max_daily_price?: string;
  slots: TimeSlot[];
}) {
  return apiRequest<Workspace[]>("/workspaces/search", {
    method: "POST",
    body: payload,
  });
}

export function createBooking(token: string, payload: {
  workspace_id: string;
  slots: TimeSlot[];
  rota_label?: string;
  notes?: string;
}, options: { idempotencyKey?: string } = {}) {
  const headers = options.idempotencyKey
    ? { "Idempotency-Key": options.idempotencyKey }
    : undefined;
  return apiRequest<BookingCreateResponse>("/bookings", {
    token,
    method: "POST",
    headers,
    body: payload,
  });
}

export function createBookingItinerary(token: string, payload: {
  items: Array<{
    workspace_id: string;
    slots: TimeSlot[];
  }>;
  rota_label?: string;
  notes?: string;
}, options: { idempotencyKey?: string } = {}) {
  const headers = options.idempotencyKey
    ? { "Idempotency-Key": options.idempotencyKey }
    : undefined;
  return apiRequest<BookingCreateResponse>("/booking-itineraries", {
    token,
    method: "POST",
    headers,
    body: payload,
  });
}

export function listMyBookings(token: string, params: { limit?: number; offset?: number } = {}) {
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  return apiRequest<BookingPage>(`/bookings/mine?limit=${limit}&offset=${offset}`, { token });
}

export function cancelBooking(token: string, bookingId: string) {
  return apiRequest<Booking>(`/bookings/${bookingId}/cancel`, {
    token,
    method: "PATCH",
  });
}

export function createPaymentIntent(token: string, bookingId: string) {
  return apiRequest<Payment>(`/bookings/${bookingId}/payment-intent`, {
    token,
    method: "POST",
  });
}

export function confirmBookingPayment(token: string, bookingId: string) {
  return apiRequest<Booking>(`/bookings/${bookingId}/payment-confirm`, {
    token,
    method: "POST",
  });
}

export function createBookingGroupPaymentIntent(token: string, bookingGroupId: string) {
  return apiRequest<Payment[]>(`/booking-groups/${bookingGroupId}/payment-intent`, {
    token,
    method: "POST",
  });
}

export function createBookingGroupCheckoutSession(token: string, bookingGroupId: string) {
  return apiRequest<PaymentCheckoutSession>(
    `/booking-groups/${bookingGroupId}/checkout-session`,
    {
      token,
      method: "POST",
    },
  );
}

export function confirmBookingGroupPayment(token: string, bookingGroupId: string) {
  return apiRequest<BookingGroupCheckout>(`/booking-groups/${bookingGroupId}/payment-confirm`, {
    token,
    method: "POST",
  });
}

export function cancelBookingGroup(token: string, bookingGroupId: string) {
  return apiRequest<BookingGroupCancel>(`/booking-groups/${bookingGroupId}/cancel`, {
    token,
    method: "PATCH",
  });
}

export function getBookingGroupReceipt(token: string, bookingGroupId: string) {
  return apiRequest<BookingGroupReceipt>(`/booking-groups/${bookingGroupId}/receipt`, {
    token,
  });
}

export function createWorkspace(token: string, payload: {
  title: string;
  description?: string;
  address_line: string;
  city: string;
  state?: string;
  photo_url?: string;
  daily_price: string;
  amenities: Record<string, unknown>;
}) {
  return apiRequest<Workspace>("/workspaces", {
    token,
    method: "POST",
    body: payload,
  });
}

export function listMyWorkspaces(token: string) {
  return apiRequest<Workspace[]>("/workspaces/mine", { token });
}

export function listWorkspacesForReview(token: string, reviewStatus?: WorkspaceReviewStatus) {
  const query = reviewStatus ? `?review_status=${reviewStatus}` : "";
  return apiRequest<Workspace[]>(`/admin/workspaces/review${query}`, { token });
}

export function listAuditEvents(
  token: string,
  params: { limit?: number; offset?: number; action?: AuditAction; entity_type?: string } = {},
) {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 20));
  query.set("offset", String(params.offset ?? 0));
  if (params.action) {
    query.set("action", params.action);
  }
  if (params.entity_type) {
    query.set("entity_type", params.entity_type);
  }
  return apiRequest<AuditEventPage>(`/admin/audit-events?${query.toString()}`, { token });
}

export function listAdminUsers(
  token: string,
  params: { limit?: number; offset?: number; role?: UserRole; is_active?: boolean } = {},
) {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 20));
  query.set("offset", String(params.offset ?? 0));
  if (params.role) {
    query.set("role", params.role);
  }
  if (params.is_active !== undefined) {
    query.set("is_active", String(params.is_active));
  }
  return apiRequest<UserPage>(`/admin/users?${query.toString()}`, { token });
}

export function listAdminBookings(
  token: string,
  params: { limit?: number; offset?: number; status?: BookingStatus } = {},
) {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 20));
  query.set("offset", String(params.offset ?? 0));
  if (params.status) {
    query.set("status", params.status);
  }
  return apiRequest<BookingPage>(`/admin/bookings?${query.toString()}`, { token });
}

export function listAdminPayments(
  token: string,
  params: { limit?: number; offset?: number; status?: Payment["status"]; provider?: string } = {},
) {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 20));
  query.set("offset", String(params.offset ?? 0));
  if (params.status) {
    query.set("status", params.status);
  }
  if (params.provider) {
    query.set("provider", params.provider);
  }
  return apiRequest<PaymentPage>(`/admin/payments?${query.toString()}`, { token });
}

export function getAdminPaymentProviderStatus(token: string) {
  return apiRequest<PaymentProviderStatus>("/admin/payment-provider/status", { token });
}

export function getAdminEmailStatus(token: string) {
  return apiRequest<EmailStatus>("/admin/email/status", { token });
}

export function getAdminStorageStatus(token: string) {
  return apiRequest<StorageStatus>("/admin/storage/status", { token });
}

export function sendAdminEmailTest(token: string) {
  return apiRequest<{ message: string; provider: string; recipient: string }>("/admin/email/test", {
    token,
    method: "POST",
  });
}

export function reviewWorkspace(
  token: string,
  workspaceId: string,
  reviewStatus: WorkspaceReviewStatus,
  reviewNote?: string,
) {
  return apiRequest<Workspace>(`/admin/workspaces/${workspaceId}/review`, {
    token,
    method: "PATCH",
    body: {
      review_status: reviewStatus,
      ...(reviewNote?.trim() ? { review_note: reviewNote.trim() } : {}),
    },
  });
}

export function updateWorkspace(token: string, workspaceId: string, payload: {
  title?: string;
  description?: string;
  address_line?: string;
  city?: string;
  state?: string;
  photo_url?: string | null;
  daily_price?: string;
  status?: WorkspaceStatus;
  review_status?: WorkspaceReviewStatus;
  amenities?: Record<string, unknown>;
}) {
  return apiRequest<Workspace>(`/workspaces/${workspaceId}`, {
    token,
    method: "PATCH",
    body: payload,
  });
}

export function uploadWorkspacePhoto(token: string, workspaceId: string, file: File) {
  const body = new FormData();
  body.append("file", file);
  return apiFormRequest<Workspace>(`/workspaces/${workspaceId}/photo`, token, body);
}

export function listHostBookings(token: string, params: { limit?: number; offset?: number } = {}) {
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  return apiRequest<BookingPage>(`/bookings/host?limit=${limit}&offset=${offset}`, { token });
}

export function getHostRevenueSummary(token: string) {
  return apiRequest<HostRevenueSummary>("/bookings/host/revenue", { token });
}

export function listWorkspaceAvailability(workspaceId: string) {
  return apiRequest<AvailabilityRule[]>(`/workspaces/${workspaceId}/availability`);
}

export function replaceWorkspaceAvailability(token: string, workspaceId: string, rules: Array<{
  day_of_week: number;
  start_time: string;
  end_time: string;
}>) {
  return apiRequest<AvailabilityRule[]>(`/workspaces/${workspaceId}/availability`, {
    token,
    method: "PUT",
    body: { rules },
  });
}

export function replaceWorkspaceBlackoutDates(token: string, workspaceId: string, blackoutDates: Array<{
  blackout_date: string;
  reason?: string;
}>) {
  return apiRequest<BlackoutDate[]>(`/workspaces/${workspaceId}/blackout-dates`, {
    token,
    method: "PUT",
    body: { blackout_dates: blackoutDates },
  });
}
