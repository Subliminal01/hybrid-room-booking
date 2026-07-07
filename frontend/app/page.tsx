"use client";

import {
  Building2,
  CalendarPlus,
  History,
  KeyRound,
  LogIn,
  LogOut,
  MailCheck,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  Wallet,
} from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  AuditEvent,
  AvailabilityRule,
  Booking,
  BookingGroupReceipt,
  EmailStatus,
  HostRevenueSummary,
  Payment,
  PaymentProviderStatus,
  StorageStatus,
  TimeSlot,
  TokenResponse,
  User,
  Workspace,
  WorkspaceStatus,
  cancelBookingGroup,
  changePassword,
  confirmBookingGroupPayment,
  confirmEmailVerification,
  confirmPasswordReset,
  createBookingGroupCheckoutSession,
  createBooking,
  getAdminEmailStatus,
  getAdminPaymentProviderStatus,
  getAdminStorageStatus,
  getBookingGroupReceipt,
  createWorkspace,
  getHostRevenueSummary,
  listAdminBookings,
  listAdminPayments,
  listAdminUsers,
  listAuditEvents,
  listHostBookings,
  listMyWorkspaces,
  listMyBookings,
  listWorkspacesForReview,
  login,
  logoutSession,
  register,
  replaceWorkspaceAvailability,
  replaceWorkspaceBlackoutDates,
  requestEmailVerification,
  requestPasswordReset,
  refreshSession,
  reviewWorkspace,
  searchWorkspaces,
  sendAdminEmailTest,
  updateMe,
  updateWorkspace,
  uploadWorkspacePhoto,
} from "@/lib/api";

type AuthMode = "login" | "register";
type DashboardTab = "worker" | "host" | "admin";

type SlotDraft = {
  date: string;
  dateText: string;
  start: string;
  end: string;
};

type WorkspaceForm = {
  title: string;
  description: string;
  addressLine: string;
  city: string;
  state: string;
  photoUrl: string;
  photoFile: File | null;
  dailyPrice: string;
  amenities: string[];
  availabilityDays: number[];
  availabilityStart: string;
  availabilityEnd: string;
};

type ListingEditDraft = {
  title: string;
  description: string;
  addressLine: string;
  city: string;
  state: string;
  photoUrl: string;
  dailyPrice: string;
  amenities: string[];
};

type AvailabilityDraft = {
  days: number[];
  start: string;
  end: string;
};

type BlackoutDraftItem = {
  blackout_date: string;
  reason: string;
};

type BlackoutDraft = {
  nextDate: string;
  nextReason: string;
  items: BlackoutDraftItem[];
};

type PendingConfirmation =
  | {
      kind: "book";
      workspace: Workspace;
      idempotencyKey: string;
    }
  | {
      kind: "cancel";
      booking: Booking;
    };

type BookingGroupSummary = {
  booking_group_id: string;
  bookings: Booking[];
  firstBooking: Booking;
  dayCount: number;
  totalPrice: string;
  status: Booking["status"] | "mixed";
  payableBooking: Booking | null;
  cancellableBooking: Booking | null;
};

type RazorpayCheckoutOptions = {
  key: string;
  amount: number;
  currency: string;
  name: string;
  description: string;
  order_id: string;
  handler: () => void;
  prefill?: {
    name?: string;
    email?: string;
  };
  theme?: {
    color?: string;
  };
};

type RazorpayConstructor = new (options: RazorpayCheckoutOptions) => {
  open: () => void;
};

declare global {
  interface Window {
    Razorpay?: RazorpayConstructor;
  }
}

const initialWorkspaceForm: WorkspaceForm = {
  title: "",
  description: "",
  addressLine: "",
  city: "Bengaluru",
  state: "Karnataka",
  photoUrl: "",
  photoFile: null,
  dailyPrice: "",
  amenities: ["wifi", "desk"],
  availabilityDays: [0, 1, 2, 3, 4],
  availabilityStart: "09:00",
  availabilityEnd: "18:00",
};

const SESSION_STORAGE_KEY = "hybrid-stay-session";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const BOOKING_PAGE_SIZE = 10;
const AUDIT_PAGE_SIZE = 12;
const ADMIN_PAGE_SIZE = 8;
const DEFAULT_START_TIME = "09:00";
const DEFAULT_END_TIME = "18:00";
const MAX_WORKSPACE_PHOTO_BYTES = 5 * 1024 * 1024;
const ALLOWED_WORKSPACE_PHOTO_TYPES = ["image/jpeg", "image/png", "image/webp"];
const HOST_AMENITIES = [
  { key: "wifi", label: "Wi-Fi" },
  { key: "desk", label: "Desk" },
  { key: "ac", label: "AC" },
  { key: "power_backup", label: "Power backup" },
  { key: "private_bath", label: "Private bath" },
  { key: "parking", label: "Parking" },
];

function dashboardForRole(role: TokenResponse["user"]["role"]): DashboardTab {
  if (role === "admin") {
    return "admin";
  }
  if (role === "host") {
    return "host";
  }
  return "worker";
}

function amenitiesFromRecord(amenities: Record<string, unknown> = {}) {
  return Object.entries(amenities)
    .filter(([, value]) => Boolean(value))
    .map(([key]) => key);
}

function amenitiesToRecord(amenities: string[]) {
  return Object.fromEntries(amenities.map((amenity) => [amenity, true]));
}

function validateWorkspacePhotoFile(file: File) {
  if (!ALLOWED_WORKSPACE_PHOTO_TYPES.includes(file.type)) {
    return "Use a JPEG, PNG, or WebP image.";
  }
  if (file.size > MAX_WORKSPACE_PHOTO_BYTES) {
    return "Workspace photo must be 5 MB or smaller.";
  }
  return null;
}

function listingDraftFromWorkspace(workspace: Workspace): ListingEditDraft {
  return {
    title: workspace.title,
    description: workspace.description ?? "",
    addressLine: workspace.address_line,
    city: workspace.city,
    state: workspace.state ?? "",
    photoUrl: workspace.photo_url ?? "",
    dailyPrice: workspace.daily_price,
    amenities: amenitiesFromRecord(workspace.amenities),
  };
}

function loadRazorpayCheckout() {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Checkout is only available in the browser."));
  }
  if (window.Razorpay) {
    return Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    const existingScript = document.querySelector<HTMLScriptElement>(
      'script[src="https://checkout.razorpay.com/v1/checkout.js"]',
    );
    if (existingScript) {
      existingScript.addEventListener("load", () => resolve(), { once: true });
      existingScript.addEventListener("error", () => reject(new Error("Could not load Razorpay Checkout.")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Could not load Razorpay Checkout."));
    document.body.appendChild(script);
  });
}

function toDateInputValue(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fromDateInputValue(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

function toDisplayDate(value: string) {
  if (!value) {
    return "";
  }
  const [year, month, day] = value.split("-");
  return `${month}/${day}/${year}`;
}

function formatTypedDisplayDate(value: string) {
  const digits = value.replace(/\D/g, "").slice(0, 8);
  const month = digits.slice(0, 2);
  const day = digits.slice(2, 4);
  const year = digits.slice(4, 8);
  return [month, day, year].filter(Boolean).join("/");
}

function countDigitsBeforeCursor(value: string, cursor: number) {
  return value.slice(0, cursor).replace(/\D/g, "").length;
}

function cursorPositionForDigitCount(value: string, digitCount: number) {
  if (digitCount <= 0) {
    return 0;
  }
  let seenDigits = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (/\d/.test(value[index])) {
      seenDigits += 1;
      if (seenDigits === digitCount) {
        return index + 1;
      }
    }
  }
  return value.length;
}

function displayDateToIso(value: string) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value);
  if (!match) {
    return null;
  }
  const month = Number(match[1]);
  const day = Number(match[2]);
  const year = Number(match[3]);
  if (year < 1000 || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }
  const candidate = new Date(year, month - 1, day);
  if (
    candidate.getFullYear() !== year ||
    candidate.getMonth() !== month - 1 ||
    candidate.getDate() !== day
  ) {
    return null;
  }
  return toDateInputValue(candidate);
}

function addCalendarDays(date: Date, days: number) {
  const nextDate = new Date(date);
  nextDate.setDate(nextDate.getDate() + days);
  return nextDate;
}

function isWeekday(date: Date) {
  const day = date.getDay();
  return day >= 1 && day <= 5;
}

function nextMatchingDates(count: number, allowedJsDays?: number[]) {
  const dates: string[] = [];
  let cursor = new Date();
  while (dates.length < count) {
    const allowed =
      allowedJsDays === undefined
        ? isWeekday(cursor)
        : allowedJsDays.includes(cursor.getDay());
    if (allowed) {
      dates.push(toDateInputValue(cursor));
    }
    cursor = addCalendarDays(cursor, 1);
  }
  return dates;
}

function makeSlotsFromDates(dates: string[]): SlotDraft[] {
  return dates.map((date) => ({
    date,
    dateText: toDisplayDate(date),
    start: DEFAULT_START_TIME,
    end: DEFAULT_END_TIME,
  }));
}

function makeInitialSlots() {
  return makeSlotsFromDates(nextMatchingDates(3, [1, 3, 5]));
}

function toIsoSlot(slot: SlotDraft): TimeSlot {
  return {
    start_at: `${slot.date}T${slot.start}:00+05:30`,
    end_at: `${slot.date}T${slot.end}:00+05:30`,
  };
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatMoney(value: string, currency = "INR") {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(Number(value));
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
  }).format(new Date(value));
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function bookingDateRange(booking: Booking) {
  return `${formatDate(booking.start_at)} · ${formatTime(booking.start_at)}-${formatTime(
    booking.end_at,
  )}`;
}

function bookingGroupDateRange(bookings: Booking[]) {
  const ordered = [...bookings].sort(
    (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
  );
  const first = ordered[0];
  const last = ordered[ordered.length - 1];
  if (!first || !last) {
    return "No dates";
  }
  if (first.id === last.id) {
    return bookingDateRange(first);
  }
  return `${formatDate(first.start_at)}-${formatDate(last.start_at)} · ${ordered.length} days`;
}

function summarizeBookingGroup(bookings: Booking[]): BookingGroupSummary | null {
  const ordered = [...bookings].sort(
    (a, b) => new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
  );
  const firstBooking = ordered[0];
  if (!firstBooking) {
    return null;
  }
  const statuses = new Set(ordered.map((booking) => booking.status));
  return {
    booking_group_id: firstBooking.booking_group_id,
    bookings: ordered,
    firstBooking,
    dayCount: ordered.length,
    totalPrice: String(
      ordered.reduce((total, booking) => total + Number(booking.total_price), 0),
    ),
    status: statuses.size === 1 ? ordered[0].status : "mixed",
    payableBooking: ordered.find((booking) => booking.status === "pending") ?? null,
    cancellableBooking: ordered.find((booking) => booking.status !== "cancelled") ?? null,
  };
}

function workspaceInitials(title: string) {
  return title
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("");
}

function shortTime(value: string) {
  return value.slice(0, 5);
}

function shortId(value: string | null) {
  return value ? value.slice(0, 8) : "system";
}

function formatAuditAction(action: string) {
  return action
    .split("_")
    .map((part) => part[0]?.toUpperCase() + part.slice(1))
    .join(" ");
}

function summarizeAuditDetails(details: Record<string, unknown>) {
  const priorityKeys = [
    "title",
    "review_status",
    "previous_review_status",
    "review_note",
    "total_paid",
    "total_refunded",
    "booking_count",
    "refunded_payment_count",
  ];
  return priorityKeys
    .filter((key) => details[key] !== undefined)
    .map((key) => `${key.replaceAll("_", " ")}: ${String(details[key])}`)
    .join(" · ");
}

function makeBookingIdempotencyKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `booking-${crypto.randomUUID()}`;
  }
  return `booking-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function availabilitySummary(rules: AvailabilityRule[] = []) {
  if (rules.length === 0) {
    return "Open unless booked";
  }
  const days = [...new Set(rules.map((rule) => WEEKDAYS[rule.day_of_week]))].join(", ");
  const firstRule = rules[0];
  return `${days} · ${shortTime(firstRule.start_time)}-${shortTime(firstRule.end_time)}`;
}

function estimatedWorkspaceTotal(workspace: Workspace, selectedDays: number) {
  return workspace.estimated_total_price ?? String(Number(workspace.daily_price) * selectedDays);
}

function draftFromRules(rules: AvailabilityRule[] = []): AvailabilityDraft {
  if (rules.length === 0) {
    return { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" };
  }
  return {
    days: [...new Set(rules.map((rule) => rule.day_of_week))],
    start: shortTime(rules[0].start_time),
    end: shortTime(rules[0].end_time),
  };
}

function draftFromBlackoutDates(workspace: Workspace): BlackoutDraft {
  return {
    nextDate: "",
    nextReason: "",
    items: (workspace.blackout_dates ?? []).map((item) => ({
      blackout_date: item.blackout_date,
      reason: item.reason ?? "",
    })),
  };
}

export default function Home() {
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [activeTab, setActiveTab] = useState<DashboardTab>("worker");
  const [session, setSession] = useState<TokenResponse | null>(null);
  const [email, setEmail] = useState("worker@example.com");
  const [password, setPassword] = useState("strong-password");
  const [fullName, setFullName] = useState("Hybrid Worker");
  const [profileName, setProfileName] = useState("Hybrid Worker");
  const [profilePhone, setProfilePhone] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [verificationToken, setVerificationToken] = useState("");
  const [resetEmail, setResetEmail] = useState("worker@example.com");
  const [resetToken, setResetToken] = useState("");
  const [resetNewPassword, setResetNewPassword] = useState("");
  const [role, setRole] = useState<"worker" | "host">("worker");
  const [city, setCity] = useState("Bengaluru");
  const [minPrice, setMinPrice] = useState("0.00");
  const [maxPrice, setMaxPrice] = useState("1000.00");
  const [rotaLabel, setRotaLabel] = useState("Office rota");
  const [bookingNotes, setBookingNotes] = useState("");
  const [slots, setSlots] = useState<SlotDraft[]>(() => makeInitialSlots());
  const [results, setResults] = useState<Workspace[]>([]);
  const [myBookings, setMyBookings] = useState<Booking[]>([]);
  const [myBookingsTotal, setMyBookingsTotal] = useState(0);
  const [hostBookings, setHostBookings] = useState<Booking[]>([]);
  const [hostBookingsTotal, setHostBookingsTotal] = useState(0);
  const [hostRevenue, setHostRevenue] = useState<HostRevenueSummary | null>(null);
  const [hostWorkspaces, setHostWorkspaces] = useState<Workspace[]>([]);
  const [reviewWorkspaces, setReviewWorkspaces] = useState<Workspace[]>([]);
  const [reviewNotes, setReviewNotes] = useState<Record<string, string>>({});
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditEventsTotal, setAuditEventsTotal] = useState(0);
  const [adminUsers, setAdminUsers] = useState<User[]>([]);
  const [adminUsersTotal, setAdminUsersTotal] = useState(0);
  const [adminBookings, setAdminBookings] = useState<Booking[]>([]);
  const [adminBookingsTotal, setAdminBookingsTotal] = useState(0);
  const [adminPayments, setAdminPayments] = useState<Payment[]>([]);
  const [adminPaymentsTotal, setAdminPaymentsTotal] = useState(0);
  const [emailStatus, setEmailStatus] = useState<EmailStatus | null>(null);
  const [paymentProviderStatus, setPaymentProviderStatus] =
    useState<PaymentProviderStatus | null>(null);
  const [storageStatus, setStorageStatus] = useState<StorageStatus | null>(null);
  const [availabilityDrafts, setAvailabilityDrafts] = useState<Record<string, AvailabilityDraft>>({});
  const [blackoutDrafts, setBlackoutDrafts] = useState<Record<string, BlackoutDraft>>({});
  const [listingDrafts, setListingDrafts] = useState<Record<string, ListingEditDraft>>({});
  const [workspaceForm, setWorkspaceForm] = useState<WorkspaceForm>(initialWorkspaceForm);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<BookingGroupReceipt | null>(null);
  const [selectedBookingGroup, setSelectedBookingGroup] = useState<BookingGroupSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pendingDateCursor = useRef<{ index: number; position: number } | null>(null);

  const apiSlots = useMemo(() => slots.map(toIsoSlot), [slots]);
  const groupedMyBookings = useMemo(() => {
    const groups = new Map<string, Booking[]>();
    for (const booking of myBookings) {
      groups.set(booking.booking_group_id, [
        ...(groups.get(booking.booking_group_id) ?? []),
        booking,
      ]);
    }
    return [...groups.values()]
      .map(summarizeBookingGroup)
      .filter((group): group is BookingGroupSummary => Boolean(group))
      .sort(
        (a, b) =>
          new Date(b.firstBooking.start_at).getTime() -
          new Date(a.firstBooking.start_at).getTime(),
      );
  }, [myBookings]);
  const selectedDays = slots.length;
  const todayInput = useMemo(() => toDateInputValue(new Date()), []);
  const isHost = session?.user.role === "host";
  const isAdmin = session?.user.role === "admin";

  useEffect(() => {
    const storedSession = window.localStorage.getItem(SESSION_STORAGE_KEY);
    if (!storedSession) {
      return;
    }

    try {
      const parsedSession = JSON.parse(storedSession) as TokenResponse;
      if (!parsedSession.access_token || !parsedSession.user?.email) {
        window.localStorage.removeItem(SESSION_STORAGE_KEY);
        return;
      }
      setSession(parsedSession);
      setProfileName(parsedSession.user.full_name);
      setProfilePhone(parsedSession.user.phone_number ?? "");
      setActiveTab(dashboardForRole(parsedSession.user.role));
      void bootstrapSession(parsedSession);
    } catch {
      window.localStorage.removeItem(SESSION_STORAGE_KEY);
    }
  }, []);

  useEffect(() => {
    const cursor = pendingDateCursor.current;
    if (!cursor) {
      return;
    }
    pendingDateCursor.current = null;
    const input = document.getElementById(`date-${cursor.index}`) as HTMLInputElement | null;
    input?.setSelectionRange(cursor.position, cursor.position);
  }, [slots]);

  useEffect(() => {
    setAvailabilityDrafts((current) => {
      const next = { ...current };
      for (const workspace of hostWorkspaces) {
        if (!next[workspace.id]) {
          next[workspace.id] = draftFromRules(workspace.availability_rules);
        }
      }
      return next;
    });
  }, [hostWorkspaces]);

  useEffect(() => {
    setBlackoutDrafts((current) => {
      const next = { ...current };
      for (const workspace of hostWorkspaces) {
        if (!next[workspace.id]) {
          next[workspace.id] = draftFromBlackoutDates(workspace);
        }
      }
      return next;
    });
  }, [hostWorkspaces]);

  useEffect(() => {
    setListingDrafts((current) => {
      const next = { ...current };
      for (const workspace of hostWorkspaces) {
        if (!next[workspace.id]) {
          next[workspace.id] = listingDraftFromWorkspace(workspace);
        }
      }
      return next;
    });
  }, [hostWorkspaces]);

  async function runAction(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function bootstrapSession(currentSession: TokenResponse) {
    try {
      const personal = await listMyBookings(currentSession.access_token, {
        limit: BOOKING_PAGE_SIZE,
      });
      setMyBookings(personal.items);
      setMyBookingsTotal(personal.total);
      if (currentSession.user.role === "host") {
        const [workspaces, bookings, revenue] = await Promise.all([
          listMyWorkspaces(currentSession.access_token),
          listHostBookings(currentSession.access_token, { limit: BOOKING_PAGE_SIZE }),
          getHostRevenueSummary(currentSession.access_token),
        ]);
        setHostWorkspaces(workspaces);
        setHostBookings(bookings.items);
        setHostBookingsTotal(bookings.total);
        setHostRevenue(revenue);
      }
      if (currentSession.user.role === "admin") {
        const [
          reviewQueue,
          auditPage,
          usersPage,
          bookingsPage,
          paymentsPage,
          nextEmailStatus,
          providerStatus,
          nextStorageStatus,
        ] = await Promise.all([
          listWorkspacesForReview(currentSession.access_token, "pending"),
          listAuditEvents(currentSession.access_token, { limit: AUDIT_PAGE_SIZE }),
          listAdminUsers(currentSession.access_token, { limit: ADMIN_PAGE_SIZE }),
          listAdminBookings(currentSession.access_token, { limit: ADMIN_PAGE_SIZE }),
          listAdminPayments(currentSession.access_token, { limit: ADMIN_PAGE_SIZE }),
          getAdminEmailStatus(currentSession.access_token),
          getAdminPaymentProviderStatus(currentSession.access_token),
          getAdminStorageStatus(currentSession.access_token),
        ]);
        setReviewWorkspaces(reviewQueue);
        setAuditEvents(auditPage.items);
        setAuditEventsTotal(auditPage.total);
        setAdminUsers(usersPage.items);
        setAdminUsersTotal(usersPage.total);
        setAdminBookings(bookingsPage.items);
        setAdminBookingsTotal(bookingsPage.total);
        setAdminPayments(paymentsPage.items);
        setAdminPaymentsTotal(paymentsPage.total);
        setEmailStatus(nextEmailStatus);
        setPaymentProviderStatus(providerStatus);
        setStorageStatus(nextStorageStatus);
      }
    } catch {
      if (currentSession.refresh_token) {
        try {
          const refreshedSession = await refreshSession(currentSession.refresh_token);
          persistSession(refreshedSession);
          await bootstrapSession(refreshedSession);
          return;
        } catch {
          // Fall through to clear an invalid saved session.
        }
      }
      clearSessionState();
      setError("Your saved session expired. Please sign in again.");
    }
  }

  function persistSession(nextSession: TokenResponse) {
    setSession(nextSession);
    setProfileName(nextSession.user.full_name);
    setProfilePhone(nextSession.user.phone_number ?? "");
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(nextSession));
    setActiveTab(dashboardForRole(nextSession.user.role));
  }

  function clearSessionState() {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    setSession(null);
    setProfileName("Hybrid Worker");
    setProfilePhone("");
    setCurrentPassword("");
    setNewPassword("");
    setVerificationToken("");
    setResetToken("");
    setResetNewPassword("");
    setMyBookings([]);
    setMyBookingsTotal(0);
    setSelectedBookingGroup(null);
    setSelectedReceipt(null);
    setHostBookings([]);
    setHostBookingsTotal(0);
    setHostRevenue(null);
    setHostWorkspaces([]);
    setReviewWorkspaces([]);
    setReviewNotes({});
    setAuditEvents([]);
    setAuditEventsTotal(0);
    setAdminUsers([]);
    setAdminUsersTotal(0);
    setAdminBookings([]);
    setAdminBookingsTotal(0);
    setAdminPayments([]);
    setAdminPaymentsTotal(0);
    setEmailStatus(null);
    setPaymentProviderStatus(null);
    setStorageStatus(null);
    setListingDrafts({});
    setResults([]);
    setActiveTab("worker");
  }

  async function signOut() {
    const refreshToken = session?.refresh_token;
    clearSessionState();
    setMessage("Signed out.");
    if (refreshToken) {
      try {
        await logoutSession(refreshToken);
      } catch {
        // Local sign-out should still succeed even if the network request fails.
      }
    }
  }

  async function handleAuth(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }
    if (authMode === "register" && !fullName.trim()) {
      setError("Name is required to create an account.");
      return;
    }
    await runAction(async () => {
      const response =
        authMode === "login"
          ? await login({ email, password })
          : await register({
              email,
              password,
              full_name: fullName,
              role,
            });
      persistSession(response);
      setMessage(`Signed in as ${response.user.email}`);
      if (response.user.role === "host") {
        const [workspaces, bookings, revenue] = await Promise.all([
          listMyWorkspaces(response.access_token),
          listHostBookings(response.access_token, { limit: BOOKING_PAGE_SIZE }),
          getHostRevenueSummary(response.access_token),
        ]);
        setHostWorkspaces(workspaces);
        setHostBookings(bookings.items);
        setHostBookingsTotal(bookings.total);
        setHostRevenue(revenue);
      }
      if (response.user.role === "admin") {
        const [
          reviewQueue,
          auditPage,
          usersPage,
          bookingsPage,
          paymentsPage,
          nextEmailStatus,
          providerStatus,
          nextStorageStatus,
        ] = await Promise.all([
          listWorkspacesForReview(response.access_token, "pending"),
          listAuditEvents(response.access_token, { limit: AUDIT_PAGE_SIZE }),
          listAdminUsers(response.access_token, { limit: ADMIN_PAGE_SIZE }),
          listAdminBookings(response.access_token, { limit: ADMIN_PAGE_SIZE }),
          listAdminPayments(response.access_token, { limit: ADMIN_PAGE_SIZE }),
          getAdminEmailStatus(response.access_token),
          getAdminPaymentProviderStatus(response.access_token),
          getAdminStorageStatus(response.access_token),
        ]);
        setReviewWorkspaces(reviewQueue);
        setAuditEvents(auditPage.items);
        setAuditEventsTotal(auditPage.total);
        setAdminUsers(usersPage.items);
        setAdminUsersTotal(usersPage.total);
        setAdminBookings(bookingsPage.items);
        setAdminBookingsTotal(bookingsPage.total);
        setAdminPayments(paymentsPage.items);
        setAdminPaymentsTotal(paymentsPage.total);
        setEmailStatus(nextEmailStatus);
        setPaymentProviderStatus(providerStatus);
        setStorageStatus(nextStorageStatus);
      }
    });
  }

  async function handleProfileUpdate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    if (!profileName.trim()) {
      setError("Name is required.");
      return;
    }
    await runAction(async () => {
      const updatedUser = await updateMe(session.access_token, {
        full_name: profileName,
        phone_number: profilePhone.trim() || null,
      });
      const nextSession = { ...session, user: updatedUser };
      persistSession(nextSession);
      setMessage("Profile updated.");
    });
  }

  async function handlePasswordChange(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    if (!currentPassword || !newPassword) {
      setError("Current password and new password are required.");
      return;
    }
    await runAction(async () => {
      await changePassword(session.access_token, {
        current_password: currentPassword,
        new_password: newPassword,
      });
      setCurrentPassword("");
      setNewPassword("");
      setMessage("Password updated.");
    });
  }

  async function handleRequestEmailVerification() {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const response = await requestEmailVerification(session.access_token);
      setVerificationToken(response.verification_token ?? "");
      setMessage(
        response.verification_token
          ? "Verification token issued."
          : "Verification instructions sent if email delivery is configured.",
      );
    });
  }

  async function handleConfirmEmailVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session) {
      return;
    }
    if (!verificationToken.trim()) {
      setError("Verification token is required.");
      return;
    }
    await runAction(async () => {
      const updatedUser = await confirmEmailVerification(verificationToken.trim());
      const nextSession = { ...session, user: updatedUser };
      persistSession(nextSession);
      setVerificationToken("");
      setMessage("Email verified.");
    });
  }

  async function handleRequestPasswordReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetEmail.trim()) {
      setError("Email is required.");
      return;
    }
    await runAction(async () => {
      const response = await requestPasswordReset(resetEmail);
      setResetToken(response.reset_token ?? "");
      setMessage(
        response.reset_token
          ? "Password reset token issued if the email exists."
          : "Password reset instructions sent if the email exists.",
      );
    });
  }

  async function handleConfirmPasswordReset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!resetToken.trim() || !resetNewPassword) {
      setError("Reset token and new password are required.");
      return;
    }
    await runAction(async () => {
      await confirmPasswordReset({
        token: resetToken.trim(),
        new_password: resetNewPassword,
      });
      setPassword(resetNewPassword);
      setResetToken("");
      setResetNewPassword("");
      setAuthMode("login");
      setMessage("Password reset. You can log in with the new password.");
    });
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validationError = validateSearchForm();
    if (validationError) {
      setError(validationError);
      return;
    }
    await runAction(async () => {
      const response = await searchWorkspaces({
        city,
        min_daily_price: minPrice,
        max_daily_price: maxPrice,
        slots: apiSlots,
      });
      setResults(response);
      setMessage(`Found ${response.length} available workspace${response.length === 1 ? "" : "s"}.`);
    });
  }

  async function handleBook(workspace: Workspace) {
    if (!session) {
      setError("Sign in before booking.");
      return;
    }
    setPendingConfirmation({
      kind: "book",
      workspace,
      idempotencyKey: makeBookingIdempotencyKey(),
    });
  }

  async function confirmBook(workspace: Workspace, idempotencyKey: string) {
    if (!session) {
      setError("Sign in before booking.");
      return;
    }
    setPendingConfirmation(null);
    await runAction(async () => {
      await createBooking(session.access_token, {
        workspace_id: workspace.id,
        slots: apiSlots,
        rota_label: rotaLabel.trim() || `${city} office rota`,
        notes: bookingNotes.trim() || undefined,
      }, {
        idempotencyKey,
      });
      setMessage("Booking reserved. Complete payment from your booking history.");
      await refreshBookings(session.access_token);
      setResults((current) => current.filter((item) => item.id !== workspace.id));
    });
  }

  async function handlePayBooking(booking: Booking) {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const checkoutSession = await createBookingGroupCheckoutSession(
        session.access_token,
        booking.booking_group_id,
      );
      if (checkoutSession.provider === "razorpay") {
        const payload = checkoutSession.checkout_payload;
        const orderId = typeof payload.order_id === "string" ? payload.order_id : "";
        const keyId = typeof payload.key_id === "string" ? payload.key_id : "";
        const amount = typeof payload.amount === "number" ? payload.amount : Number(payload.amount);
        const currency = typeof payload.currency === "string" ? payload.currency : checkoutSession.currency;
        if (!orderId || !keyId || Number.isNaN(amount)) {
          throw new Error("Razorpay checkout details are incomplete.");
        }
        await loadRazorpayCheckout();
        const Razorpay = window.Razorpay;
        if (!Razorpay) {
          throw new Error("Razorpay Checkout is unavailable.");
        }
        const checkout = new Razorpay({
          key: keyId,
          amount,
          currency,
          name: "Hybrid Stay Booking",
          description: `${checkoutSession.payments.length} rota day${
            checkoutSession.payments.length === 1 ? "" : "s"
          }`,
          order_id: orderId,
          prefill: {
            name: session.user.full_name,
            email: session.user.email,
          },
          theme: {
            color: "#147d64",
          },
          handler: () => {
            setMessage("Payment submitted. Your booking will confirm after Razorpay sends the webhook.");
            void refreshBookings(session.access_token);
          },
        });
        checkout.open();
        return;
      }
      if (checkoutSession.provider !== "mock") {
        setMessage(
          `Checkout started with ${checkoutSession.provider}. Payment will confirm after the provider webhook completes.`,
        );
        window.location.assign(checkoutSession.checkout_url);
        return;
      }
      const checkout = await confirmBookingGroupPayment(
        session.access_token,
        booking.booking_group_id,
      );
      await refreshBookings(session.access_token);
      setMessage(
        `Paid ${formatMoney(
          checkout.total_paid,
          checkoutSession.currency,
        )} for ${checkout.bookings.length} rota day${
          checkout.bookings.length === 1 ? "" : "s"
        } via ${checkoutSession.provider} checkout ${checkoutSession.checkout_reference.slice(0, 17)}.`,
      );
    });
  }

  async function refreshBookings(token = session?.access_token) {
    if (!token) {
      return;
    }
    const personal = await listMyBookings(token, { limit: BOOKING_PAGE_SIZE });
    setMyBookings(personal.items);
    setMyBookingsTotal(personal.total);
    if (isHost) {
      const [hostPage, revenue] = await Promise.all([
        listHostBookings(token, { limit: BOOKING_PAGE_SIZE }),
        getHostRevenueSummary(token),
      ]);
      setHostBookings(hostPage.items);
      setHostBookingsTotal(hostPage.total);
      setHostRevenue(revenue);
    }
  }

  async function loadMoreMyBookings() {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const page = await listMyBookings(session.access_token, {
        limit: BOOKING_PAGE_SIZE,
        offset: myBookings.length,
      });
      setMyBookings((current) => [...current, ...page.items]);
      setMyBookingsTotal(page.total);
    });
  }

  async function loadMoreHostBookings() {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const page = await listHostBookings(session.access_token, {
        limit: BOOKING_PAGE_SIZE,
        offset: hostBookings.length,
      });
      setHostBookings((current) => [...current, ...page.items]);
      setHostBookingsTotal(page.total);
      setHostRevenue(await getHostRevenueSummary(session.access_token));
    });
  }

  async function refreshHostWorkspaces(token = session?.access_token) {
    if (!token || !isHost) {
      return;
    }
    const [workspaces, revenue] = await Promise.all([
      listMyWorkspaces(token),
      getHostRevenueSummary(token),
    ]);
    setHostWorkspaces(workspaces);
    setHostRevenue(revenue);
  }

  async function refreshReviewWorkspaces(token = session?.access_token) {
    if (!token || !isAdmin) {
      return;
    }
    setReviewWorkspaces(await listWorkspacesForReview(token, "pending"));
  }

  async function refreshAuditEvents(token = session?.access_token) {
    if (!token || !isAdmin) {
      return;
    }
    const page = await listAuditEvents(token, { limit: AUDIT_PAGE_SIZE });
    setAuditEvents(page.items);
    setAuditEventsTotal(page.total);
  }

  async function refreshAdminOperations(token = session?.access_token) {
    if (!token || !isAdmin) {
      return;
    }
    const [
      usersPage,
      bookingsPage,
      paymentsPage,
      nextEmailStatus,
      providerStatus,
      nextStorageStatus,
    ] = await Promise.all([
        listAdminUsers(token, { limit: ADMIN_PAGE_SIZE }),
        listAdminBookings(token, { limit: ADMIN_PAGE_SIZE }),
        listAdminPayments(token, { limit: ADMIN_PAGE_SIZE }),
        getAdminEmailStatus(token),
        getAdminPaymentProviderStatus(token),
        getAdminStorageStatus(token),
      ]);
    setAdminUsers(usersPage.items);
    setAdminUsersTotal(usersPage.total);
    setAdminBookings(bookingsPage.items);
    setAdminBookingsTotal(bookingsPage.total);
    setAdminPayments(paymentsPage.items);
    setAdminPaymentsTotal(paymentsPage.total);
    setEmailStatus(nextEmailStatus);
    setPaymentProviderStatus(providerStatus);
    setStorageStatus(nextStorageStatus);
  }

  async function loadMoreAdminUsers() {
    if (!session || !isAdmin) {
      return;
    }
    await runAction(async () => {
      const page = await listAdminUsers(session.access_token, {
        limit: ADMIN_PAGE_SIZE,
        offset: adminUsers.length,
      });
      setAdminUsers((current) => [...current, ...page.items]);
      setAdminUsersTotal(page.total);
    });
  }

  async function loadMoreAdminBookings() {
    if (!session || !isAdmin) {
      return;
    }
    await runAction(async () => {
      const page = await listAdminBookings(session.access_token, {
        limit: ADMIN_PAGE_SIZE,
        offset: adminBookings.length,
      });
      setAdminBookings((current) => [...current, ...page.items]);
      setAdminBookingsTotal(page.total);
    });
  }

  async function loadMoreAdminPayments() {
    if (!session || !isAdmin) {
      return;
    }
    await runAction(async () => {
      const page = await listAdminPayments(session.access_token, {
        limit: ADMIN_PAGE_SIZE,
        offset: adminPayments.length,
      });
      setAdminPayments((current) => [...current, ...page.items]);
      setAdminPaymentsTotal(page.total);
    });
  }

  async function loadMoreAuditEvents() {
    if (!session || !isAdmin) {
      return;
    }
    await runAction(async () => {
      const page = await listAuditEvents(session.access_token, {
        limit: AUDIT_PAGE_SIZE,
        offset: auditEvents.length,
      });
      setAuditEvents((current) => [...current, ...page.items]);
      setAuditEventsTotal(page.total);
    });
  }

  async function handleReviewWorkspace(workspace: Workspace, reviewStatus: "approved" | "rejected") {
    if (!session || !isAdmin) {
      return;
    }
    await runAction(async () => {
      const reviewNote = reviewNotes[workspace.id]?.trim();
      const reviewed = await reviewWorkspace(session.access_token, workspace.id, reviewStatus, reviewNote);
      setReviewWorkspaces((current) => current.filter((item) => item.id !== reviewed.id));
      setReviewNotes((current) => {
        const next = { ...current };
        delete next[workspace.id];
        return next;
      });
      await refreshAuditEvents(session.access_token);
      setMessage(`${reviewed.title} marked ${reviewed.review_status}.`);
    });
  }

  async function handleCancel(booking: Booking) {
    if (!session) {
      return;
    }
    setPendingConfirmation({ kind: "cancel", booking });
  }

  async function handleViewReceipt(group: BookingGroupSummary) {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const receipt = await getBookingGroupReceipt(session.access_token, group.booking_group_id);
      setSelectedReceipt(receipt);
      setMessage("Receipt loaded.");
    });
  }

  async function confirmCancel(booking: Booking) {
    if (!session) {
      return;
    }
    setPendingConfirmation(null);
    await runAction(async () => {
      const cancelled = await cancelBookingGroup(session.access_token, booking.booking_group_id);
      await refreshBookings(session.access_token);
      setSelectedBookingGroup(null);
      setMessage(
        `Cancelled ${cancelled.bookings.length} rota day${
          cancelled.bookings.length === 1 ? "" : "s"
        }${
          Number(cancelled.total_refunded) > 0
            ? ` and refunded ${formatMoney(cancelled.total_refunded)}`
            : ""
        }.`,
      );
    });
  }

  async function handleCreateWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || session.user.role === "worker") {
      return;
    }
    if (!workspaceForm.title.trim() || !workspaceForm.addressLine.trim() || !workspaceForm.city.trim()) {
      setError("Workspace title, address, and city are required.");
      return;
    }
    if (Number(workspaceForm.dailyPrice) <= 0 || Number.isNaN(Number(workspaceForm.dailyPrice))) {
      setError("Daily price must be greater than zero.");
      return;
    }
    if (workspaceForm.availabilityDays.length === 0) {
      setError("Choose at least one available weekday.");
      return;
    }
    if (workspaceForm.availabilityEnd <= workspaceForm.availabilityStart) {
      setError("Availability end time must be after start time.");
      return;
    }
    await runAction(async () => {
      const amenities = Object.fromEntries(
        workspaceForm.amenities
          .map((amenity) => [amenity, true]),
      );
      const created = await createWorkspace(session.access_token, {
        title: workspaceForm.title.trim(),
        description: workspaceForm.description.trim() || undefined,
        address_line: workspaceForm.addressLine.trim(),
        city: workspaceForm.city.trim(),
        state: workspaceForm.state.trim() || undefined,
        photo_url: workspaceForm.photoUrl.trim() || undefined,
        daily_price: workspaceForm.dailyPrice.trim(),
        amenities,
      });
      const workspaceWithPhoto = workspaceForm.photoFile
        ? await uploadWorkspacePhoto(session.access_token, created.id, workspaceForm.photoFile)
        : created;
      const rules = await replaceWorkspaceAvailability(
        session.access_token,
        created.id,
        workspaceForm.availabilityDays.map((day) => ({
          day_of_week: day,
          start_time: workspaceForm.availabilityStart,
          end_time: workspaceForm.availabilityEnd,
        })),
      );
      const createdWithAvailability = { ...workspaceWithPhoto, availability_rules: rules };
      setHostWorkspaces((current) => [createdWithAvailability, ...current]);
      setAvailabilityDrafts((current) => ({
        ...current,
        [created.id]: draftFromRules(rules),
      }));
      setBlackoutDrafts((current) => ({
        ...current,
        [created.id]: draftFromBlackoutDates(created),
      }));
      setWorkspaceForm(initialWorkspaceForm);
      setMessage(`${workspaceWithPhoto.title} was submitted for admin review.`);
    });
  }

  function toggleWorkspaceFormAmenity(amenity: string) {
    setWorkspaceForm((current) => ({
      ...current,
      amenities: current.amenities.includes(amenity)
        ? current.amenities.filter((item) => item !== amenity)
        : [...current.amenities, amenity],
    }));
  }

  function handleNewWorkspacePhoto(file: File | null) {
    if (!file) {
      setWorkspaceForm((current) => ({ ...current, photoFile: null }));
      return;
    }
    const validationError = validateWorkspacePhotoFile(file);
    if (validationError) {
      setError(validationError);
      setWorkspaceForm((current) => ({ ...current, photoFile: null }));
      return;
    }
    setError(null);
    setWorkspaceForm((current) => ({ ...current, photoFile: file, photoUrl: "" }));
  }

  async function handleListingPhotoUpload(workspace: Workspace, file: File | null) {
    if (!session || !file) {
      return;
    }
    const validationError = validateWorkspacePhotoFile(file);
    if (validationError) {
      setError(validationError);
      return;
    }
    await runAction(async () => {
      const updated = await uploadWorkspacePhoto(session.access_token, workspace.id, file);
      const merged = {
        ...workspace,
        ...updated,
        availability_rules: updated.availability_rules ?? workspace.availability_rules,
        blackout_dates: updated.blackout_dates ?? workspace.blackout_dates,
      };
      setHostWorkspaces((current) =>
        current.map((item) => (item.id === workspace.id ? merged : item)),
      );
      setListingDrafts((current) => ({
        ...current,
        [workspace.id]: listingDraftFromWorkspace(merged),
      }));
      setMessage(`${workspace.title} photo updated.`);
    });
  }

  function toggleWorkspaceFormDay(day: number) {
    setWorkspaceForm((current) => ({
      ...current,
      availabilityDays: current.availabilityDays.includes(day)
        ? current.availabilityDays.filter((selectedDay) => selectedDay !== day)
        : [...current.availabilityDays, day].sort(),
    }));
  }

  function updateListingDraft(workspaceId: string, patch: Partial<ListingEditDraft>) {
    setListingDrafts((current) => {
      const baseDraft = current[workspaceId];
      const workspace = hostWorkspaces.find((item) => item.id === workspaceId);
      if (!baseDraft && !workspace) {
        return current;
      }
      const nextDraft = baseDraft ?? listingDraftFromWorkspace(workspace!);
      return {
        ...current,
        [workspaceId]: {
          ...nextDraft,
          ...patch,
        },
      };
    });
  }

  function toggleListingDraftAmenity(workspace: Workspace, amenity: string) {
    const draft = listingDrafts[workspace.id] ?? listingDraftFromWorkspace(workspace);
    updateListingDraft(workspace.id, {
      amenities: draft.amenities.includes(amenity)
        ? draft.amenities.filter((item) => item !== amenity)
        : [...draft.amenities, amenity],
    });
  }

  async function handleSaveListingDetails(workspace: Workspace) {
    if (!session) {
      return;
    }
    const draft = listingDrafts[workspace.id] ?? listingDraftFromWorkspace(workspace);
    if (!draft.title.trim() || !draft.addressLine.trim() || !draft.city.trim()) {
      setError("Workspace title, address, and city are required.");
      return;
    }
    if (Number(draft.dailyPrice) <= 0 || Number.isNaN(Number(draft.dailyPrice))) {
      setError("Daily price must be greater than zero.");
      return;
    }
    await runAction(async () => {
      const updated = await updateWorkspace(session.access_token, workspace.id, {
        title: draft.title.trim(),
        description: draft.description.trim() || undefined,
        address_line: draft.addressLine.trim(),
        city: draft.city.trim(),
        state: draft.state.trim() || undefined,
        photo_url: draft.photoUrl.trim() || null,
        daily_price: draft.dailyPrice.trim(),
        amenities: amenitiesToRecord(draft.amenities),
      });
      const merged = {
        ...workspace,
        ...updated,
        availability_rules: updated.availability_rules ?? workspace.availability_rules,
        blackout_dates: updated.blackout_dates ?? workspace.blackout_dates,
      };
      setHostWorkspaces((current) =>
        current.map((item) => (item.id === workspace.id ? merged : item)),
      );
      setListingDrafts((current) => ({
        ...current,
        [workspace.id]: listingDraftFromWorkspace(merged),
      }));
      setMessage(`${updated.title} details updated.`);
    });
  }

  async function handleWorkspaceStatus(workspace: Workspace, statusValue: WorkspaceStatus) {
    if (!session) {
      return;
    }
    await runAction(async () => {
      const updated = await updateWorkspace(session.access_token, workspace.id, {
        status: statusValue,
      });
      setHostWorkspaces((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      setMessage(`${updated.title} is now ${updated.status}.`);
    });
  }

  function updateSlot(index: number, patch: Partial<SlotDraft>) {
    setSlots((current) =>
      current.map((slot, slotIndex) =>
        slotIndex === index ? { ...slot, ...patch } : slot,
      ),
    );
  }

  function updateSlotDateText(index: number, value: string, cursorPosition: number | null) {
    const dateText = formatTypedDisplayDate(value);
    if (cursorPosition !== null) {
      pendingDateCursor.current = {
        index,
        position: cursorPositionForDigitCount(
          dateText,
          countDigitsBeforeCursor(value, cursorPosition),
        ),
      };
    }
    const parsedDate = displayDateToIso(dateText);
    updateSlot(index, {
      dateText,
      ...(parsedDate ? { date: parsedDate } : {}),
    });
  }

  function updateSlotDateFromPicker(index: number, value: string) {
    updateSlot(index, {
      date: value,
      dateText: toDisplayDate(value),
    });
  }

  function openDatePicker(index: number) {
    const picker = document.getElementById(`date-picker-${index}`) as HTMLInputElement | null;
    if (!picker) {
      return;
    }
    if (typeof picker.showPicker === "function") {
      picker.showPicker();
      return;
    }
    picker.click();
  }

  function applyRotaPreset(dates: string[], label: string) {
    setSlots(makeSlotsFromDates(dates));
    setRotaLabel(label);
  }

  function addNextRotaDay() {
    setSlots((current) => {
      const lastDateValue = current[current.length - 1]?.date;
      const startingDate = lastDateValue ? fromDateInputValue(lastDateValue) : new Date();
      let candidate = addCalendarDays(startingDate, 1);
      while (!isWeekday(candidate)) {
        candidate = addCalendarDays(candidate, 1);
      }
      return [
        ...current,
        {
          date: toDateInputValue(candidate),
          dateText: toDisplayDate(toDateInputValue(candidate)),
          start: current[current.length - 1]?.start ?? DEFAULT_START_TIME,
          end: current[current.length - 1]?.end ?? DEFAULT_END_TIME,
        },
      ];
    });
  }

  function removeSlot(index: number) {
    setSlots((current) => {
      return current.filter((_, slotIndex) => slotIndex !== index);
    });
  }

  function updateAvailabilityDraft(workspaceId: string, patch: Partial<AvailabilityDraft>) {
    setAvailabilityDrafts((current) => ({
      ...current,
      [workspaceId]: {
        ...(current[workspaceId] ?? { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" }),
        ...patch,
      },
    }));
  }

  function toggleAvailabilityDay(workspaceId: string, day: number) {
    const draft = availabilityDrafts[workspaceId] ?? {
      days: [0, 1, 2, 3, 4],
      start: "09:00",
      end: "18:00",
    };
    const days = draft.days.includes(day)
      ? draft.days.filter((selectedDay) => selectedDay !== day)
      : [...draft.days, day].sort();
    updateAvailabilityDraft(workspaceId, { days });
  }

  async function handleSaveAvailability(workspace: Workspace) {
    if (!session) {
      return;
    }
    const draft = availabilityDrafts[workspace.id] ?? draftFromRules(workspace.availability_rules);
    if (draft.days.length === 0) {
      setError("Choose at least one available weekday.");
      return;
    }
    if (draft.end <= draft.start) {
      setError("Availability end time must be after start time.");
      return;
    }
    await runAction(async () => {
      const rules = await replaceWorkspaceAvailability(
        session.access_token,
        workspace.id,
        draft.days.map((day) => ({
          day_of_week: day,
          start_time: draft.start,
          end_time: draft.end,
        })),
      );
      setHostWorkspaces((current) =>
        current.map((item) =>
          item.id === workspace.id ? { ...item, availability_rules: rules } : item,
        ),
      );
      setMessage(`Updated availability for ${workspace.title}.`);
    });
  }

  function updateBlackoutDraft(workspaceId: string, patch: Partial<BlackoutDraft>) {
    setBlackoutDrafts((current) => ({
      ...current,
      [workspaceId]: {
        ...(current[workspaceId] ?? { nextDate: "", nextReason: "", items: [] }),
        ...patch,
      },
    }));
  }

  function addBlackoutDraftItem(workspaceId: string) {
    const draft = blackoutDrafts[workspaceId] ?? { nextDate: "", nextReason: "", items: [] };
    if (!draft.nextDate) {
      setError("Choose a blocked date first.");
      return;
    }
    const existingIndex = draft.items.findIndex((item) => item.blackout_date === draft.nextDate);
    const nextItem = { blackout_date: draft.nextDate, reason: draft.nextReason };
    const items =
      existingIndex >= 0
        ? draft.items.map((item, index) => (index === existingIndex ? nextItem : item))
        : [...draft.items, nextItem].sort((a, b) => a.blackout_date.localeCompare(b.blackout_date));
    updateBlackoutDraft(workspaceId, { nextDate: "", nextReason: "", items });
  }

  function removeBlackoutDraftItem(workspaceId: string, blackoutDate: string) {
    const draft = blackoutDrafts[workspaceId] ?? { nextDate: "", nextReason: "", items: [] };
    updateBlackoutDraft(workspaceId, {
      items: draft.items.filter((item) => item.blackout_date !== blackoutDate),
    });
  }

  async function handleSaveBlackoutDates(workspace: Workspace) {
    if (!session) {
      return;
    }
    const draft = blackoutDrafts[workspace.id] ?? draftFromBlackoutDates(workspace);
    await runAction(async () => {
      const blackoutDates = await replaceWorkspaceBlackoutDates(
        session.access_token,
        workspace.id,
        draft.items,
      );
      setHostWorkspaces((current) =>
        current.map((item) =>
          item.id === workspace.id ? { ...item, blackout_dates: blackoutDates } : item,
        ),
      );
      setMessage(`Updated blocked dates for ${workspace.title}.`);
    });
  }

  function validateSearchForm() {
    if (!city.trim()) {
      return "City is required.";
    }
    if (Number(maxPrice) <= 0 || Number.isNaN(Number(maxPrice))) {
      return "Max daily price must be greater than zero.";
    }
    if (Number(minPrice) < 0 || Number.isNaN(Number(minPrice))) {
      return "Min daily price cannot be negative.";
    }
    if (Number(minPrice) > Number(maxPrice)) {
      return "Min daily price cannot be higher than max daily price.";
    }
    if (slots.length === 0) {
      return "Add at least one rota day before searching.";
    }
    for (const slot of slots) {
      const parsedDate = displayDateToIso(slot.dateText);
      if (!slot.dateText || !parsedDate || !slot.start || !slot.end) {
        return "Each rota day needs a date, start time, and end time.";
      }
      if (parsedDate < todayInput) {
        return "Rota dates cannot be in the past.";
      }
      const start = new Date(`${slot.date}T${slot.start}:00+05:30`);
      const end = new Date(`${slot.date}T${slot.end}:00+05:30`);
      if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
        return "One of the selected rota days is invalid.";
      }
      if (end <= start) {
        return "End time must be after start time for every rota day.";
      }
    }
    return null;
  }

  function confirmationTitle() {
    if (!pendingConfirmation) {
      return "";
    }
    return pendingConfirmation.kind === "book"
      ? "Confirm booking"
      : "Cancel booking";
  }

  function confirmationBody() {
    if (!pendingConfirmation) {
      return "";
    }
    if (pendingConfirmation.kind === "book") {
      const { workspace } = pendingConfirmation;
      return `Book ${workspace.title} for ${selectedDays} selected day${
        selectedDays === 1 ? "" : "s"
      } at an estimated total of ${formatMoney(
        estimatedWorkspaceTotal(workspace, selectedDays),
        workspace.currency,
      )}?`;
    }
    return `Cancel this rota group starting ${bookingDateRange(
      pendingConfirmation.booking,
    )}? Paid days in the group will be refunded.`;
  }

  function confirmationPolicy() {
    if (!pendingConfirmation) {
      return "";
    }
    if (pendingConfirmation.kind === "book") {
      return "A room is held after booking creation. Payment must be completed before the hold expires. Confirmed bookings can be cancelled from booking history; eligible paid days are refunded through the original payment provider.";
    }
    return "Cancelling applies to the whole rota group. Refund timing depends on the payment provider and bank processing timelines.";
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <strong>Hybrid Stay Booking</strong>
          <span>Affordable workday rooms for office rota schedules</span>
        </div>
        <div className="session">
          {session ? (
            <>
              <div className="session-meta">
                {session.user.full_name} · {session.user.role}
              </div>
              <button
                className="btn secondary"
                type="button"
                onClick={() => void signOut()}
              >
                <LogOut size={16} />
                Sign out
              </button>
            </>
          ) : (
            <span className="session-meta">Not signed in</span>
          )}
        </div>
      </header>

      <div className="content">
        <aside className="stack">
          {!session ? (
          <section className="panel">
            <div className="panel-header">
              <h2>Account</h2>
              <LogIn size={18} />
            </div>
            <form className="panel-body" onSubmit={handleAuth}>
              <div className="tabs" aria-label="Authentication mode">
                <button
                  className={`tab ${authMode === "login" ? "active" : ""}`}
                  type="button"
                  onClick={() => setAuthMode("login")}
                >
                  Login
                </button>
                <button
                  className={`tab ${authMode === "register" ? "active" : ""}`}
                  type="button"
                  onClick={() => setAuthMode("register")}
                >
                  Register
                </button>
              </div>

              {authMode === "register" ? (
                <div className="grid-2">
                  <div className="field">
                    <label htmlFor="fullName">Name</label>
                    <input
                      id="fullName"
                      value={fullName}
                      onChange={(event) => setFullName(event.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="role">Role</label>
                    <select
                      id="role"
                      value={role}
                      onChange={(event) => setRole(event.target.value as "worker" | "host")}
                    >
                      <option value="worker">Worker</option>
                      <option value="host">Host</option>
                    </select>
                  </div>
                </div>
              ) : null}

              <div className="field">
                <label htmlFor="email">Email</label>
                <input
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </div>
              <button className="btn" type="submit" disabled={busy}>
                <LogIn size={16} />
                {authMode === "login" ? "Login" : "Create account"}
              </button>
            </form>
            <div className="panel-body auth-divider">
              <form className="account-form" onSubmit={handleRequestPasswordReset}>
                <div className="panel-subheader">
                  <h3>Reset password</h3>
                  <KeyRound size={16} />
                </div>
                <div className="field">
                  <label htmlFor="resetEmail">Email</label>
                  <input
                    id="resetEmail"
                    type="email"
                    value={resetEmail}
                    onChange={(event) => setResetEmail(event.target.value)}
                  />
                </div>
                <button className="btn secondary" type="submit" disabled={busy}>
                  <MailCheck size={16} />
                  Request token
                </button>
              </form>
              <form className="account-form" onSubmit={handleConfirmPasswordReset}>
                <div className="field">
                  <label htmlFor="resetToken">Reset token</label>
                  <input
                    id="resetToken"
                    value={resetToken}
                    onChange={(event) => setResetToken(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="resetNewPassword">New password</label>
                  <input
                    id="resetNewPassword"
                    type="password"
                    value={resetNewPassword}
                    onChange={(event) => setResetNewPassword(event.target.value)}
                  />
                </div>
                <button className="btn secondary" type="submit" disabled={busy}>
                  <KeyRound size={16} />
                  Reset password
                </button>
              </form>
            </div>
          </section>
          ) : (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2>Dashboard</h2>
                  <div className="muted">{session.user.email}</div>
                </div>
                <LogIn size={18} />
              </div>
              <div className="panel-body">
                <div className="mode-badge" aria-label="Current dashboard mode">
                  {activeTab === "worker" ? "Worker dashboard" : null}
                  {activeTab === "host" ? "Host dashboard" : null}
                  {activeTab === "admin" ? "Admin dashboard" : null}
                </div>
                <div className="account-form">
                  <div className="security-row">
                    <div>
                      <strong>Email verification</strong>
                      <div className={`status ${session.user.email_verified_at ? "" : "pending"}`}>
                        {session.user.email_verified_at ? "verified" : "pending"}
                      </div>
                    </div>
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => void handleRequestEmailVerification()}
                      disabled={busy || Boolean(session.user.email_verified_at)}
                    >
                      <MailCheck size={16} />
                      Send token
                    </button>
                  </div>
                  {!session.user.email_verified_at ? (
                    <form className="inline-form" onSubmit={handleConfirmEmailVerification}>
                      <div className="field">
                        <label htmlFor="verificationToken">Verification token</label>
                        <input
                          id="verificationToken"
                          value={verificationToken}
                          onChange={(event) => setVerificationToken(event.target.value)}
                        />
                      </div>
                      <button className="btn secondary" type="submit" disabled={busy}>
                        <ShieldCheck size={16} />
                        Verify
                      </button>
                    </form>
                  ) : null}
                </div>
                <form className="account-form" onSubmit={handleProfileUpdate}>
                  <div className="field">
                    <label htmlFor="profileName">Name</label>
                    <input
                      id="profileName"
                      value={profileName}
                      onChange={(event) => setProfileName(event.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="profilePhone">Phone</label>
                    <input
                      id="profilePhone"
                      value={profilePhone}
                      onChange={(event) => setProfilePhone(event.target.value)}
                    />
                  </div>
                  <button className="btn secondary" type="submit" disabled={busy}>
                    Save profile
                  </button>
                </form>
                <form className="account-form" onSubmit={handlePasswordChange}>
                  <div className="field">
                    <label htmlFor="currentPassword">Current password</label>
                    <input
                      id="currentPassword"
                      type="password"
                      value={currentPassword}
                      onChange={(event) => setCurrentPassword(event.target.value)}
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="newPassword">New password</label>
                    <input
                      id="newPassword"
                      type="password"
                      value={newPassword}
                      onChange={(event) => setNewPassword(event.target.value)}
                    />
                  </div>
                  <button className="btn secondary" type="submit" disabled={busy}>
                    Change password
                  </button>
                </form>
              </div>
            </section>
          )}

          {activeTab === "worker" ? (
          <section className="panel">
            <div className="panel-header">
              <h2>Search Rota</h2>
              <Search size={18} />
            </div>
            <form className="panel-body" onSubmit={handleSearch}>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="city">City</label>
                  <input
                    id="city"
                    value={city}
                    onChange={(event) => setCity(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="minPrice">Min daily price</label>
                  <input
                    id="minPrice"
                    inputMode="decimal"
                    value={minPrice}
                    onChange={(event) => setMinPrice(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="maxPrice">Max daily price</label>
                  <input
                    id="maxPrice"
                    inputMode="decimal"
                    value={maxPrice}
                    onChange={(event) => setMaxPrice(event.target.value)}
                  />
                </div>
              </div>
              <div className="grid-2">
                <div className="field">
                  <label htmlFor="rotaLabel">Rota label</label>
                  <input
                    id="rotaLabel"
                    value={rotaLabel}
                    onChange={(event) => setRotaLabel(event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="bookingNotes">Booking notes</label>
                  <input
                    id="bookingNotes"
                    value={bookingNotes}
                    onChange={(event) => setBookingNotes(event.target.value)}
                  />
                </div>
              </div>

              <div className="rota-presets" aria-label="Quick rota presets">
                <button
                  className="preset-button"
                  type="button"
                  onClick={() => applyRotaPreset([toDateInputValue(new Date())], "Today")}
                >
                  Today
                </button>
                <button
                  className="preset-button"
                  type="button"
                  onClick={() =>
                    applyRotaPreset(nextMatchingDates(3, [1, 3, 5]), "Mon Wed Fri rota")
                  }
                >
                  Mon/Wed/Fri
                </button>
                <button
                  className="preset-button"
                  type="button"
                  onClick={() => applyRotaPreset(nextMatchingDates(2, [2, 4]), "Tue Thu rota")}
                >
                  Tue/Thu
                </button>
                <button
                  className="preset-button"
                  type="button"
                  onClick={() =>
                    applyRotaPreset(nextMatchingDates(5), "Next 5 workdays")
                  }
                >
                  Next 5 workdays
                </button>
              </div>

              {slots.map((slot, index) => (
                <div className="slot-row" key={`${slot.date}-${index}`}>
                  <div className="field">
                    <label htmlFor={`date-${index}`}>Date</label>
                    <div className="date-entry">
                      <input
                        id={`date-${index}`}
                        inputMode="numeric"
                        placeholder="MM/DD/YYYY"
                        value={slot.dateText}
                        onChange={(event) =>
                          updateSlotDateText(
                            index,
                            event.currentTarget.value,
                            event.currentTarget.selectionStart,
                          )
                        }
                      />
                      <button
                        aria-label={`Open date picker for rota day ${index + 1}`}
                        className="date-picker-button"
                        type="button"
                        onClick={() => openDatePicker(index)}
                      >
                        <CalendarPlus size={16} />
                      </button>
                      <input
                        aria-hidden="true"
                        className="native-date-input"
                        id={`date-picker-${index}`}
                        tabIndex={-1}
                        type="date"
                        min={todayInput}
                        value={slot.date}
                        onChange={(event) =>
                          updateSlotDateFromPicker(index, event.target.value)
                        }
                      />
                    </div>
                  </div>
                  <div className="grid-2">
                    <div className="field">
                      <label htmlFor={`start-${index}`}>Start</label>
                      <input
                        id={`start-${index}`}
                        type="time"
                        value={slot.start}
                        onChange={(event) => updateSlot(index, { start: event.target.value })}
                      />
                    </div>
                    <div className="field">
                      <label htmlFor={`end-${index}`}>End</label>
                      <input
                        id={`end-${index}`}
                        type="time"
                        value={slot.end}
                        onChange={(event) => updateSlot(index, { end: event.target.value })}
                      />
                    </div>
                  </div>
                  <button
                    aria-label={`Remove rota day ${index + 1}`}
                    className="remove-slot-button"
                    type="button"
                    onClick={() => removeSlot(index)}
                    title="Remove day"
                  >
                    <Trash2 size={16} />
                    <span>Remove</span>
                  </button>
                </div>
              ))}

              {slots.length === 0 ? (
                <div className="empty-rota">
                  No rota days selected. Add a day or choose a quick rota.
                </div>
              ) : null}

              <div className="button-row">
                <button
                  className="btn secondary"
                  type="button"
                  onClick={addNextRotaDay}
                >
                  <Plus size={16} />
                  Add day
                </button>
                <button className="btn" type="submit" disabled={busy}>
                  <Search size={16} />
                  Search
                </button>
              </div>
            </form>
          </section>
          ) : null}
        </aside>

        <section className="stack">
          {message ? <div className="notice">{message}</div> : null}
          {error ? <div className="error">{error}</div> : null}

          {activeTab === "admin" && isAdmin ? (
            <>
              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Workspace Review</h2>
                    <div className="muted">{reviewWorkspaces.length} pending listing{reviewWorkspaces.length === 1 ? "" : "s"}</div>
                  </div>
                  <ShieldCheck size={18} />
                </div>
                <div className="panel-body">
                  <div className="button-row">
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => runAction(() => refreshReviewWorkspaces())}
                      disabled={busy}
                    >
                      <History size={16} />
                      Refresh queue
                    </button>
                  </div>
                  <div className="workspace-list">
                    {reviewWorkspaces.length === 0 ? (
                      <div className="muted">No listings are waiting for review.</div>
                    ) : (
                      reviewWorkspaces.map((workspace) => (
                        <div className="workspace-row" key={workspace.id}>
                          <div className="workspace-thumb" aria-hidden="true">
                            {workspace.photo_url ? (
                              <img alt="" src={workspace.photo_url} />
                            ) : (
                              <span>{workspaceInitials(workspace.title)}</span>
                            )}
                          </div>
                          <div>
                            <strong>{workspace.title}</strong>
                            <div className="muted">
                              {workspace.address_line}, {workspace.city}
                            </div>
                            <div className="muted">
                              {formatMoney(workspace.daily_price, workspace.currency)} · {workspace.capacity} seat
                              {workspace.capacity === 1 ? "" : "s"}
                            </div>
                            <div className={`status review-${workspace.review_status ?? "pending"}`}>
                              Review: {workspace.review_status ?? "pending"}
                            </div>
                            <div className="field review-note-field">
                              <label htmlFor={`review-note-${workspace.id}`}>Review note</label>
                              <textarea
                                id={`review-note-${workspace.id}`}
                                placeholder="Optional reason or approval note"
                                value={reviewNotes[workspace.id] ?? ""}
                                onChange={(event) =>
                                  setReviewNotes((current) => ({
                                    ...current,
                                    [workspace.id]: event.target.value,
                                  }))
                                }
                              />
                            </div>
                          </div>
                          <div className="button-row">
                            <button
                              className="btn"
                              type="button"
                              onClick={() => handleReviewWorkspace(workspace, "approved")}
                              disabled={busy}
                            >
                              Approve
                            </button>
                            <button
                              className="btn danger"
                              type="button"
                              onClick={() => handleReviewWorkspace(workspace, "rejected")}
                              disabled={busy}
                            >
                              Reject
                            </button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Admin Operations</h2>
                    <div className="muted">
                      Users, bookings, and payments across the marketplace
                    </div>
                  </div>
                  <Wallet size={18} />
                </div>
                <div className="panel-body">
                  <div className="button-row">
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => runAction(() => refreshAdminOperations())}
                      disabled={busy}
                    >
                      <History size={16} />
                      Refresh operations
                    </button>
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() =>
                        runAction(async () => {
                          if (!session) {
                            return;
                          }
                          const response = await sendAdminEmailTest(session.access_token);
                          setMessage(
                            `Test email sent to ${response.recipient} via ${response.provider}.`,
                          );
                        })
                      }
                      disabled={busy}
                    >
                      <MailCheck size={16} />
                      Send email test
                    </button>
                  </div>

                  {emailStatus ? (
                    <div className="audit-row">
                      <div>
                        <strong>Email provider: {emailStatus.provider}</strong>
                        <div className="muted">From: {emailStatus.from_address}</div>
                        {emailStatus.smtp_host ? (
                          <div className="muted">
                            SMTP: {emailStatus.smtp_host}:{emailStatus.smtp_port}
                            {emailStatus.smtp_use_ssl
                              ? " SSL"
                              : emailStatus.smtp_use_tls
                                ? " TLS"
                                : ""}
                          </div>
                        ) : null}
                        {emailStatus.missing_settings.length > 0 ? (
                          <div className="muted">
                            Missing: {emailStatus.missing_settings.join(", ")}
                          </div>
                        ) : null}
                      </div>
                      <span className={`status ${emailStatus.ready ? "confirmed" : "pending"}`}>
                        {emailStatus.ready ? "ready" : "setup needed"}
                      </span>
                    </div>
                  ) : null}

                  {paymentProviderStatus ? (
                    <div className="audit-row">
                      <div>
                        <strong>Payment provider: {paymentProviderStatus.provider}</strong>
                        <div className="muted">
                          Webhook URL: {paymentProviderStatus.webhook_url}
                        </div>
                        <div className="muted">
                          Manual confirmation{" "}
                          {paymentProviderStatus.manual_confirmation_enabled
                            ? "enabled for mock payments"
                            : "disabled for real providers"}
                        </div>
                        {paymentProviderStatus.missing_settings.length > 0 ? (
                          <div className="muted">
                            Missing: {paymentProviderStatus.missing_settings.join(", ")}
                          </div>
                        ) : null}
                      </div>
                      <span
                        className={`status ${
                          paymentProviderStatus.ready ? "confirmed" : "pending"
                        }`}
                      >
                        {paymentProviderStatus.ready ? "ready" : "setup needed"}
                      </span>
                    </div>
                  ) : null}

                  {storageStatus ? (
                    <div className="audit-row">
                      <div>
                        <strong>Upload storage: {storageStatus.provider}</strong>
                        <div className="muted">
                          {storageStatus.durable
                            ? "Durable object storage enabled"
                            : "Local disk storage for demos only"}
                        </div>
                        {storageStatus.public_base_url ? (
                          <div className="muted">
                            Public base URL: {storageStatus.public_base_url}
                          </div>
                        ) : null}
                        {storageStatus.missing_settings.length > 0 ? (
                          <div className="muted">
                            Missing: {storageStatus.missing_settings.join(", ")}
                          </div>
                        ) : null}
                      </div>
                      <span
                        className={`status ${storageStatus.ready ? "confirmed" : "pending"}`}
                      >
                        {storageStatus.ready ? "ready" : "setup needed"}
                      </span>
                    </div>
                  ) : null}

                  <div className="ops-grid">
                    <div>
                      <div className="section-heading">
                        <h3>Users</h3>
                        <span className="muted">
                          {adminUsers.length} of {adminUsersTotal}
                        </span>
                      </div>
                      <div className="audit-list">
                        {adminUsers.length === 0 ? (
                          <div className="muted">Users will appear here.</div>
                        ) : (
                          adminUsers.map((user) => (
                            <div className="audit-row" key={user.id}>
                              <div>
                                <strong>{user.full_name}</strong>
                                <div className="muted">{user.email}</div>
                              </div>
                              <span className={`status ${user.is_active ? "" : "cancelled"}`}>
                                {user.role}
                              </span>
                            </div>
                          ))
                        )}
                      </div>
                      {adminUsers.length < adminUsersTotal ? (
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={loadMoreAdminUsers}
                          disabled={busy}
                        >
                          <History size={16} />
                          Load more users
                        </button>
                      ) : null}
                    </div>

                    <div>
                      <div className="section-heading">
                        <h3>Bookings</h3>
                        <span className="muted">
                          {adminBookings.length} of {adminBookingsTotal}
                        </span>
                      </div>
                      <div className="audit-list">
                        {adminBookings.length === 0 ? (
                          <div className="muted">Bookings will appear here.</div>
                        ) : (
                          adminBookings.map((booking) => (
                            <div className="audit-row" key={booking.id}>
                              <div>
                                <strong>
                                  {booking.workspace?.title ?? "Workspace booking"}
                                </strong>
                                <div className="muted">
                                  {booking.user?.email ?? "Unknown worker"} · {formatDateTime(booking.start_at)}
                                </div>
                                <div className="muted">
                                  {formatMoney(booking.total_price, booking.workspace?.currency ?? "INR")}
                                </div>
                              </div>
                              <span className={`status ${booking.status}`}>{booking.status}</span>
                            </div>
                          ))
                        )}
                      </div>
                      {adminBookings.length < adminBookingsTotal ? (
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={loadMoreAdminBookings}
                          disabled={busy}
                        >
                          <History size={16} />
                          Load more bookings
                        </button>
                      ) : null}
                    </div>

                    <div>
                      <div className="section-heading">
                        <h3>Payments</h3>
                        <span className="muted">
                          {adminPayments.length} of {adminPaymentsTotal}
                        </span>
                      </div>
                      <div className="audit-list">
                        {adminPayments.length === 0 ? (
                          <div className="muted">Payments will appear here.</div>
                        ) : (
                          adminPayments.map((payment) => (
                            <div className="audit-row" key={payment.id}>
                              <div>
                                <strong>{formatMoney(payment.amount, payment.currency)}</strong>
                                <div className="muted">
                                  {payment.provider} · {shortId(payment.booking_id)}
                                </div>
                                {payment.paid_at ? (
                                  <div className="muted">Paid {formatDateTime(payment.paid_at)}</div>
                                ) : null}
                              </div>
                              <span className={`status ${payment.status}`}>{payment.status}</span>
                            </div>
                          ))
                        )}
                      </div>
                      {adminPayments.length < adminPaymentsTotal ? (
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={loadMoreAdminPayments}
                          disabled={busy}
                        >
                          <History size={16} />
                          Load more payments
                        </button>
                      ) : null}
                    </div>
                  </div>
                </div>
              </section>

              <section className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Audit Trail</h2>
                    <div className="muted">
                      Showing {auditEvents.length} of {auditEventsTotal} event
                      {auditEventsTotal === 1 ? "" : "s"}
                    </div>
                  </div>
                  <History size={18} />
                </div>
                <div className="panel-body">
                  <div className="button-row">
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => runAction(() => refreshAuditEvents())}
                      disabled={busy}
                    >
                      <History size={16} />
                      Refresh audit
                    </button>
                  </div>
                  <div className="audit-list">
                    {auditEvents.length === 0 ? (
                      <div className="muted">Audit events will appear here.</div>
                    ) : (
                      auditEvents.map((event) => (
                        <div className="audit-row" key={event.id}>
                          <div>
                            <strong>{formatAuditAction(event.action)}</strong>
                            <div className="muted">
                              {event.entity_type} {shortId(event.entity_id)} · actor {shortId(event.actor_user_id)}
                            </div>
                            {summarizeAuditDetails(event.details) ? (
                              <div className="muted">{summarizeAuditDetails(event.details)}</div>
                            ) : null}
                          </div>
                          <span className="muted">{formatDateTime(event.created_at)}</span>
                        </div>
                      ))
                    )}
                  </div>
                  {auditEvents.length < auditEventsTotal ? (
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={loadMoreAuditEvents}
                      disabled={busy}
                    >
                      <History size={16} />
                      Load more events
                    </button>
                  ) : null}
                </div>
              </section>
            </>
          ) : null}

          {activeTab === "host" && isHost ? (
            <section className="panel">
              <div className="panel-header">
                <div>
                  <h2>Host Workspace Manager</h2>
                  <div className="muted">Submit rooms for review and manage worker availability</div>
                </div>
                <Building2 size={18} />
              </div>
              <div className="panel-body">
                <form className="host-form" onSubmit={handleCreateWorkspace}>
                  <div className="host-onboarding-note">
                    New rooms stay pending until an admin approves them. Workers only see approved rooms
                    that match their rota.
                  </div>
                  <div className="grid-2">
                    <div className="field">
                      <label htmlFor="workspaceTitle">Title</label>
                      <input
                        id="workspaceTitle"
                        placeholder="e.g. Koramangala focus room"
                        value={workspaceForm.title}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            title: event.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="workspacePrice">Daily price</label>
                      <input
                        id="workspacePrice"
                        inputMode="decimal"
                        placeholder="850.00"
                        value={workspaceForm.dailyPrice}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            dailyPrice: event.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="workspaceDescription">Description</label>
                    <textarea
                      id="workspaceDescription"
                      placeholder="Quiet room with desk, Wi-Fi and easy metro access."
                      value={workspaceForm.description}
                      onChange={(event) =>
                        setWorkspaceForm((current) => ({
                          ...current,
                          description: event.target.value,
                        }))
                      }
                    />
                  </div>
                  <div className="grid-2">
                    <div className="field">
                      <label htmlFor="workspaceAddress">Address</label>
                      <input
                        id="workspaceAddress"
                        placeholder="12 Residency Road"
                        value={workspaceForm.addressLine}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            addressLine: event.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="workspaceCity">City</label>
                      <input
                        id="workspaceCity"
                        placeholder="Bengaluru"
                        value={workspaceForm.city}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            city: event.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="grid-2">
                    <div className="field">
                      <label htmlFor="workspaceState">State</label>
                      <input
                        id="workspaceState"
                        value={workspaceForm.state}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            state: event.target.value,
                          }))
                        }
                      />
                    </div>
                    <div className="field">
                      <label htmlFor="workspacePhotoFile">Photo upload</label>
                      <input
                        id="workspacePhotoFile"
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={(event) =>
                          handleNewWorkspacePhoto(event.target.files?.[0] ?? null)
                        }
                      />
                      {workspaceForm.photoFile ? (
                        <div className="muted">{workspaceForm.photoFile.name}</div>
                      ) : null}
                    </div>
                  </div>
                  <div className="field">
                    <label htmlFor="workspacePhoto">Photo URL fallback</label>
                      <input
                        id="workspacePhoto"
                        placeholder="https://..."
                        value={workspaceForm.photoUrl}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            photoUrl: event.target.value,
                            photoFile: null,
                          }))
                        }
                      />
                  </div>
                  <div className="field">
                    <label>Amenities</label>
                    <div className="amenity-toggle-row">
                      {HOST_AMENITIES.map((amenity) => (
                        <button
                          className={`amenity-toggle ${
                            workspaceForm.amenities.includes(amenity.key) ? "active" : ""
                          }`}
                          key={amenity.key}
                          type="button"
                          onClick={() => toggleWorkspaceFormAmenity(amenity.key)}
                          disabled={busy}
                        >
                          {amenity.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="host-form-section">
                    <div>
                      <strong>Weekly availability</strong>
                      <div className="muted">Choose the days and day-use window workers can book.</div>
                    </div>
                    <div className="day-toggle-row" aria-label="New workspace available days">
                      {WEEKDAYS.map((dayLabel, day) => (
                        <button
                          className={`day-toggle ${
                            workspaceForm.availabilityDays.includes(day) ? "active" : ""
                          }`}
                          key={dayLabel}
                          type="button"
                          onClick={() => toggleWorkspaceFormDay(day)}
                          disabled={busy}
                        >
                          {dayLabel}
                        </button>
                      ))}
                    </div>
                    <div className="availability-time-row">
                      <input
                        aria-label="New workspace availability start time"
                        type="time"
                        value={workspaceForm.availabilityStart}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            availabilityStart: event.target.value,
                          }))
                        }
                      />
                      <input
                        aria-label="New workspace availability end time"
                        type="time"
                        value={workspaceForm.availabilityEnd}
                        onChange={(event) =>
                          setWorkspaceForm((current) => ({
                            ...current,
                            availabilityEnd: event.target.value,
                          }))
                        }
                      />
                    </div>
                  </div>
                  <div className="button-row">
                    <button className="btn" type="submit" disabled={busy}>
                      <Plus size={16} />
                      Submit for review
                    </button>
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => runAction(() => refreshHostWorkspaces())}
                      disabled={busy}
                    >
                      <History size={16} />
                      Refresh listings
                    </button>
                  </div>
                </form>

                <div className="workspace-list">
                  {hostWorkspaces.length === 0 ? (
                    <div className="muted">Your workspace listings will appear here.</div>
                  ) : (
                    hostWorkspaces.map((workspace) => {
                      const listingDraft = listingDrafts[workspace.id] ?? listingDraftFromWorkspace(workspace);
                      return (
                      <div className="workspace-row" key={workspace.id}>
                        <div className="workspace-thumb" aria-hidden="true">
                          {workspace.photo_url ? (
                            <img alt="" src={workspace.photo_url} />
                          ) : (
                            <span>{workspaceInitials(workspace.title)}</span>
                          )}
                        </div>
                        <div>
                          <strong>{workspace.title}</strong>
                          <div className="muted">
                            {workspace.city} · {formatMoney(workspace.daily_price, workspace.currency)}
                          </div>
                          <div className="muted">
                            Availability: {availabilitySummary(workspace.availability_rules)}
                          </div>
                          <div className={`status ${workspace.status === "paused" ? "cancelled" : ""}`}>
                            {workspace.status}
                          </div>
                          <div className={`status review-${workspace.review_status ?? "pending"}`}>
                            Review: {workspace.review_status ?? "pending"}
                          </div>
                          <div className="listing-editor">
                            <div className="grid-2">
                              <div className="field">
                                <label htmlFor={`listing-title-${workspace.id}`}>Title</label>
                                <input
                                  id={`listing-title-${workspace.id}`}
                                  value={listingDraft.title}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { title: event.target.value })
                                  }
                                />
                              </div>
                              <div className="field">
                                <label htmlFor={`listing-price-${workspace.id}`}>Daily price</label>
                                <input
                                  id={`listing-price-${workspace.id}`}
                                  inputMode="decimal"
                                  value={listingDraft.dailyPrice}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { dailyPrice: event.target.value })
                                  }
                                />
                              </div>
                            </div>
                            <div className="field">
                              <label htmlFor={`listing-description-${workspace.id}`}>Description</label>
                              <textarea
                                id={`listing-description-${workspace.id}`}
                                value={listingDraft.description}
                                onChange={(event) =>
                                  updateListingDraft(workspace.id, { description: event.target.value })
                                }
                              />
                            </div>
                            <div className="grid-2">
                              <div className="field">
                                <label htmlFor={`listing-address-${workspace.id}`}>Address</label>
                                <input
                                  id={`listing-address-${workspace.id}`}
                                  value={listingDraft.addressLine}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { addressLine: event.target.value })
                                  }
                                />
                              </div>
                              <div className="field">
                                <label htmlFor={`listing-city-${workspace.id}`}>City</label>
                                <input
                                  id={`listing-city-${workspace.id}`}
                                  value={listingDraft.city}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { city: event.target.value })
                                  }
                                />
                              </div>
                            </div>
                            <div className="grid-2">
                              <div className="field">
                                <label htmlFor={`listing-state-${workspace.id}`}>State</label>
                                <input
                                  id={`listing-state-${workspace.id}`}
                                  value={listingDraft.state}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { state: event.target.value })
                                  }
                                />
                              </div>
                              <div className="field">
                                <label htmlFor={`listing-photo-file-${workspace.id}`}>Photo upload</label>
                                <input
                                  id={`listing-photo-file-${workspace.id}`}
                                  type="file"
                                  accept="image/jpeg,image/png,image/webp"
                                  onChange={(event) =>
                                    handleListingPhotoUpload(workspace, event.target.files?.[0] ?? null)
                                  }
                                  disabled={busy}
                                />
                              </div>
                            </div>
                            <div className="field">
                              <label htmlFor={`listing-photo-${workspace.id}`}>Photo URL fallback</label>
                                <input
                                  id={`listing-photo-${workspace.id}`}
                                  value={listingDraft.photoUrl}
                                  onChange={(event) =>
                                    updateListingDraft(workspace.id, { photoUrl: event.target.value })
                                  }
                                />
                            </div>
                            <div className="field">
                              <label>Amenities</label>
                              <div className="amenity-toggle-row">
                                {HOST_AMENITIES.map((amenity) => (
                                  <button
                                    className={`amenity-toggle ${
                                      listingDraft.amenities.includes(amenity.key) ? "active" : ""
                                    }`}
                                    key={amenity.key}
                                    type="button"
                                    onClick={() => toggleListingDraftAmenity(workspace, amenity.key)}
                                    disabled={busy}
                                  >
                                    {amenity.label}
                                  </button>
                                ))}
                              </div>
                            </div>
                            <div className="button-row">
                              <button
                                className="btn secondary"
                                type="button"
                                onClick={() => handleSaveListingDetails(workspace)}
                                disabled={busy}
                              >
                                Save listing details
                              </button>
                            </div>
                          </div>
                          <div className="availability-editor">
                            <div className="day-toggle-row" aria-label={`${workspace.title} available days`}>
                              {WEEKDAYS.map((dayLabel, day) => (
                                <button
                                  className={`day-toggle ${
                                    (availabilityDrafts[workspace.id] ?? draftFromRules(workspace.availability_rules))
                                      .days.includes(day)
                                      ? "active"
                                      : ""
                                  }`}
                                  key={dayLabel}
                                  type="button"
                                  onClick={() => toggleAvailabilityDay(workspace.id, day)}
                                  disabled={busy}
                                >
                                  {dayLabel}
                                </button>
                              ))}
                            </div>
                            <div className="availability-time-row">
                              <input
                                aria-label="Availability start time"
                                type="time"
                                value={
                                  (availabilityDrafts[workspace.id] ?? draftFromRules(workspace.availability_rules))
                                    .start
                                }
                                onChange={(event) =>
                                  updateAvailabilityDraft(workspace.id, { start: event.target.value })
                                }
                              />
                              <input
                                aria-label="Availability end time"
                                type="time"
                                value={
                                  (availabilityDrafts[workspace.id] ?? draftFromRules(workspace.availability_rules))
                                    .end
                                }
                                onChange={(event) =>
                                  updateAvailabilityDraft(workspace.id, { end: event.target.value })
                                }
                              />
                              <button
                                className="btn secondary"
                                type="button"
                                onClick={() => handleSaveAvailability(workspace)}
                                disabled={busy}
                              >
                                Save availability
                              </button>
                            </div>
                          </div>
                          <div className="blackout-editor">
                            <div className="muted">
                              Blocked dates: {(blackoutDrafts[workspace.id]?.items.length ?? 0) || "none"}
                            </div>
                            <div className="availability-time-row">
                              <input
                                aria-label="Blocked date"
                                type="date"
                                value={(blackoutDrafts[workspace.id] ?? draftFromBlackoutDates(workspace)).nextDate}
                                onChange={(event) =>
                                  updateBlackoutDraft(workspace.id, { nextDate: event.target.value })
                                }
                              />
                              <input
                                aria-label="Blocked date reason"
                                placeholder="Reason"
                                value={(blackoutDrafts[workspace.id] ?? draftFromBlackoutDates(workspace)).nextReason}
                                onChange={(event) =>
                                  updateBlackoutDraft(workspace.id, { nextReason: event.target.value })
                                }
                              />
                              <button
                                className="btn secondary"
                                type="button"
                                onClick={() => addBlackoutDraftItem(workspace.id)}
                                disabled={busy}
                              >
                                Add blocked date
                              </button>
                            </div>
                            {(blackoutDrafts[workspace.id]?.items.length ?? 0) > 0 ? (
                              <div className="blackout-list">
                                {(blackoutDrafts[workspace.id] ?? draftFromBlackoutDates(workspace)).items.map(
                                  (item) => (
                                    <span className="blackout-chip" key={item.blackout_date}>
                                      {item.blackout_date}
                                      {item.reason ? ` · ${item.reason}` : ""}
                                      <button
                                        aria-label={`Remove blocked date ${item.blackout_date}`}
                                        type="button"
                                        onClick={() =>
                                          removeBlackoutDraftItem(workspace.id, item.blackout_date)
                                        }
                                        disabled={busy}
                                      >
                                        x
                                      </button>
                                    </span>
                                  ),
                                )}
                              </div>
                            ) : null}
                            <button
                              className="btn secondary"
                              type="button"
                              onClick={() => handleSaveBlackoutDates(workspace)}
                              disabled={busy}
                            >
                              Save blocked dates
                            </button>
                          </div>
                        </div>
                        <div className="button-row">
                          <button
                            className="btn secondary"
                            type="button"
                            onClick={() => handleWorkspaceStatus(workspace, "active")}
                            disabled={
                              busy ||
                              workspace.status === "active" ||
                              workspace.review_status !== "approved"
                            }
                          >
                            Activate
                          </button>
                          <button
                            className="btn secondary"
                            type="button"
                            onClick={() => handleWorkspaceStatus(workspace, "paused")}
                            disabled={busy || workspace.status === "paused"}
                          >
                            Pause
                          </button>
                        </div>
                      </div>
                    );
                    })
                  )}
                </div>
              </div>
            </section>
          ) : null}

          {activeTab === "worker" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>Available Rooms</h2>
                <div className="muted">{selectedDays} selected day{selectedDays === 1 ? "" : "s"}</div>
              </div>
              <Building2 size={18} />
            </div>
            <div className="panel-body">
              {results.length === 0 ? (
                <div className="muted">Search for a rota to see available workspaces.</div>
              ) : (
                <div className="results-grid">
                  {results.map((workspace) => (
                    <article className="workspace-card" key={workspace.id}>
                      <div className="workspace-photo">
                        {workspace.photo_url ? (
                          <img alt={workspace.title} src={workspace.photo_url} />
                        ) : (
                          <div className="photo-fallback">{workspaceInitials(workspace.title)}</div>
                        )}
                      </div>
                      <div>
                        <h3 className="card-title">{workspace.title}</h3>
                        <div className="muted">
                          {workspace.address_line}, {workspace.city}
                        </div>
                      </div>
                      <p className="muted">{workspace.description}</p>
                      <div className="pill-row">
                        {Object.entries(workspace.amenities)
                          .filter(([, enabled]) => Boolean(enabled))
                          .slice(0, 4)
                          .map(([name]) => (
                            <span className="pill" key={name}>
                              {name}
                            </span>
                          ))}
                      </div>
                      <div>
                        <div className="price">
                          {formatMoney(workspace.daily_price, workspace.currency)}
                        </div>
                        <div className="muted">
                          Estimated rota total{" "}
                          {formatMoney(
                            estimatedWorkspaceTotal(workspace, selectedDays),
                            workspace.currency,
                          )}
                          {" "}for {workspace.matched_slot_count ?? selectedDays} day
                          {(workspace.matched_slot_count ?? selectedDays) === 1 ? "" : "s"}
                        </div>
                      </div>
                      <button
                        className="btn"
                        type="button"
                        onClick={() => handleBook(workspace)}
                        disabled={busy || !session}
                      >
                        <CalendarPlus size={16} />
                        Book rota
                      </button>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </section>
          ) : null}

          {activeTab !== "admin" ? (
          <section className="panel">
            <div className="panel-header">
              <div>
                <h2>{activeTab === "host" ? "Guest Bookings" : "Booking History"}</h2>
                <div className="muted">
                  {activeTab === "host"
                    ? `Showing ${hostBookings.length} of ${hostBookingsTotal} guest booking${
                        hostBookingsTotal === 1 ? "" : "s"
                      }`
                    : `Showing ${groupedMyBookings.length} rota group${
                        groupedMyBookings.length === 1 ? "" : "s"
                      } from ${myBookings.length} loaded day${myBookings.length === 1 ? "" : "s"}`}
                </div>
              </div>
              <History size={18} />
            </div>
            <div className="panel-body">
              <div className="button-row">
                <button
                  className="btn secondary"
                  type="button"
                  onClick={() => runAction(() => refreshBookings())}
                  disabled={!session || busy}
                >
                  <History size={16} />
                  Refresh
                </button>
                {activeTab === "host" ? (
                  <button
                    className="btn secondary"
                    type="button"
                    onClick={() => runAction(() => refreshHostWorkspaces())}
                    disabled={busy}
                  >
                    <Building2 size={16} />
                    Refresh listings
                  </button>
                ) : null}
              </div>
              {activeTab === "worker" ? (
              <>
              <div className="booking-list">
                {myBookings.length === 0 ? (
                  <div className="muted">Your bookings will appear here.</div>
                ) : (
                  groupedMyBookings.map((group) => {
                    const booking = group.firstBooking;
                    return (
                    <div className="booking-row" key={group.booking_group_id}>
                      <div className="workspace-thumb" aria-hidden="true">
                        {booking.workspace?.photo_url ? (
                          <img alt="" src={booking.workspace.photo_url} />
                        ) : (
                          <span>{workspaceInitials(booking.workspace?.title ?? "Booking")}</span>
                        )}
                      </div>
                      <div>
                        <strong>{booking.workspace?.title ?? "Workspace booking"}</strong>
                        <div className="muted">
                          {bookingGroupDateRange(group.bookings)}
                        </div>
                        <div className="muted">
                          {booking.workspace?.city ?? "City"} · {booking.rota_label ?? "Rota booking"} ·{" "}
                          {formatMoney(group.totalPrice)}
                        </div>
                        <div className="muted">
                          {group.dayCount} booked day{group.dayCount === 1 ? "" : "s"} in this rota
                        </div>
                        {booking.notes ? (
                          <div className="muted">
                            Notes: {booking.notes}
                          </div>
                        ) : null}
                        {booking.status === "pending" && booking.expires_at ? (
                          <div className="muted">
                            Pay by {formatDateTime(booking.expires_at)}
                          </div>
                        ) : null}
                      </div>
                      <div>
                        <div className={`status ${group.status}`}>{group.status}</div>
                        <button
                          className="btn secondary"
                          type="button"
                          onClick={() => setSelectedBookingGroup(group)}
                          disabled={busy}
                        >
                          Details
                        </button>
                        {group.payableBooking ? (
                          <button
                            className="btn"
                            type="button"
                            onClick={() => handlePayBooking(group.payableBooking as Booking)}
                            disabled={busy}
                          >
                            Pay
                          </button>
                        ) : null}
                        {group.status === "confirmed" || group.status === "mixed" ? (
                          <button
                            className="btn secondary"
                            type="button"
                            onClick={() => handleViewReceipt(group)}
                            disabled={busy}
                          >
                            Receipt
                          </button>
                        ) : null}
                        {group.cancellableBooking ? (
                          <button
                            className="btn secondary"
                            type="button"
                            onClick={() => handleCancel(group.cancellableBooking as Booking)}
                            disabled={busy}
                          >
                            Cancel
                          </button>
                        ) : null}
                      </div>
                    </div>
                    );
                  })
                )}
              </div>
              {selectedBookingGroup ? (
                <div className="booking-detail-panel" aria-label="Booking details">
                  <div className="panel-subheader">
                    <div>
                      <h3>{selectedBookingGroup.firstBooking.workspace?.title ?? "Workspace booking"}</h3>
                      <div className="muted">
                        {selectedBookingGroup.dayCount} rota day
                        {selectedBookingGroup.dayCount === 1 ? "" : "s"} ·{" "}
                        {formatMoney(selectedBookingGroup.totalPrice)}
                      </div>
                    </div>
                    <span className={`status ${selectedBookingGroup.status}`}>
                      {selectedBookingGroup.status}
                    </span>
                  </div>
                  <div className="booking-detail-grid">
                    {selectedBookingGroup.bookings.map((booking) => (
                      <div className="booking-detail-day" key={booking.id}>
                        <strong>{bookingDateRange(booking)}</strong>
                        <span className={`status ${booking.status}`}>{booking.status}</span>
                        {booking.expires_at && booking.status === "pending" ? (
                          <span className="muted">Pay by {formatDateTime(booking.expires_at)}</span>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  <div className="policy-note">
                    Confirmed bookings can be cancelled from booking history. Eligible paid days are
                    refunded through the original payment provider; provider and bank timelines may vary.
                  </div>
                  <div className="button-row">
                    {selectedBookingGroup.payableBooking ? (
                      <button
                        className="btn"
                        type="button"
                        onClick={() => handlePayBooking(selectedBookingGroup.payableBooking as Booking)}
                        disabled={busy}
                      >
                        Pay now
                      </button>
                    ) : null}
                    {selectedBookingGroup.cancellableBooking ? (
                      <button
                        className="btn secondary"
                        type="button"
                        onClick={() => handleCancel(selectedBookingGroup.cancellableBooking as Booking)}
                        disabled={busy}
                      >
                        Cancel rota
                      </button>
                    ) : null}
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={() => setSelectedBookingGroup(null)}
                      disabled={busy}
                    >
                      Close details
                    </button>
                  </div>
                </div>
              ) : null}
              {selectedReceipt ? (
                <div className="receipt-panel" aria-label="Booking receipt">
                  <div>
                    <strong>Receipt</strong>
                    <div className="muted">
                      {selectedReceipt.bookings[0]?.workspace?.title ?? "Workspace booking"} ·{" "}
                      {selectedReceipt.bookings.length} day
                      {selectedReceipt.bookings.length === 1 ? "" : "s"}
                    </div>
                    <div className="muted">
                      Issued {formatDateTime(selectedReceipt.issued_at)}
                      {selectedReceipt.paid_at ? ` · Paid ${formatDateTime(selectedReceipt.paid_at)}` : ""}
                    </div>
                  </div>
                  <div className="receipt-totals">
                    <span>Paid {formatMoney(selectedReceipt.total_paid, selectedReceipt.currency)}</span>
                    {Number(selectedReceipt.total_refunded) > 0 ? (
                      <span>Refunded {formatMoney(selectedReceipt.total_refunded, selectedReceipt.currency)}</span>
                    ) : null}
                    <strong>Net {formatMoney(selectedReceipt.net_paid, selectedReceipt.currency)}</strong>
                  </div>
                  <button
                    className="btn secondary"
                    type="button"
                    onClick={() => setSelectedReceipt(null)}
                    disabled={busy}
                  >
                    Close receipt
                  </button>
                </div>
              ) : null}
              {myBookings.length < myBookingsTotal ? (
                <button
                  className="btn secondary"
                  type="button"
                  onClick={loadMoreMyBookings}
                  disabled={busy}
                >
                  <History size={16} />
                  Load more bookings
                </button>
              ) : null}
              </>
              ) : null}
              {activeTab === "host" && hostRevenue ? (
                <div className="revenue-summary" aria-label="Host revenue summary">
                  <div className="metric">
                    <Wallet size={18} />
                    <div>
                      <span>Paid revenue</span>
                      <strong>{formatMoney(hostRevenue.total_paid, hostRevenue.currency)}</strong>
                    </div>
                  </div>
                  <div className="metric">
                    <History size={18} />
                    <div>
                      <span>Refunded</span>
                      <strong>
                        {formatMoney(hostRevenue.total_refunded, hostRevenue.currency)}
                      </strong>
                    </div>
                  </div>
                  <div className="metric">
                    <History size={18} />
                    <div>
                      <span>Pending holds</span>
                      <strong>
                        {formatMoney(hostRevenue.pending_hold_value, hostRevenue.currency)}
                      </strong>
                    </div>
                  </div>
                  <div className="metric">
                    <CalendarPlus size={18} />
                    <div>
                      <span>Confirmed stays</span>
                      <strong>{hostRevenue.confirmed_booking_count}</strong>
                    </div>
                  </div>
                  <div className="metric">
                    <Trash2 size={18} />
                    <div>
                      <span>Cancelled stays</span>
                      <strong>{hostRevenue.cancelled_booking_count}</strong>
                    </div>
                  </div>
                  <div className="metric">
                    <Building2 size={18} />
                    <div>
                      <span>Awaiting payment</span>
                      <strong>{hostRevenue.pending_booking_count}</strong>
                    </div>
                  </div>
                </div>
              ) : null}
              {activeTab === "host" && hostBookings.length === 0 ? (
                <div className="muted">Guest bookings will appear here once workers book your rooms.</div>
              ) : null}
              {activeTab === "host" && hostBookings.length > 0 ? (
                <>
                  <h3>
                    Host bookings{" "}
                    <span className="muted">
                      {hostBookings.length} of {hostBookingsTotal}
                    </span>
                  </h3>
                  <div className="booking-list">
                    {hostBookings.map((booking) => (
                      <div className="booking-row" key={booking.id}>
                        <div className="workspace-thumb" aria-hidden="true">
                          {booking.workspace?.photo_url ? (
                            <img alt="" src={booking.workspace.photo_url} />
                          ) : (
                            <span>{workspaceInitials(booking.workspace?.title ?? "Booking")}</span>
                          )}
                        </div>
                        <div>
                          <strong>{booking.workspace?.title ?? "Workspace booking"}</strong>
                          <div className="muted">
                            {bookingDateRange(booking)}
                          </div>
                          <div className="muted">
                            {booking.user?.full_name ?? "Guest"} · {booking.user?.email ?? booking.user_id.slice(0, 8)} ·{" "}
                            {formatMoney(booking.total_price)}
                          </div>
                          {booking.status === "pending" && booking.expires_at ? (
                            <div className="muted">
                              Hold expires {formatDateTime(booking.expires_at)}
                            </div>
                          ) : null}
                        </div>
                        <span className={`status ${booking.status}`}>{booking.status}</span>
                      </div>
                    ))}
                  </div>
                  {hostBookings.length < hostBookingsTotal ? (
                    <button
                      className="btn secondary"
                      type="button"
                      onClick={loadMoreHostBookings}
                      disabled={busy}
                    >
                      <History size={16} />
                      Load more host bookings
                    </button>
                  ) : null}
                </>
              ) : null}
            </div>
          </section>
          ) : null}
        </section>
      </div>

      <footer className="site-footer" aria-label="Legal and support links">
        <a href="/privacy">Privacy</a>
        <a href="/terms">Terms</a>
        <a href="/refunds">Cancellation and refunds</a>
        <a href="/contact">Contact</a>
      </footer>

      {pendingConfirmation ? (
        <div className="modal-backdrop" role="presentation">
          <section
            aria-labelledby="confirmation-title"
            aria-modal="true"
            className="modal"
            role="dialog"
          >
            <h2 id="confirmation-title">{confirmationTitle()}</h2>
            <p>{confirmationBody()}</p>
            <p className="modal-note">{confirmationPolicy()}</p>
            <div className="button-row">
              <button
                className={pendingConfirmation.kind === "cancel" ? "btn danger" : "btn"}
                type="button"
                onClick={() =>
                  pendingConfirmation.kind === "book"
                    ? confirmBook(
                        pendingConfirmation.workspace,
                        pendingConfirmation.idempotencyKey,
                      )
                    : confirmCancel(pendingConfirmation.booking)
                }
                disabled={busy}
              >
                {pendingConfirmation.kind === "book" ? "Confirm booking" : "Cancel booking"}
              </button>
              <button
                className="btn secondary"
                type="button"
                onClick={() => setPendingConfirmation(null)}
                disabled={busy}
              >
                Keep editing
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
