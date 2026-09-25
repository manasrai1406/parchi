import { Navigate, type RouteObject } from "react-router";

import { Layout } from "@/components/Layout";
import { FilesPage } from "@/pages/files/FilesPage";
import { NotFound } from "@/pages/NotFound";
import { Placeholder } from "@/pages/Placeholder";
import { UploadPage } from "@/pages/upload/UploadPage";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/files" replace /> },
      { path: "upload", element: <UploadPage /> },
      { path: "files", element: <FilesPage /> },
      { path: "review", element: <Placeholder eyebrow="Fix" title="Review" phase={4} /> },
      { path: "query", element: <Placeholder eyebrow="Ask" title="Query" phase={7} /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
