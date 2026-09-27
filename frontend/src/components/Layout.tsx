import { Navigate, Outlet, useLocation } from "react-router";

import { useMe } from "@/auth/session";

import { Sidebar } from "./Sidebar";

/** Every page but Login: only for someone logged in, with a password of their own. */
export function Layout() {
  const { data: me, isPending, isError, error } = useMe();
  const location = useLocation();

  if (isPending) {
    return <p className="p-10 text-muted">Loading…</p>;
  }
  if (isError) {
    return (
      <p role="alert" className="p-10 text-flagged">
        Parchi could not be reached. {error instanceof Error ? error.message : ""}
      </p>
    );
  }
  if (!me) {
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  }
  if (me.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }

  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="flex min-w-0 grow flex-col gap-5 px-12 py-10">
        <Outlet />
      </main>
    </div>
  );
}
