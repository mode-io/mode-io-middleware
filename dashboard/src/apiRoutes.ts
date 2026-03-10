export const modeioMonitoringRoutes = {
  events: "/modeio/api/v1/events",
  eventDetail: (requestId: string) => `/modeio/api/v1/events/${requestId}`,
  liveEvents: "/modeio/api/v1/events/live",
  stats: "/modeio/api/v1/stats",
} as const;

export const modeioAdminRoutes = {
  plugins: "/modeio/admin/v1/plugins",
  profilePlugins: (profileName: string) => `/modeio/admin/v1/profiles/${profileName}/plugins`,
} as const;
