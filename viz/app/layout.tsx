import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MARQUEE — market microstructure sandbox",
  description:
    "Live limit-order-book simulation: emergent price discovery, liquidity dynamics, and flash crashes from agent interaction.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
