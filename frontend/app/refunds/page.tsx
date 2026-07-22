import Link from "next/link";

export const metadata = {
  title: "Cancellation and Refund Policy | Hybrid Stay Booking",
  description: "Cancellation and refund rules for Hybrid Stay Booking.",
};

export default function RefundPolicyPage() {
  return (
    <main className="legal-page">
      <section className="legal-document">
        <Link className="legal-back-link" href="/">Back to booking</Link>
        <h1>Cancellation and Refund Policy</h1>
        <p className="muted">Last updated: July 21, 2026</p>

        <h2>Pending Bookings</h2>
        <p>
          Pending bookings are temporary holds. If payment is not completed within
          the hold window, the booking may expire and the room may become available
          to other workers.
        </p>

        <h2>Confirmed Bookings</h2>
        <p>
          Confirmed bookings can be cancelled from booking history where cancellation
          is available. Refund eligibility depends on the cancellation window,
          provider settlement status, host policy, and any platform rules shown at
          the time of booking.
        </p>

        <h2>Current Pilot Policy</h2>
        <p>
          During pilot testing, confirmed bookings cancelled more than 24 hours
          before check-in are eligible for a full refund where payment provider
          settlement rules allow it. Cancellations within 24 hours of check-in,
          no-shows, misuse, or overstays may be non-refundable. Stays that have
          already started cannot be cancelled through self-service.
        </p>

        <h2>Refund Processing</h2>
        <p>
          Approved refunds are processed through the original payment provider.
          Refund timing depends on the provider and the worker&apos;s bank or payment
          method. Provider fees may be non-refundable where applicable.
        </p>

        <h2>Host Cancellations</h2>
        <p>
          If a host cannot honor a confirmed booking, the worker should receive a
          refund or support with an alternative room where feasible.
        </p>

        <h2>Disputes</h2>
        <p>
          Contact support with the booking id, payment reference, rota dates, and a
          short explanation. Final public-launch dispute timelines and escalation
          rules should be added before accepting live payments.
        </p>
      </section>
    </main>
  );
}
