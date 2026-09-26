import type { Metadata } from "next";
import { Exo_2, Geist_Mono } from "next/font/google";
import "./globals.css";

// Variable font: omitting `weight` loads the whole 100-900 range in one file.
const exo2 = Exo_2({
  variable: "--font-exo2",
  subsets: ["latin"],
  style: ["normal", "italic"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Policy Data Analytics",
  description: "Ask questions about Singapore government datasets",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${exo2.variable} ${geistMono.variable}`}>
      <body>{children}</body>
    </html>
  );
}
