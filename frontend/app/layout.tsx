import type { Metadata } from "next";
import { ClientMonitoring } from "./client-monitoring";
import "./globals.css";

export const metadata: Metadata = {
  title: "Hybrid Stay Booking",
  description: "Book affordable workday stays around your office rota.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <ClientMonitoring />
        {children}
      </body>
    </html>
  );
}
