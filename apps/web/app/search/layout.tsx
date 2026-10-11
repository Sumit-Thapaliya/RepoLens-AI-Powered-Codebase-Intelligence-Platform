/**
 * Search is nested under the app-wide root layout. Keep this segment layout
 * transparent so it never introduces a second <html> or <body> element.
 */
export default function SearchLayout({ children }: { children: React.ReactNode }) {
  return children;
}
