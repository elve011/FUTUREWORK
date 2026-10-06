import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FutureWork · Project & Tokenization",
  description: "Tableau de bord Dev 1 pour les projets et leur tokenisation.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
