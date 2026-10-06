import type { Metadata } from "next";
import "./globals.css";
import "./auth.css";

export const metadata: Metadata = {
  title: "FUTUREWORK · AI Command Center",
  description: "Project monitoring, agent activity, audit trails and Hedera settlement status.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
