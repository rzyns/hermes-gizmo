(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  const { React } = SDK;
  const { useEffect, useMemo, useState } = SDK.hooks;
  const { Badge, Button, Card, CardContent, CardHeader, CardTitle } = SDK.components;

  function fmtNumber(value) {
    const number = Number(value || 0);
    return new Intl.NumberFormat().format(Number.isFinite(number) ? Math.round(number) : 0);
  }

  function fmtTime(timestamp) {
    if (!timestamp) return "No selections recorded";
    return new Date(Number(timestamp) * 1000).toLocaleString();
  }

  function fmtIndexTime(timestamp) {
    if (!timestamp) return "Never rebuilt";
    return new Date(Number(timestamp) * 1000).toLocaleString();
  }

  function shortChecksum(value) {
    return value ? String(value).slice(0, 12) : "none";
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
    const [state, setState] = useState({ loading: true, error: null, status: null, summary: null, indexInfo: null, advisor: null, privacy: null });

    function load() {
      setState(function (prev) { return Object.assign({}, prev, { loading: true, error: null }); });
      Promise.all([
        SDK.fetchJSON("/api/plugins/tool-slimmer/status"),
        SDK.fetchJSON("/api/plugins/tool-slimmer/summary?limit=1000"),
        SDK.fetchJSON("/api/plugins/tool-slimmer/index"),
        SDK.fetchJSON("/api/plugins/tool-slimmer/advisor?limit=1000"),
        SDK.fetchJSON("/api/plugins/tool-slimmer/privacy"),
      ]).then(function (results) {
        setState({ loading: false, error: null, status: results[0], summary: results[1].summary, indexInfo: results[2].index, advisor: results[3].advisor, privacy: results[4].privacy });
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
    const [indexBusy, setIndexBusy] = useState(false);
    const [indexMessage, setIndexMessage] = useState(null);
    const [evalBusy, setEvalBusy] = useState(false);
    const [evalReport, setEvalReport] = useState(null);
    const [evalError, setEvalError] = useState(null);
    const summary = data.summary || {};
    const totals = summary.totals || {};
    const averages = summary.averages || {};
    const config = (data.status && data.status.config) || {};
    const statusIndex = (data.status && data.status.index) || {};
    const index = data.indexInfo || statusIndex || {};
    const doctor = (data.status && data.status.doctor && data.status.doctor.checks) || {};
    const recent = summary.recent || [];
    const indexDocs = index.documents || [];
    const advisor = data.advisor || {};
    const privacy = data.privacy || {};
    const recommendations = advisor.recommendations || [];
    const latestDecision = recent.length ? recent[recent.length - 1] : null;
    const latestMetrics = latestDecision && latestDecision.metrics ? latestDecision.metrics : {};
    const latestCandidates = latestDecision && latestDecision.metrics && latestDecision.metrics.top_candidates
      ? latestDecision.metrics.top_candidates
      : [];

    const topTools = useMemo(function () {
      return Object.entries(summary.top_selected_tools || {}).slice(0, 10);
    }, [summary.top_selected_tools]);

    function rebuildIndex() {
      setIndexBusy(true);
      setIndexMessage(null);
      SDK.fetchJSON("/api/plugins/tool-slimmer/index/rebuild", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }).then(function (result) {
        const rebuilt = result.index || {};
        setIndexMessage("Indexed " + String(rebuilt.total_tools || 0) + " tools from " + String(result.source || "Hermes") + ".");
        data.reload();
      }).catch(function (error) {
        const message = error && error.message ? error.message : "Index rebuild failed";
        setIndexMessage(message);
      }).finally(function () {
        setIndexBusy(false);
      });
    }

    function generateEvalReport() {
      setEvalBusy(true);
      setEvalError(null);
      SDK.fetchJSON("/api/plugins/tool-slimmer/eval-report").then(function (result) {
        setEvalReport(result.report || {});
      }).catch(function (error) {
        setEvalError(error && error.message ? error.message : "Eval report failed");
      }).finally(function () {
        setEvalBusy(false);
      });
    }

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
        React.createElement(Metric, {
          label: "Selector Overhead",
          value: (Number.isFinite(Number(averages.selection_ms || 0)) ? Number(averages.selection_ms || 0) : 0).toFixed(2) + " ms",
          detail: fmtNumber(totals.skipped_events || 0) + " low-value selections skipped",
        }),
        React.createElement(Metric, {
          label: "Anthropic Deferred",
          value: fmtNumber(latestMetrics.anthropic_deferred_tools),
          detail: latestMetrics.metric_basis === "hot_set"
            ? "Latest event measured against hot set"
            : "No hot-set event recorded",
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
              React.createElement("span", { className: "font-courier" }, String(statusIndex.total_tools || index.total_tools || 0)),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Decision Logging"),
              React.createElement("span", { className: "font-courier" }, config.log_decisions ? "on" : "off"),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Minimum Tools"),
              React.createElement("span", { className: "font-courier" }, String(config.min_total_tools ?? 0)),
            ),
            React.createElement("div", { className: "flex justify-between gap-3" },
              React.createElement("span", { className: "tool-slimmer-muted" }, "Minimum Reduction"),
              React.createElement("span", { className: "font-courier" }, String(config.min_estimated_reduction_percent ?? 0) + "%"),
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

      React.createElement("div", { className: "grid gap-4 lg:grid-cols-2" },
        React.createElement(Card, null,
          React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Config Advisor")),
          React.createElement(CardContent, { className: "grid gap-3 text-sm" },
            recommendations.length === 0 && React.createElement("div", { className: "tool-slimmer-muted" }, "No recommendations from recent selector activity."),
            recommendations.map(function (item) {
              return React.createElement("div", { key: item.id, className: "flex items-start justify-between gap-3 border-b border-border pb-2" },
                React.createElement("div", null,
                  React.createElement("div", { className: "font-medium" }, String(item.id || "").replaceAll("_", " ")),
                  React.createElement("div", { className: "tool-slimmer-muted text-xs" }, item.message),
                ),
                React.createElement(Badge, { variant: item.severity === "warn" ? "outline" : "default" }, item.severity || "info"),
              );
            }),
          ),
        ),
        React.createElement(Card, null,
          React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Decision Inspector")),
          React.createElement(CardContent, { className: "grid gap-2 text-sm" },
            latestCandidates.length === 0 && React.createElement("div", { className: "tool-slimmer-muted" }, "No score details recorded yet."),
            latestCandidates.slice(0, 6).map(function (candidate) {
              const details = candidate.details || {};
              return React.createElement("div", { key: candidate.name, className: "tool-slimmer-score-row" },
                React.createElement("div", { className: "flex justify-between gap-3" },
                  React.createElement("span", { className: "font-courier" }, candidate.name),
                  React.createElement("span", null, (Number.isFinite(Number(candidate.score || 0)) ? Number(candidate.score || 0) : 0).toFixed(2)),
                ),
                React.createElement("div", { className: "tool-slimmer-muted text-xs" },
                  "bm25 ", (Number.isFinite(Number(details.bm25 || 0)) ? Number(details.bm25 || 0) : 0).toFixed(2),
                  " / name ", (Number.isFinite(Number(details.name_boost || 0)) ? Number(details.name_boost || 0) : 0).toFixed(2),
                  " / toolset ", (Number.isFinite(Number(details.toolset_boost || 0)) ? Number(details.toolset_boost || 0) : 0).toFixed(2),
                  " / params ", (Number.isFinite(Number(details.parameter_boost || 0)) ? Number(details.parameter_boost || 0) : 0).toFixed(2),
                  " / alias ", (Number.isFinite(Number(details.alias_boost || 0)) ? Number(details.alias_boost || 0) : 0).toFixed(2),
                  " / hybrid ", (Number.isFinite(Number(details.hybrid_boost || 0)) ? Number(details.hybrid_boost || 0) : 0).toFixed(2),
                ),
              );
            }),
          ),
        ),
      ),

      React.createElement(Card, null,
        React.createElement(CardHeader, null, React.createElement(CardTitle, null, "Privacy")),
        React.createElement(CardContent, { className: "grid gap-3 text-sm" },
          React.createElement("div", { className: "flex flex-wrap gap-2" },
            React.createElement(Badge, { variant: privacy.raw_prompts_logged ? "outline" : "default" }, privacy.raw_prompts_logged ? "raw prompts logged" : "raw prompts not logged"),
            React.createElement(Badge, { variant: "outline" }, "session events only in headline"),
          ),
          React.createElement("div", { className: "tool-slimmer-path" }, privacy.decision_log_path || "No decision log path available"),
          React.createElement("div", { className: "tool-slimmer-muted text-xs" },
            "Logged fields: ", ((privacy.event_fields || []).concat(privacy.context_fields || []).concat(privacy.metric_fields || [])).slice(0, 18).join(", "),
            ((privacy.metric_fields || []).length > 12) ? "..." : "",
          ),
        ),
      ),

      React.createElement(Card, null,
        React.createElement(CardHeader, { className: "flex flex-row items-center justify-between gap-3" },
          React.createElement(CardTitle, null, "Release Evidence"),
          React.createElement(Button, { onClick: generateEvalReport, disabled: evalBusy }, evalBusy ? "Generating" : "Generate Eval Report"),
        ),
        React.createElement(CardContent, { className: "grid gap-3 text-sm" },
          !evalReport && !evalError && React.createElement("div", { className: "tool-slimmer-muted" }, "Generate the example prompt/schema evaluation report from the dashboard."),
          evalError && React.createElement("div", { className: "tool-slimmer-muted" }, evalError),
          evalReport && evalReport.summary && React.createElement("div", { className: "tool-slimmer-index-grid" },
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Hit Rate"),
              React.createElement("div", { className: "font-medium" }, String(evalReport.summary.hit_rate)),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Average Reduction"),
              React.createElement("div", { className: "font-medium" }, String(evalReport.summary.average_reduction_percent || 0) + "%"),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Average Selected"),
              React.createElement("div", { className: "font-medium" }, String(evalReport.summary.average_selected_tools || 0)),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Fail Open"),
              React.createElement("div", { className: "font-medium" }, String(evalReport.summary.fail_open_count || 0)),
            ),
          ),
          evalReport && evalReport.rows && React.createElement("div", { className: "tool-slimmer-tools" },
            evalReport.rows.map(function (row) {
              return React.createElement("span", { key: row.name, className: "tool-slimmer-pill" }, String(row.name) + " " + String(row.expected_included));
            }),
          ),
        ),
      ),

      React.createElement(Card, null,
        React.createElement(CardHeader, { className: "flex flex-row items-center justify-between gap-3" },
          React.createElement(CardTitle, null, "Tool Index"),
          React.createElement("div", { className: "flex items-center gap-2" },
            React.createElement(Button, { variant: "outline", onClick: data.reload, disabled: data.loading || indexBusy }, "Refresh"),
            React.createElement(Button, { onClick: rebuildIndex, disabled: indexBusy }, indexBusy ? "Rebuilding" : "Rebuild From Hermes Tools"),
          ),
        ),
        React.createElement(CardContent, { className: "grid gap-4 text-sm" },
          React.createElement("div", { className: "tool-slimmer-index-grid" },
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Status"),
              React.createElement("div", { className: "font-medium" }, index.exists ? "Ready" : "Not built"),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Tools"),
              React.createElement("div", { className: "font-medium" }, String(index.total_tools || 0)),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Updated"),
              React.createElement("div", { className: "font-medium" }, fmtIndexTime(index.updated_at)),
            ),
            React.createElement("div", null,
              React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "Checksum"),
              React.createElement("div", { className: "font-courier" }, shortChecksum(index.checksum)),
            ),
          ),
          React.createElement("div", { className: "tool-slimmer-path" }, index.path || "No index path available"),
          React.createElement("div", { className: "tool-slimmer-muted text-xs" },
            index.live_selection && index.live_selection.message
              ? index.live_selection.message
              : "Hermes selection ranks the live request tool schemas in memory; the persisted index is for inspection, audits, and troubleshooting.",
          ),
          indexMessage && React.createElement("div", { className: "tool-slimmer-muted text-xs" }, indexMessage),
          indexDocs.length === 0
            ? React.createElement("div", { className: "tool-slimmer-muted text-sm" }, "No indexed tools to preview yet.")
            : React.createElement("div", { className: "tool-slimmer-tools" },
                indexDocs.slice(0, 18).map(function (doc) {
                  const label = doc.toolset ? doc.toolset + "." + doc.name : doc.name;
                  return React.createElement("span", { key: label, className: "tool-slimmer-pill" }, label + " " + String(doc.token_count || 0));
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
                  React.createElement("td", null,
                    String(metrics.estimated_reduction_percent || 0) + "%",
                    metrics.skipped && React.createElement("div", { className: "tool-slimmer-muted text-xs" }, metrics.skip_reason || "skipped"),
                    metrics.metric_basis && React.createElement("div", { className: "tool-slimmer-muted text-xs" }, "basis: ", metrics.metric_basis),
                  ),
                  React.createElement("td", null,
                    String(metrics.selected_tools || 0), " / ", String(metrics.total_tools || 0),
                    metrics.anthropic_payload_tools && React.createElement("div", { className: "tool-slimmer-muted text-xs" },
                      String(metrics.anthropic_deferred_tools || 0), " deferred / ", String(metrics.anthropic_payload_tools || 0), " payload",
                    ),
                  ),
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
