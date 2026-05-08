// Analyze page (the original home). Routed under `/` so existing
// bookmarks keep working; the route group `(shell)` is invisible to
// the URL.
//
// Backend probe used to live here — it's been hoisted to the shell
// layout so /history shares it. The page itself is now a one-line
// re-export of the client island; everything stateful happens inside
// `<AnalyzeShell />`.

import { AnalyzeShell } from "../../components/AnalyzeShell";

export default function AnalyzePage() {
  return <AnalyzeShell />;
}
