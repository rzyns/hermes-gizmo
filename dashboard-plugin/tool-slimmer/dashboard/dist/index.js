(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { useEffect, useMemo, useState } = SDK.hooks;
  const { Badge, Button, Card, CardContent, CardHeader, CardTitle } = SDK.components;

  function fmtNumber(value) {
    return new Intl.NumberFormat().format(Math.round(Number(value || 0)));
  }

  function fmtTime(timestamp) {
    if (!timestamp) return "No selections recorded";
    return new Date(Number(timestamp) * 1000).toLocaleString();
  }

  function Metric({ label, value, detail }) {
    return React.createElement("div", { className: "tool-slimmer-metric" },
      React.createElement("div", { className: "tool-slimmer-metric-label" }, label),
      React.createElement("div", { className: "tool-slimmer-metric-value" }, value),
      detail && React.createElement("div", { className: "tool-slimmer-muted text-xs" }, detail),
    );
  }

  function ToolPills({ tools }) {
    const shown = (tools || []).slice(0, 8);
    return React.createElement("div", { className: "tool-slimmer-tools" },
      shown.map(function (tool) {
        return React.createElement("span", { key: tool, className: "tool-slimmer-pill" }, tool);
      }),
      (tools || []).length > shown.length &&
        React.createElement("span", { className: "tool-slimmer-pill" }, "+" + String(tools.length - shown.length)),
    );
  }

  function useToolSlimmerData() {
    const [state, setState] = useState({ loading: true, error: null, status: null, summary: null });

    function load() {
      setState(function (prev) { return Object.assign({}, prev, { loading: true, error: null }); });
      Promise.all([
        SDK.fetchJSON("/api/plugins/tool-slimmer/status"),
        SDK.fetchJSON("/api/plugins/tool-slimmer/summary?limit=1000"),
      ]).then(function (results) {
        setState({ loading: false, error: null, status: results[0], summary: results[1].summary });
      }).catch(function (error) {
        setState(function (prev) {
          return Object.assign({}, prev, { loading: false, error: error && error.message ? error.message : "LOAD_FAILED" });
        });
      });
    }

    useEffect(function () {
      load();
    }, []);

    return Object.assign({}, state, { reload: load });
  }

  function ToolSlimmerPage() {
    const data = useToolSlimmerData();
    const summary = data.summary || {};
    const totals = summary.totals || {};
    const averages = summary.averages || {};
    const config = (data.status && data.status.config) || {};
    const index = (data.status && data.status.index) || {};
    const doctor = (data.status && data.status.doctor && data.status.doctor.checks) || {};
    const recent = summary.recent || [];

    const topTools = useMemo(function () {
      return Object.entries(summary.top_selected_tools || {}).slice(0, 10);
    }, [summary.top_selected_tools]);

    return React.createElement("div", { className: "tool-slimmer-page flex flex-col gap-6" },
      React.createElement("div", { className: "flex flex-wrap items-center justify-between gap-3" },
        React.createElement("div", { className: "flex flex-col gap-1" },
          React.createElement("div", { className: "flex flex-wrap items-center gap-2" },
            React.createElement("h1", { className: "text-xl font-semibold" }, "Tool Slimmer"),
            React.createElement(Badge, { variant: config.enabled ? "default" : "outline" }, config.enabled ? "enabled" : "disabled"),
            config.dry_run && React.createElement(Badge, { variant: "outline" }, "dry run"),
          ),
          React.createElement("div", { className: "tool-slimmer-muted text-sm" },
            "Last selector event: ", fmtTime(summary.last_event_at),
          ),
        ),
        React.createElement(Button, { onClick: data.reload, disabled: data.loading }, data.loading ? "Refreshing" : "Refresh"),
      ),

      data.error && React.createElement(Card, { className: "border-destructive" },
        React.createElement(CardContent, { className: "py-4 text-sm" }, "Tool Slimmer API is not available: ", data.error),
      ),

      React.createElement("div", { className: "tool-slimmer-grid" },
        React.createElement(Metric, {
          label: "Estimated Schema Tokens Saved",
          value: fmtNumber(totals.approx_tokens_saved),
          detail: fmtNumber(totals.approx_tokens_before) + " before / " + fmtNumber(totals.approx_tokens_after) + " after",
        }),
        React.createElement(Metric, {
          label: "Schema Bytes Saved",
          value: fmtNumber(totals.schema_bytes_saved),
          detail: fmtNumber(totals.schema_bytes_before) + " before / " + fmtNumber(totals.schema_bytes_after) + " after",
        }),
        React.createElement(Metric, {
          label: "Average Reduction",
          value: String(averages.reduction_percent || 0) + "%",
          detail: String(averages.selected_tools || 0) + " selected of " + String(averages.total_tools || 0) + " tools",
        }),
        React.createElement(Metric, {
          label: "Selections Logged",
          value: fmtNumber(totals.events),
          detail: String(summary.ignored_events || 0) + " probe events excluded",
        }),
      ),

      React.createElement(Card, null,
        React.createElement(CardContent, { className: "py-3 text-xs tool-slimmer-muted" },
          "Savings are schema-overhead estimates from serialized tool-schema JSON bytes / 4. ",
          "Actual provider input tokens and billing can differ because tokenizers, prompt caching, system prompts, conversation history, and provider serialization vary.",
        ),
      ),

      React.createElement("div", { className: "grid gap-4 lg:grid-cols-2" },
        React.createElement(Card, null,
          React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Runtime")),
          React.createElement(CardContent, { className: "grid gap-3 text-sm" },
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Mode"),
              React.createElement("span", { className: "font-courier" }, config.mode || "unknown"),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Top K"),
              React.createElement("span", { className: "font-courier" }, String(config.top_k ?? "unknown")),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Indexed Tools"),
              React.createElement("span", { className: "font-courier" }, String(index.total_tools || 0)),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Decision Logging"),
              React.createElement("span", { className: "font-courier" }, config.log_decisions ? "on" : "off"),
            ),
          ),
        ),
        React.createElement(Card, null,
          React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Health Checks")),
          React.createElement(CardContent, { className: "grid gap-2 text-sm" },
            Object.entries(doctor).length === 0 && React.createElement("div", { className: "tool-slimmer-muted" }, "No doctor data available"),
            Object.entries(doctor).map(function ([name, check]) {
              return React.createElement("div", { key: name, className: "flex items-start justify-between gap-3 border-b border-border pb-2" },
                React.createElement("div", null,
                  React.createElement("div", { className: "font-medium" }, name.replaceAll("_", " ")),
                  React.createElement("div", { className: "tool-slimmer-muted text-xs" }, check.message),
                ),
                React.createElement(Badge, { variant: check.status === "pass" ? "default" : "outline" }, check.status),
              );
            }),
          ),
        ),
      ),

      React.createElement(Card, null,
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Most Selected Tools")),
        React.createElement(CardContent, null,
          topTools.length === 0
            ? React.createElement("div", { className: "tool-slimmer-muted text-sm" }, "No selections have been recorded yet.")
            : React.createElement("div", { className: "tool-slimmer-tools" },
                topTools.map(function ([tool, count]) {
                  return React.createElement("span", { key: tool, className: "tool-slimmer-pill" }, tool + " x" + count);
                }),
              ),
        ),
      ),

      React.createElement(Card, null,
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Recent Decisions")),
        React.createElement(CardContent, { className: "overflow-x-auto" },
          React.createElement("table", { className: "tool-slimmer-table" },
            React.createElement("thead", null,
              React.createElement("tr", null,
                React.createElement("th", null, "Time"),
                React.createElement("th", null, "Mode"),
                React.createElement("th", null, "Reduction"),
                React.createElement("th", null, "Tools"),
                React.createElement("th", null, "Selected"),
              ),
            ),
            React.createElement("tbody", null,
              recent.slice().reverse().map(function (event, idx) {
                const metrics = event.metrics || {};
                return React.createElement("tr", { key: String(event.timestamp || idx) },
                  React.createElement("td", null, fmtTime(event.timestamp)),
                  React.createElement("td", { className: "font-courier" }, metrics.mode || "unknown"),
                  React.createElement("td", null, String(metrics.estimated_reduction_percent || 0) + "%"),
                  React.createElement("td", null, String(metrics.selected_tools || 0), " / ", String(metrics.total_tools || 0)),
                  React.createElement("td", null, React.createElement(ToolPills, { tools: metrics.selected || [] })),
                );
              }),
              recent.length === 0 && React.createElement("tr", null,
                React.createElement("td", { colSpan: 5, className: "tool-slimmer-muted" }, "No selector decisions recorded yet."),
              ),
            ),
          ),
        ),
      ),
    );
  }

  window.__HERMES_PLUGINS__.register("tool-slimmer", ToolSlimmerPage);
})();
