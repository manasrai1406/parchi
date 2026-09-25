import { Navigate, type RouteObject } from "react-router";

import { Layout } from "@/components/Layout";
import { NotFound } from "@/pages/NotFound";
import { Placeholder } from "@/pages/Placeholder";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/files" replace /> },
      { path: "upload", element: <Placeholder eyebrow="Ingest" title="Upload" phase={2} /> },
      { path: "files", element: <Placeholder eyebrow="Status" title="Files" phase={2} /> },
      { path: "review", element: <Placeholder eyebrow="Fix" title="Review" phase={4} /> },
      { path: "query", element: <Placeholder eyebrow="Ask" title="Query" phase={7} /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
