import { Spinner } from "@/components/ui/feedback";

/** Shown while a dynamic page renders on the server during navigation, so
 * moving between pages reads as a brief loading beat rather than a frozen UI.
 * Every workspace page is force-dynamic, so each navigation does a server
 * round-trip this covers. */
export default function Loading() {
  return (
    <main className="flex min-h-screen items-center justify-center">
      <Spinner className="h-6 w-6" />
    </main>
  );
}
