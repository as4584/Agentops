import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "WebGen ML Lab",
  description: "Visual drift monitor for Agentop WebGen training",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
