import type { Metadata, Viewport } from "next";
import { Syne, Crimson_Pro, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";

// =============================================================================
// FONTS — Design System v4.0
// =============================================================================

const syne = Syne({
  subsets: ["latin"],
  variable: "--font-syne",
  display: "swap",
  weight: ["400", "500", "600", "700", "800"],
});

const crimson = Crimson_Pro({
  subsets: ["latin"],
  variable: "--font-crimson",
  display: "swap",
  weight: ["400", "500", "600", "700"],
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
  weight: ["400", "500", "600"],
});

// =============================================================================
// METADATA
// =============================================================================

export const metadata: Metadata = {
  title: "DOU · Diário Oficial Reimaginado",
  description: "O feed do poder no Brasil. Toda nomeação, contrato e portaria em uma experiência digna dos melhores apps.",
  keywords: ["DOU", "Diário Oficial", "busca jurídica", "atos oficiais", "portarias"],
  authors: [{ name: "GABI" }],
  manifest: "/manifest.json",
  icons: {
    icon: "/favicon.ico",
    apple: "/apple-touch-icon.png",
  },
  openGraph: {
    type: "website",
    title: "DOU · Diário Oficial Reimaginado",
    description: "O feed do poder no Brasil.",
    siteName: "DOU Reimaginado",
  },
  twitter: {
    card: "summary_large_image",
    title: "DOU · Diário Oficial Reimaginado",
    description: "O feed do poder no Brasil.",
  },
};

export const viewport: Viewport = {
  themeColor: "#07070F",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

// =============================================================================
// ROOT LAYOUT
// =============================================================================

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="pt-BR"
      className={`${syne.variable} ${crimson.variable} ${jetbrains.variable}`}
      suppressHydrationWarning
    >
      <body className="antialiased bg-canvas text-primary min-h-screen">
        <Providers>
          {children}
        </Providers>
      </body>
    </html>
  );
}
