import { Navigate, type RouteObject } from "react-router";

import { Layout } from "@/components/Layout";
import { FilesPage } from "@/pages/files/FilesPage";
import { ChangePasswordPage } from "@/pages/login/ChangePasswordPage";
import { LoginPage } from "@/pages/login/LoginPage";
import { NotFound } from "@/pages/NotFound";
import { QueryPage } from "@/pages/query/QueryPage";
import { ReviewPage } from "@/pages/review/ReviewPage";
import { ReviewQueue } from "@/pages/review/ReviewQueue";
import { UploadPage } from "@/pages/upload/UploadPage";
import { UsersPage } from "@/pages/users/UsersPage";

export const routes: RouteObject[] = [
  // Outside the Layout: no sidebar, and reachable before a password of one's own is set.
  { path: "login", element: <LoginPage /> },
  { path: "change-password", element: <ChangePasswordPage /> },
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/files" replace /> },
      { path: "upload", element: <UploadPage /> },
      { path: "files", element: <FilesPage /> },
      { path: "review", element: <ReviewQueue /> },
      { path: "review/:ref", element: <ReviewPage /> },
      { path: "query", element: <QueryPage /> },
      { path: "users", element: <UsersPage /> },
      { path: "*", element: <NotFound /> },
    ],
  },
];
