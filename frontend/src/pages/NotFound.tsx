import { Link } from "react-router";

import { PageHeader } from "@/components/PageHeader";

export function NotFound() {
  return (
    <>
      <PageHeader eyebrow="Error" title="Page not found" />
      <Link
        to="/files"
        className="inline-flex min-h-11 items-center text-accent-text underline underline-offset-4"
      >
        Go to Files
      </Link>
    </>
  );
}
