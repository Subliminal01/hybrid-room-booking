import Link from "next/link";

export const metadata = {
  title: "Privacy Policy | Hybrid Stay Booking",
  description: "Privacy practices for Hybrid Stay Booking users, hosts, and admins.",
};

export default function PrivacyPolicyPage() {
  return (
    <main className="legal-page">
      <section className="legal-document">
        <Link className="legal-back-link" href="/">Back to booking</Link>
        <h1>Privacy Policy</h1>
        <p className="muted">Last updated: July 5, 2026</p>

        <h2>Overview</h2>
        <p>
          Hybrid Stay Booking helps workers find and book short-term workday rooms
          from hosts. This policy explains what information we collect, why we use
          it, and how users can contact us about privacy requests.
        </p>

        <h2>Information We Collect</h2>
        <p>
          We collect account details such as name, email address, phone number,
          role, login/session information, booking rota dates, workspace details,
          host listing information, payment status, receipts, and support messages.
        </p>

        <h2>How We Use Information</h2>
        <p>
          We use information to create accounts, authenticate users, show available
          rooms, prevent double-booking, process payments, generate receipts,
          support hosts and workers, review listings, prevent abuse, and maintain
          platform security.
        </p>

        <h2>Payments</h2>
        <p>
          Payment processing is handled by our configured payment provider. We do
          not store card numbers or full payment instrument details on our servers.
          We store payment references, payment status, amounts, currency, and receipt
          information needed for bookings, support, and accounting.
        </p>

        <h2>Sharing</h2>
        <p>
          We share limited booking information between workers and hosts where
          necessary to complete a stay. We may share information with service
          providers such as hosting, database, email, analytics, error monitoring,
          and payment providers. We may disclose information if required by law or
          to protect users and the platform.
        </p>

        <h2>Retention</h2>
        <p>
          We retain account, booking, audit, payment, and receipt records for as
          long as needed to operate the service, meet legal obligations, resolve
          disputes, and prevent fraud. Users may request account review or deletion
          subject to legal and transactional retention requirements.
        </p>

        <h2>Your Choices</h2>
        <p>
          You can update your account profile in the app. For privacy access,
          correction, or deletion requests, contact support using the details on
          the Contact page.
        </p>

        <h2>Contact</h2>
        <p>
          Operator name, registered address, and final support email should be
          added before public launch. Until then, use the Contact page for pilot
          support instructions.
        </p>
      </section>
    </main>
  );
}
