import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, IBM_Plex_Serif, Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-ui-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const plexSerif = IBM_Plex_Serif({
  variable: "--font-plex-serif",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  style: ["normal", "italic"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

const DIRECTION = `<!--
impeccable:direction
THESIS: A research desk, not a chat. The composer is a query slip at the
top of a working page; the answer is a skeleton argument whose numbered
authorities open in a bundle beside it. It refuses the bubble transcript
with a composer pinned to the bottom, and the enterprise results page of
blue links.
OWN-WORLD: A dark room and one sheet of light. Everything operated is
greyscale; the only colour is the amber highlighter across a matched
passage and the single control that acts. Inter operates the tool, a
serif reads the law, mono carries citations and dates. Hairline rules,
no cards, no shadows except the bundle lifting off the page.
STORY: A practitioner asks, sees what was consulted, reads a cited
answer, and verifies each authority without leaving the page - then
follows it to kenyalaw.org if it matters.
FIRST VIEWPORT: Header with the wordmark. Left rail of filters (260px).
Working page: the query slip with Search/Ask, then the answer or ranked
passages. The bundle slides in from the right on the first citation;
on a phone it rises from the bottom over the answer. Primary action: the
slip's Ask button.
FORM: Bundle of authorities on a law-report page; first of seven
candidates from the practitioner's world; code-led, no seed.
FINISH: unreviewed and undocumented is unfinished; this build ends with
the finish review, the verdict, DESIGN.md, and every shipping raster
carrying its provenance.
-->`;

export const metadata: Metadata = {
  title: "Wakili",
  description: "Legal research over Kenyan legislation and case law, with every answer cited.",
};

export const viewport: Viewport = {
  themeColor: "#0b0b0c",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${inter.variable} ${plexSerif.variable} ${plexMono.variable} h-full`}
    >
      <body className="min-h-full">
        {/* React strips JSX comments, so the direction contract is emitted as a
            real HTML comment the built output keeps and can be audited. */}
        <div hidden aria-hidden="true" dangerouslySetInnerHTML={{ __html: DIRECTION }} />
        {children}
      </body>
    </html>
  );
}
