import Link from "next/link";

export const metadata = {
  title: "Terms of Service | Hybrid Stay Booking",
  description: "Terms for using Hybrid Stay Booking.",
};

export default function TermsPage() {
  return (
    <main className="legal-page">
      <section className="legal-document">
        <Link className="legal-back-link" href="/">Back to booking</Link>
        <h1>Terms of Service</h1>
        <p className="muted">Last updated: July 5, 2026</p>

        <h2>Service</h2>
        <p>
          Hybrid Stay Booking is a platform for workers to discover and reserve
          short-term workday rooms offered by hosts. The service is intended for
          day-use or rota-based work stays, not long-term tenancy.
        </p>

        <h2>Accounts</h2>
        <p>
          Users must provide accurate account information and keep login credentials
          secure. Workers are responsible for booking only the dates and times they
          need. Hosts are responsible for listing accurate workspace details,
          pricing, availability, amenities, and restrictions.
        </p>

        <h2>Bookings</h2>
        <p>
          A booking is confirmed only after payment succeeds and the booking status
          changes to confirmed. Pending bookings may expire if payment is not
          completed within the hold window. Availability may change until payment
          confirmation is complete.
        </p>

        <h2>Host Responsibilities</h2>
        <p>
          Hosts must have the right to offer their listed space, keep the space
          safe, honor confirmed bookings, and comply with local laws, building
          rules, tax obligations, and any permissions required for short-term use.
        </p>

        <h2>Worker Responsibilities</h2>
        <p>
          Workers must use booked spaces respectfully, follow host instructions,
          avoid unlawful activity, and leave the room in reasonable condition.
          Workers should not overstay the booked time window.
        </p>

        <h2>Payments</h2>
        <p>
          Payments are processed through the configured payment provider. Platform
          prices, taxes, fees, refunds, and cancellation handling may vary by
          booking and will be shown where applicable.
        </p>

        <h2>Changes and Suspension</h2>
        <p>
          We may update the service, review or remove listings, restrict accounts,
          or cancel bookings where needed for safety, fraud prevention, policy
          enforcement, or legal compliance.
        </p>

        <h2>Final Business Details</h2>
        <p>
          Operator legal name, address, tax details, and final jurisdiction clauses
          should be added before public launch.
        </p>
      </section>
    </main>
  );
}
