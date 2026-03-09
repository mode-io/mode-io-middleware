import type { Locale } from "./types";

const COPY = {
  en: {
    toolbar: {
      title: "ModeIO Monitor",
      refresh: "Refresh",
      language: "Lang",
      theme: "Theme",
      day: "Day",
      night: "Night",
      demoBadge: "example data",
    },
    stats: {
      traces: "Traces",
      inFlight: "In flight",
      modified: "Modified",
      blocked: "Blocked",
      errors: "Errors",
      p50: "p50",
      p95: "p95",
    },
    table: {
      listTitle: "Trace stream",
      listSubtitle: "Recent middleware activity",
      status: "Outcome",
      client: "Client",
      lifecycle: "Lifecycle",
      impact: "Impact",
      plugin: "Plugin",
      duration: "Duration",
      requestId: "Request ID",
      time: "Time",
      loading: "Loading traces...",
      empty: "No traces match the current filters.",
      demoNote: "Showing example traces. Live data will replace these automatically.",
    },
    inspector: {
      title: "Trace inspector",
      subtitle: "Selected request detail",
      profile: "Profile",
      client: "Client",
      lifecycle: "Lifecycle",
      impact: "Impact",
      pluginSummary: "Plugin summary",
      upstream: "Upstream",
      notCaptured: "Not captured",
      emptyTitle: "No trace selected",
      emptyNote: "Select a row from the table to inspect its details.",
      loading: "Loading...",
      tabRequest: "Request",
      tabResponse: "Response",
      tabHooks: "Hooks",
      tabContext: "Context",
      tabRaw: "Raw",
      before: "Before",
      after: "After",
      change: "Change summary",
      unchanged: "No changes",
      plugin: "Plugin",
      hook: "Hook",
      reported: "Reported",
      effective: "Effective",
      time: "Time",
      noHooks: "No hook executions recorded.",
      preActions: "Pre actions",
      postActions: "Post actions",
      degraded: "Degraded",
      findings: "Findings",
      blockReason: "Block reason",
      errorMessage: "Error",
      none: "None",
      stream: "Stream",
      events: "events",
      streamBlocked: "blocked during stream",
      streamDone: "done received",
    },
    filters: {
      all: "All",
      status: "Outcome",
      client: "Client",
      lifecycle: "Lifecycle",
      impact: "Impact",
      clear: "Clear filters",
      showingAll: "All traces visible",
      activeFilters: "Active filters",
    },
    common: {
      completed: "completed",
      blocked: "blocked",
      error: "error",
      streamCompleted: "stream",
      allow: "allow",
      modify: "modify",
      warn: "warn",
      block: "block",
      passThrough: "pass-through",
      modified: "modified",
      warned: "warned",
      mixed: "mixed",
      claudeCode: "Claude Code",
      codex: "Codex CLI",
      opencode: "OpenCode",
      openclaw: "OpenClaw",
      noIntervention: "no intervention",
      preRequest: "pre-request",
      postResponse: "post-response",
      preAndPost: "pre + post",
      stream: "stream",
      preAndStream: "pre + stream",
      unknown: "unknown",
    },
  },
  zh: {
    toolbar: {
      title: "ModeIO 监控台",
      refresh: "刷新",
      language: "语言",
      theme: "主题",
      day: "浅色",
      night: "夜间",
      demoBadge: "示例数据",
    },
    stats: {
      traces: "轨迹",
      inFlight: "处理中",
      modified: "已改写",
      blocked: "已拦截",
      errors: "错误",
      p50: "p50",
      p95: "p95",
    },
    table: {
      listTitle: "轨迹流",
      listSubtitle: "最近的中间件活动",
      status: "结果",
      client: "客户端",
      lifecycle: "处理环节",
      impact: "影响",
      plugin: "插件",
      duration: "耗时",
      requestId: "请求 ID",
      time: "时间",
      loading: "正在加载轨迹...",
      empty: "当前筛选条件下没有轨迹。",
      demoNote: "当前展示的是示例轨迹，真实流量进入后会自动替换。",
    },
    inspector: {
      title: "轨迹详情",
      subtitle: "当前选中请求",
      profile: "配置",
      client: "客户端",
      lifecycle: "处理环节",
      impact: "影响",
      pluginSummary: "插件摘要",
      upstream: "上游",
      notCaptured: "未捕获",
      emptyTitle: "未选择轨迹",
      emptyNote: "从表格中选择一行以查看其详情。",
      loading: "加载中...",
      tabRequest: "请求",
      tabResponse: "响应",
      tabHooks: "处理步骤",
      tabContext: "上下文",
      tabRaw: "原始数据",
      before: "处理前",
      after: "处理后",
      change: "变化摘要",
      unchanged: "无变化",
      plugin: "插件",
      hook: "Hook",
      reported: "原始动作",
      effective: "生效动作",
      time: "耗时",
      noHooks: "没有记录到处理步骤。",
      preActions: "前置动作",
      postActions: "后置动作",
      degraded: "降级信息",
      findings: "发现项",
      blockReason: "拦截原因",
      errorMessage: "错误",
      none: "无",
      stream: "流式",
      events: "事件",
      streamBlocked: "流式中被拦截",
      streamDone: "已收到结束信号",
    },
    filters: {
      all: "全部",
      status: "结果",
      client: "客户端",
      lifecycle: "处理环节",
      impact: "影响",
      clear: "清除筛选",
      showingAll: "当前显示全部轨迹",
      activeFilters: "当前筛选条件",
    },
    common: {
      completed: "已完成",
      blocked: "已拦截",
      error: "错误",
      streamCompleted: "流式",
      allow: "放行",
      modify: "改写",
      warn: "告警",
      block: "拦截",
      passThrough: "直通",
      modified: "已改写",
      warned: "已告警",
      mixed: "混合",
      claudeCode: "Claude Code",
      codex: "Codex CLI",
      opencode: "OpenCode",
      openclaw: "OpenClaw",
      noIntervention: "未介入",
      preRequest: "请求前",
      postResponse: "响应后",
      preAndPost: "前后双向",
      stream: "流式",
      preAndStream: "请求前 + 流式",
      unknown: "未知",
    },
  },
} as const;

export function getCopy(locale: Locale) {
  return COPY[locale];
}

export function fmtStatus(status: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = { completed: c.completed, blocked: c.blocked, error: c.error, stream_completed: c.streamCompleted };
  return map[status] ?? status;
}

export function fmtClient(clientName: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    claude_code: c.claudeCode,
    codex: c.codex,
    opencode: c.opencode,
    openclaw: c.openclaw,
  };
  return map[clientName] ?? c.unknown;
}

export function fmtLifecycle(lifecycle: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    none: c.noIntervention,
    pre_request: c.preRequest,
    post_response: c.postResponse,
    pre_and_post: c.preAndPost,
    stream: c.stream,
    pre_and_stream: c.preAndStream,
  };
  return map[lifecycle] ?? (lifecycle || c.unknown);
}

export function fmtImpact(impact: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = {
    pass_through: c.passThrough,
    modified: c.modified,
    blocked: c.blocked,
    warned: c.warned,
    mixed: c.mixed,
  };
  return map[impact] ?? impact;
}

export function fmtAction(action: string, locale: Locale): string {
  const c = getCopy(locale).common;
  const map: Record<string, string> = { allow: c.allow, modify: c.modify, warn: c.warn, block: c.block };
  return map[action] ?? action;
}

export function fmtFilterMatchCount(count: number, locale: Locale): string {
  if (locale === "zh") {
    return `匹配 ${count} 条`;
  }
  return `${count} ${count === 1 ? "match" : "matches"}`;
}
