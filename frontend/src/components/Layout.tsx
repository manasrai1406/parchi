import { Outlet } from "react-router";

import { Sidebar } from "./Sidebar";

export function Layout() {
  return (
    <div className="flex min-h-full">
      <Sidebar />
      <main className="flex min-w-0 grow flex-col gap-5 px-12 py-10">
        <Outlet />
      </main>
    </div>
  );
}
