import Link from "next/link";

export const metadata = {
  title: "Contact and Support | Hybrid Stay Booking",
  description: "Support contact information for Hybrid Stay Booking.",
};

export default function ContactPage() {
  return (
    <main className="legal-page">
      <section className="legal-document">
        <Link className="legal-back-link" href="/">Back to booking</Link>
        <h1>Contact and Support</h1>
        <p className="muted">Last updated: July 5, 2026</p>

        <h2>Support</h2>
        <p>
          For booking, payment, refund, host listing, or account support, include
          your account email, booking id, payment reference if available, and the
          relevant rota dates.
        </p>

        <h2>Pilot Contact Details</h2>
        <p>
          Final business email, phone number, registered address, and operating
          hours should be added before public launch and before switching to live
          payments.
        </p>

        <h2>Common Requests</h2>
        <p>
          Workers can use booking history for receipts, pending payments, and
          cancellations. Hosts can use the host dashboard for listing availability,
          blocked dates, and guest booking history. Admins can review listings and
          audit platform events.
        </p>

        <h2>Payment Issues</h2>
        <p>
          If a payment succeeds but the booking remains pending, wait a few minutes
          for the payment webhook to arrive. If it still does not update, contact
          support with the payment reference and booking group id.
        </p>
      </section>
    </main>
  );
}
