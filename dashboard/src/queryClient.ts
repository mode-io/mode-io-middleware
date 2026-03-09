import { QueryClient } from "@tanstack/react-query";

export function createDashboardQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        refetchOnWindowFocus: false,
        staleTime: 2_000,
      },
      mutations: {
        retry: false,
      },
    },
  });
}
