"use client";

import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "@/lib/api-client";
import { useAuth } from "@/lib/auth-context";
import { parseCsv } from "./csv";

interface Organization {
  id: string;
  name: string;
}

interface Workspace {
  id: string;
  organization_id: string;
  name: string;
}

interface Source {
  id: string;
  organization_id: string;
  workspace_id: string | null;
  name: string;
  connector_type: string;
  classification: string;
  status: string;
  description: string;
  connection_config: Record<string, unknown>;
  created_at: string;
}

interface SourceEvent {
  id: string;
  event_type: string;
  status: string;
  detail: string;
  rows_ingested: number | null;
  rows_rejected: number | null;
  latency_ms: number | null;
  occurred_at: string;
}

interface Dataset {
  id: string;
  source_id: string;
  name: string;
  domain: string;
  classification: string;
  schema_summary: Record<string, string>;
  row_count: number;
  last_synced_at: string | null;
}

interface EnterpriseRecord {
  id: string;
  row_data: Record<string, unknown>;
  ingested_at: string;
}

interface Entitlement {
  id: string;
  dataset_id: string;
  principal_type: string;
  principal_id: string;
  granted_by: string | null;
  granted_at: string;
}

const CONNECTOR_TYPES = ["MANUAL_UPLOAD", "REST_API", "SFTP", "DATABASE", "S3", "WEBHOOK"];
const CLASSIFICATIONS = [
  "PUBLIC",
  "LICENSED_MARKET_DATA",
  "ALPHAGASIQ_PROPRIETARY",
  "CUSTOMER_CONFIDENTIAL",
  "CUSTOMER_RESTRICTED",
  "CUSTOMER_POSITION_DATA",
  "CUSTOMER_RISK_DATA",
  "SIMULATED",
];
const DOMAINS = [
  "MARKET_PRICE", "PRODUCTION", "DEMAND", "WEATHER", "STORAGE", "PIPELINE", "TRANSPORTATION",
  "LNG", "POWER", "NEWS_EVENT", "POSITION", "PORTFOLIO", "HEDGE", "CONTRACT", "RISK",
  "FORECAST", "SCENARIO", "ASSET", "FACILITY", "NODE", "FLOW",
];
const PRINCIPAL_TYPES = ["USER", "ROLE", "WORKSPACE", "AGENT"];

const STATUS_COLOR: Record<string, string> = {
  success: "text-terminal-bull",
  error: "text-terminal-bear",
  healthy: "text-terminal-bull",
  degraded: "text-terminal-warn",
  not_configured: "text-terminal-muted",
};

function CsvPasteBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs">
      {label}
      <textarea
        className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 font-mono text-[11px]"
        rows={4}
        placeholder={"well_id,basin,production_bbl\nW-1,Permian,120.5\nW-2,Permian,88.1"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function DatasetDetail({ dataset, token, onChanged }: { dataset: Dataset; token: string; onChanged: () => void }) {
  const [records, setRecords] = useState<EnterpriseRecord[] | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlement[] | null>(null);
  const [csvText, setCsvText] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [previewResult, setPreviewResult] = useState<{ schema: Record<string, string>; preview_rows: Record<string, unknown>[] } | null>(null);
  const [principal, setPrincipal] = useState({ principal_type: "WORKSPACE", principal_id: "" });

  async function loadRecords() {
    setRecords(await apiGet<EnterpriseRecord[]>(`/admin/enterprise-data/datasets/${dataset.id}/records`, token));
  }
  async function loadEntitlements() {
    setEntitlements(await apiGet<Entitlement[]>(`/admin/enterprise-data/datasets/${dataset.id}/entitlements`, token));
  }

  useEffect(() => {
    loadRecords().catch(() => {});
    loadEntitlements().catch(() => {});
  }, [dataset.id, token]);

  async function preview() {
    setMessage(null);
    try {
      const rows = parseCsv(csvText);
      const result = await apiPost<{ schema: Record<string, string>; preview_rows: Record<string, unknown>[] }>(
        `/admin/enterprise-data/datasets/${dataset.id}/preview`,
        { rows },
        token
      );
      setPreviewResult(result);
    } catch {
      setMessage("Preview failed — check the pasted CSV.");
    }
  }

  async function ingest() {
    setMessage(null);
    try {
      const rows = parseCsv(csvText);
      await apiPost(`/admin/enterprise-data/datasets/${dataset.id}/ingest`, { rows }, token);
      setCsvText("");
      setPreviewResult(null);
      await loadRecords();
      onChanged();
    } catch {
      setMessage("Ingest failed — check the pasted CSV.");
    }
  }

  async function grantEntitlement() {
    if (!principal.principal_id.trim()) return;
    setMessage(null);
    try {
      await apiPost(`/admin/enterprise-data/datasets/${dataset.id}/entitlements`, principal, token);
      setPrincipal((p) => ({ ...p, principal_id: "" }));
      await loadEntitlements();
    } catch {
      setMessage("Could not grant entitlement.");
    }
  }

  async function revokeEntitlement(id: string) {
    try {
      await apiDelete(`/admin/enterprise-data/datasets/${dataset.id}/entitlements/${id}`, token);
      await loadEntitlements();
    } catch {
      setMessage("Could not revoke entitlement.");
    }
  }

  return (
    <div className="panel space-y-3 border-l-2 border-terminal-accent/40">
      <div className="panel-title">{dataset.name}</div>
      <div className="text-[11px] text-terminal-muted">
        {dataset.domain} · {dataset.classification} · {dataset.row_count} row(s)
        {dataset.last_synced_at && ` · last synced ${new Date(dataset.last_synced_at).toLocaleString()}`}
      </div>
      <div className="text-[10px] text-terminal-muted">
        Schema: {Object.entries(dataset.schema_summary).map(([k, v]) => `${k}:${v}`).join(", ") || "—"}
      </div>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      <CsvPasteBox value={csvText} onChange={setCsvText} label="Paste CSV to preview/ingest" />
      <div className="flex gap-2">
        <button onClick={preview} className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent">
          Preview
        </button>
        <button onClick={ingest} className="text-[10px] px-1.5 py-0.5 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10">
          Ingest
        </button>
      </div>
      {previewResult && (
        <div className="text-[11px]">
          <div className="text-terminal-muted mb-1">
            Inferred schema: {Object.entries(previewResult.schema).map(([k, v]) => `${k}:${v}`).join(", ") || "—"}
          </div>
          <div className="text-terminal-muted">{previewResult.preview_rows.length} row(s) previewed</div>
        </div>
      )}

      <div>
        <div className="text-terminal-muted text-xs mb-1">Records</div>
        <table className="mono-table w-full text-[11px]">
          <thead>
            <tr>
              <th>Ingested At</th>
              <th>Row</th>
            </tr>
          </thead>
          <tbody>
            {(records ?? []).slice(0, 20).map((r) => (
              <tr key={r.id}>
                <td className="whitespace-nowrap">{new Date(r.ingested_at).toLocaleString()}</td>
                <td className="break-all">{JSON.stringify(r.row_data)}</td>
              </tr>
            ))}
            {records?.length === 0 && (
              <tr>
                <td colSpan={2} className="text-terminal-muted">
                  No records ingested yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div>
        <div className="text-terminal-muted text-xs mb-1">Entitlements</div>
        <div className="flex items-center gap-2 text-xs mb-2">
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={principal.principal_type}
            onChange={(e) => setPrincipal((p) => ({ ...p, principal_type: e.target.value }))}
          >
            {PRINCIPAL_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            placeholder="principal id"
            value={principal.principal_id}
            onChange={(e) => setPrincipal((p) => ({ ...p, principal_id: e.target.value }))}
          />
          <button onClick={grantEntitlement} className="px-2 py-1 border border-terminal-border rounded hover:border-terminal-accent">
            Grant
          </button>
        </div>
        <table className="mono-table w-full text-[11px]">
          <thead>
            <tr>
              <th>Principal</th>
              <th>Granted By</th>
              <th>Granted At</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(entitlements ?? []).map((e) => (
              <tr key={e.id}>
                <td>
                  {e.principal_type}: {e.principal_id}
                </td>
                <td>{e.granted_by ?? "—"}</td>
                <td className="whitespace-nowrap">{new Date(e.granted_at).toLocaleString()}</td>
                <td>
                  <button
                    onClick={() => revokeEntitlement(e.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
            {entitlements?.length === 0 && (
              <tr>
                <td colSpan={4} className="text-terminal-muted">
                  No entitlements granted yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SourceDetail({ source, token, onChanged }: { source: Source; token: string; onChanged: () => void }) {
  const [events, setEvents] = useState<SourceEvent[] | null>(null);
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [selectedDataset, setSelectedDataset] = useState<string | null>(null);
  const [testCsv, setTestCsv] = useState("");
  const [newDataset, setNewDataset] = useState({ name: "", domain: DOMAINS[0], classification: CLASSIFICATIONS[0], csv: "" });
  const [message, setMessage] = useState<string | null>(null);

  async function loadEvents() {
    setEvents(await apiGet<SourceEvent[]>(`/admin/enterprise-data/sources/${source.id}/events`, token));
  }
  async function loadDatasets() {
    setDatasets(await apiGet<Dataset[]>(`/admin/enterprise-data/sources/${source.id}/datasets`, token));
  }

  useEffect(() => {
    loadEvents().catch(() => {});
    loadDatasets().catch(() => {});
  }, [source.id, token]);

  async function testConnection() {
    setMessage(null);
    try {
      const sample_rows = parseCsv(testCsv);
      await apiPost(`/admin/enterprise-data/sources/${source.id}/test-connection`, { sample_rows }, token);
      await loadEvents();
    } catch {
      setMessage("Test connection failed to record.");
    }
  }

  async function createDataset() {
    if (!newDataset.name.trim()) return;
    setMessage(null);
    try {
      const sample_rows = parseCsv(newDataset.csv);
      await apiPost(
        `/admin/enterprise-data/sources/${source.id}/datasets`,
        { name: newDataset.name, domain: newDataset.domain, classification: newDataset.classification, sample_rows },
        token
      );
      setNewDataset({ name: "", domain: DOMAINS[0], classification: CLASSIFICATIONS[0], csv: "" });
      await loadDatasets();
    } catch {
      setMessage("Could not create dataset.");
    }
  }

  const activeDataset = datasets?.find((d) => d.id === selectedDataset) ?? null;

  return (
    <div className="panel space-y-4">
      <div className="flex items-center justify-between">
        <div className="panel-title">{source.name}</div>
        <span className={STATUS_COLOR[source.status.toLowerCase()] ?? ""}>{source.status}</span>
      </div>
      <div className="text-[11px] text-terminal-muted">
        {source.connector_type} · {source.classification}
      </div>
      {message && <p className="text-xs text-terminal-warn">{message}</p>}

      {source.connector_type === "MANUAL_UPLOAD" ? (
        <CsvPasteBox value={testCsv} onChange={setTestCsv} label="Sample rows for test connection (optional)" />
      ) : source.connector_type === "WEBHOOK" ? (
        <p className="text-[11px] text-terminal-muted">
          External systems push rows to <code>POST /api/v1/webhooks/enterprise-data/{source.id}</code>,
          signed with <code>X-AlphaGasIQ-Signature</code> (HMAC-SHA256 of the body, keyed by the
          secret in the <code>signing_secret_env_var</code> environment variable named below).
          Staged rows show up in "Sample rows for schema discovery" and dataset preview/ingest
          below automatically.
        </p>
      ) : (
        <p className="text-[11px] text-terminal-muted">
          Pulls live from <code>connection_config</code> below (edit via the API — see
          docs/alpha-intelligence.md section 11.3 for the fields each connector type reads).
        </p>
      )}
      <div className="text-[10px] text-terminal-muted break-all">
        connection_config: {JSON.stringify(source.connection_config) || "{}"}
      </div>
      <button onClick={testConnection} className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent">
        Test Connection
      </button>

      <div>
        <div className="text-terminal-muted text-xs mb-1">Event Log</div>
        <table className="mono-table w-full text-[11px]">
          <thead>
            <tr>
              <th>Time</th>
              <th>Event</th>
              <th>Status</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {(events ?? []).map((e) => (
              <tr key={e.id}>
                <td className="whitespace-nowrap">{new Date(e.occurred_at).toLocaleString()}</td>
                <td>{e.event_type}</td>
                <td className={STATUS_COLOR[e.status] ?? ""}>{e.status}</td>
                <td>{e.detail}</td>
              </tr>
            ))}
            {events?.length === 0 && (
              <tr>
                <td colSpan={4} className="text-terminal-muted">
                  No events recorded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div>
        <div className="text-terminal-muted text-xs mb-2">Datasets</div>
        <div className="flex flex-wrap items-end gap-2 text-xs mb-2">
          <input
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            placeholder="dataset name"
            value={newDataset.name}
            onChange={(e) => setNewDataset((d) => ({ ...d, name: e.target.value }))}
          />
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={newDataset.domain}
            onChange={(e) => setNewDataset((d) => ({ ...d, domain: e.target.value }))}
          >
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={newDataset.classification}
            onChange={(e) => setNewDataset((d) => ({ ...d, classification: e.target.value }))}
          >
            {CLASSIFICATIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
          <button onClick={createDataset} className="px-2 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10">
            Create dataset
          </button>
        </div>
        <CsvPasteBox
          value={newDataset.csv}
          onChange={(v) => setNewDataset((d) => ({ ...d, csv: v }))}
          label="Sample rows for schema discovery (optional)"
        />

        <table className="mono-table w-full text-xs mt-2">
          <thead>
            <tr>
              <th>Name</th>
              <th>Domain</th>
              <th>Rows</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(datasets ?? []).map((d) => (
              <tr key={d.id}>
                <td>{d.name}</td>
                <td>{d.domain}</td>
                <td>{d.row_count}</td>
                <td>
                  <button
                    onClick={() => setSelectedDataset(d.id === selectedDataset ? null : d.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                  >
                    {d.id === selectedDataset ? "Close" : "Manage"}
                  </button>
                </td>
              </tr>
            ))}
            {datasets?.length === 0 && (
              <tr>
                <td colSpan={4} className="text-terminal-muted">
                  No datasets registered yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {activeDataset && <DatasetDetail dataset={activeDataset} token={token} onChanged={() => { loadDatasets(); onChanged(); }} />}
    </div>
  );
}

export function EnterpriseDataConsole() {
  const { token } = useAuth();
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [draft, setDraft] = useState({
    organization_id: "",
    workspace_id: "",
    name: "",
    connector_type: "MANUAL_UPLOAD",
    classification: "CUSTOMER_CONFIDENTIAL",
    description: "",
  });
  const [connectionConfigText, setConnectionConfigText] = useState("{}");

  async function refresh() {
    if (!token) return;
    setSources(await apiGet<Source[]>("/admin/enterprise-data/sources", token));
  }

  useEffect(() => {
    if (!token) return;
    refresh().catch(() => setMessage("Unable to load enterprise data sources."));
    apiGet<Organization[]>("/admin/organizations", token).then(setOrganizations).catch(() => {});
    apiGet<Workspace[]>("/admin/workspaces", token).then(setWorkspaces).catch(() => {});
  }, [token]);

  async function createSource() {
    if (!token || !draft.organization_id || !draft.name.trim()) return;
    setMessage(null);
    let connection_config: Record<string, unknown> = {};
    try {
      connection_config = connectionConfigText.trim() ? JSON.parse(connectionConfigText) : {};
    } catch {
      setMessage("connection_config must be valid JSON.");
      return;
    }
    try {
      await apiPost(
        "/admin/enterprise-data/sources",
        { ...draft, workspace_id: draft.workspace_id || null, connection_config },
        token
      );
      setDraft({ organization_id: "", workspace_id: "", name: "", connector_type: "MANUAL_UPLOAD", classification: "CUSTOMER_CONFIDENTIAL", description: "" });
      setConnectionConfigText("{}");
      await refresh();
    } catch {
      setMessage("Could not create source.");
    }
  }

  async function deleteSource(id: string) {
    if (!token) return;
    try {
      await apiDelete(`/admin/enterprise-data/sources/${id}`, token);
      if (selected === id) setSelected(null);
      await refresh();
    } catch {
      setMessage("Could not delete source.");
    }
  }

  if (!sources) return <p className="text-xs text-terminal-muted">Loading…</p>;

  const activeSource = sources.find((s) => s.id === selected) ?? null;
  const workspacesForOrg = workspaces.filter((w) => w.organization_id === draft.organization_id);

  return (
    <div className="space-y-4">
      <h1 className="panel-title">Enterprise Data</h1>
      <p className="text-[11px] text-terminal-muted">
        Combine an authorized customer&apos;s own proprietary data with the Alpha Intelligence
        Layer (docs/alpha-intelligence.md section 11). All six connector types
        (MANUAL_UPLOAD/WEBHOOK/REST_API/DATABASE/S3/SFTP) genuinely pull or receive real data —
        set the non-secret <code>connection_config</code> below (a URL, a bucket, a hostname —
        never a credential value; each connector reads the actual secret from an environment
        variable named there) and a connector missing its required configuration honestly
        reports not_configured rather than pretending to work.
      </p>
      {message && <p className="text-xs text-terminal-bear">{message}</p>}

      <div className="panel flex flex-wrap items-end gap-2 text-xs">
        <label className="flex flex-col gap-1">
          Organization
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.organization_id}
            onChange={(e) => setDraft((d) => ({ ...d, organization_id: e.target.value, workspace_id: "" }))}
          >
            <option value="">Select…</option>
            {organizations.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          Workspace (optional)
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.workspace_id}
            onChange={(e) => setDraft((d) => ({ ...d, workspace_id: e.target.value }))}
          >
            <option value="">None</option>
            {workspacesForOrg.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          Name
          <input
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.name}
            onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
          />
        </label>
        <label className="flex flex-col gap-1">
          Connector type
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.connector_type}
            onChange={(e) => setDraft((d) => ({ ...d, connector_type: e.target.value }))}
          >
            {CONNECTOR_TYPES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          Classification
          <select
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1"
            value={draft.classification}
            onChange={(e) => setDraft((d) => ({ ...d, classification: e.target.value }))}
          >
            {CLASSIFICATIONS.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 w-full">
          connection_config (JSON — non-secret only, e.g. {"{"}"url": "https://...", "auth_header_env_var": "PARTNER_API_TOKEN"{"}"})
          <textarea
            className="bg-terminal-bg border border-terminal-border rounded px-2 py-1 font-mono text-[11px] w-full"
            rows={2}
            value={connectionConfigText}
            onChange={(e) => setConnectionConfigText(e.target.value)}
          />
        </label>
        <button onClick={createSource} className="px-2 py-1 border border-terminal-accent text-terminal-accent rounded hover:bg-terminal-accent/10">
          Create source
        </button>
      </div>

      <div className="panel overflow-x-auto">
        <table className="mono-table w-full">
          <thead>
            <tr>
              <th>Name</th>
              <th>Connector</th>
              <th>Classification</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.id}>
                <td>{s.name}</td>
                <td>{s.connector_type}</td>
                <td>{s.classification}</td>
                <td className={STATUS_COLOR[s.status.toLowerCase()] ?? ""}>{s.status}</td>
                <td className="flex gap-2">
                  <button
                    onClick={() => setSelected(s.id === selected ? null : s.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-accent"
                  >
                    {s.id === selected ? "Close" : "Manage"}
                  </button>
                  <button
                    onClick={() => deleteSource(s.id)}
                    className="text-[10px] px-1.5 py-0.5 border border-terminal-border rounded hover:border-terminal-bear hover:text-terminal-bear"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {sources.length === 0 && (
              <tr>
                <td colSpan={5} className="text-terminal-muted">
                  No enterprise data sources yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {activeSource && <SourceDetail source={activeSource} token={token!} onChanged={refresh} />}
    </div>
  );
}
