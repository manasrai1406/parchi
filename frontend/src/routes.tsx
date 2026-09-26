import { Navigate, type RouteObject } from "react-router";

import { Layout } from "@/components/Layout";
import { FilesPage } from "@/pages/files/FilesPage";
import { NotFound } from "@/pages/NotFound";
import { QueryPage } from "@/pages/query/QueryPage";
import { ReviewPage } from "@/pages/review/ReviewPage";
import { ReviewQueue } from "@/pages/review/ReviewQueue";
import { UploadPage } from "@/pages/upload/UploadPage";

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/files" replace /> },
      { path: "upload", element: <UploadPage /> },
      { path: "files", element: <FilesPage /> },
      { path: "review", element: <ReviewQueue /> },
      { path: "review/:ref", element: <ReviewPage /> },
      { path: "query", element: <QueryPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
