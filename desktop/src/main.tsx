import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createRuntimeApi } from "./api/client";


async function start() {
  const api = await createRuntimeApi();
  createRoot(document.getElementById("root")!).render(
    <StrictMode><App api={api} /></StrictMode>
  );
}

void start();
