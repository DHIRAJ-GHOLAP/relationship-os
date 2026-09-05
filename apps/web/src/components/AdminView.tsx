import React, { useEffect, useState } from "react";
import { ApiService } from "../services/api";
import {
  Activity,
  ArrowLeft,
  Copy,
  Check,
  FileText,
  KeyRound,
  RotateCw,
  Shield,
  Trash2,
  Users,
  Webhook,
  AlertTriangle,
} from "lucide-react";

interface AdminViewProps {
  onBack: () => void;
}

export const AdminView: React.FC<AdminViewProps> = ({ onBack }) => {
  const [health, setHealth] = useState<any>(null);
  const [sessions, setSessions] = useState<any[]>([]);
  const [webhooks, setWebhooks] = useState<any[]>([]);
  const [failedDeliveries, setFailedDeliveries] = useState<any[]>([]);
  const [auditLogs, setAuditLogs] = useState<any[]>([]);
  const [integrityStatus, setIntegrityStatus] = useState<any>(null);

  // New Enrollment Token State
  const [newTokenDevice, setNewTokenDevice] = useState("PowerShell Client");
  const [issuedToken, setIssuedToken] = useState<string | null>(null);
  const [copiedToken, setCopiedToken] = useState(false);

  // New Webhook State
  const [newWebhookName, setNewWebhookName] = useState("");
  const [newWebhookUrl, setNewWebhookUrl] = useState("");
  const [webhookSecretCreated, setWebhookSecretCreated] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [h, s, w, f, a] = await Promise.all([
        ApiService.getAdminHealth(),
        ApiService.getSessions(),
        ApiService.getWebhooks(),
        ApiService.getFailedDeliveries(),
        ApiService.getAuditLogs(),
      ]);
      setHealth(h);
      setSessions(s);
      setWebhooks(w);
      setFailedDeliveries(f);
      setAuditLogs(a);
    } catch (err: any) {
      setError(err.message || "Failed to load admin controls");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleGenerateToken = async () => {
    try {
      const res = await ApiService.createEnrollmentToken(newTokenDevice, 24);
      setIssuedToken(res.token);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCreateWebhook = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await ApiService.createWebhook(newWebhookName, newWebhookUrl);
      setWebhookSecretCreated(res.signing_secret);
      setNewWebhookName("");
      setNewWebhookUrl("");
      const updated = await ApiService.getWebhooks();
      setWebhooks(updated);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteWebhook = async (id: string) => {
    if (!confirm("Are you sure you want to delete this webhook?")) return;
    try {
      await ApiService.deleteWebhook(id);
      setWebhooks((prev) => prev.filter((w) => w.id !== id));
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRevokeSession = async (id: string) => {
    if (!confirm("Revoke this session? The device will immediately be disconnected.")) return;
    try {
      await ApiService.revokeSession(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRetryDelivery = async (id: string) => {
    try {
      await ApiService.retryDelivery(id);
      setFailedDeliveries((prev) => prev.filter((d) => d.id !== id));
      alert("Delivery reset for immediate retry.");
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleRunIntegrity = async () => {
    try {
      const res = await ApiService.verifyIntegrity();
      setIntegrityStatus(res);
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100 p-4 sm:p-8">
      <div className="max-w-5xl mx-auto space-y-8">
        <div className="flex items-center justify-between border-b border-neutral-800 pb-4">
          <div className="flex items-center space-x-3">
            <button
              onClick={onBack}
              className="p-2 rounded-xl bg-neutral-900 border border-neutral-800 text-neutral-400 hover:text-white transition"
            >
              <ArrowLeft size={18} />
            </button>
            <div>
              <h1 className="text-xl font-bold flex items-center space-x-2">
                <Shield className="text-rose-500" size={20} />
                <span>Admin Control Plane</span>
              </h1>
              <p className="text-xs text-neutral-400">Security oversight and platform management</p>
            </div>
          </div>
          <button
            onClick={loadData}
            disabled={loading}
            className="px-3 py-1.5 bg-neutral-900 border border-neutral-800 hover:bg-neutral-800 text-xs font-medium rounded-xl flex items-center space-x-1.5 transition"
          >
            <RotateCw size={14} className={loading ? "animate-spin" : ""} />
            <span>Refresh</span>
          </button>
        </div>

        {error && (
          <div className="bg-rose-950/60 border border-rose-800/80 text-rose-300 p-4 rounded-xl text-sm flex items-center space-x-2">
            <AlertTriangle size={18} className="text-rose-400 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {health && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="bg-neutral-900/80 border border-neutral-800 p-4 rounded-2xl">
              <div className="text-xs text-neutral-400 uppercase font-semibold">Database</div>
              <div className="text-lg font-bold text-emerald-400 mt-1 capitalize">{health.database}</div>
            </div>
            <div className="bg-neutral-900/80 border border-neutral-800 p-4 rounded-2xl">
              <div className="text-xs text-neutral-400 uppercase font-semibold">Outbox Pending</div>
              <div className="text-lg font-bold text-neutral-100 mt-1">{health.outbox.pending_or_retrying}</div>
            </div>
            <div className="bg-neutral-900/80 border border-neutral-800 p-4 rounded-2xl">
              <div className="text-xs text-neutral-400 uppercase font-semibold">Failed Deliveries</div>
              <div className={`text-lg font-bold mt-1 ${health.outbox.failed_dead_letter > 0 ? "text-rose-400" : "text-neutral-400"}`}>
                {health.outbox.failed_dead_letter}
              </div>
            </div>
            <div className="bg-neutral-900/80 border border-neutral-800 p-4 rounded-2xl">
              <div className="text-xs text-neutral-400 uppercase font-semibold">Active Sessions</div>
              <div className="text-lg font-bold text-neutral-100 mt-1">{health.active_sessions}</div>
            </div>
          </div>
        )}

        {/* Issue Enrollment Token */}
        <section className="bg-neutral-900/60 border border-neutral-800 p-6 rounded-2xl space-y-4">
          <div className="flex items-center space-x-2">
            <KeyRound className="text-rose-400" size={20} />
            <h2 className="font-semibold text-neutral-100">Enroll New Device / Terminal</h2>
          </div>
          <p className="text-xs text-neutral-400">
            Generate a high-entropy one-time enrollment token to safely launch the client on Windows PowerShell or Linux terminal without sharing passwords.
          </p>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={newTokenDevice}
              onChange={(e) => setNewTokenDevice(e.target.value)}
              placeholder="Device name (e.g. My Laptop)"
              className="px-4 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm flex-1"
            />
            <button
              onClick={handleGenerateToken}
              className="px-4 py-2 bg-rose-600 hover:bg-rose-500 text-white text-sm font-medium rounded-xl transition shadow"
            >
              Generate Enrollment Token
            </button>
          </div>

          {issuedToken && (
            <div className="mt-4 p-4 bg-neutral-950 border border-neutral-800 rounded-xl space-y-2">
              <div className="text-xs font-semibold text-rose-400 uppercase">One-Time Token Issued:</div>
              <div className="flex items-center justify-between bg-neutral-900 p-2.5 rounded-lg font-mono text-xs text-neutral-200">
                <span className="truncate mr-2">{issuedToken}</span>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(issuedToken);
                    setCopiedToken(true);
                    setTimeout(() => setCopiedToken(false), 2000);
                  }}
                  className="p-1.5 hover:text-white transition"
                >
                  {copiedToken ? <Check size={16} className="text-emerald-400" /> : <Copy size={16} />}
                </button>
              </div>
              <div className="text-[11px] text-neutral-400">
                Launch command for PowerShell:
                <code className="block bg-neutral-900 p-2 rounded mt-1 font-mono text-neutral-300">
                  pwsh ./apps/launcher/Launch-RelationshipOS.ps1 -EnrollmentToken "{issuedToken}"
                </code>
              </div>
            </div>
          )}
        </section>

        {/* Webhooks Section */}
        <section className="bg-neutral-900/60 border border-neutral-800 p-6 rounded-2xl space-y-4">
          <div className="flex items-center space-x-2">
            <Webhook className="text-rose-400" size={20} />
            <h2 className="font-semibold text-neutral-100">Outbound Webhook Destinations</h2>
          </div>
          <p className="text-xs text-neutral-400">
            Configure secure HMAC-SHA256 signed webhooks. All outbound URLs are validated against SSRF attacks.
          </p>

          <form onSubmit={handleCreateWebhook} className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              required
              value={newWebhookName}
              onChange={(e) => setNewWebhookName(e.target.value)}
              placeholder="Webhook Name (e.g. Automation Hub)"
              className="px-4 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm sm:w-1/3"
            />
            <input
              type="url"
              required
              value={newWebhookUrl}
              onChange={(e) => setNewWebhookUrl(e.target.value)}
              placeholder="https://example.com/webhook"
              className="px-4 py-2 bg-neutral-950 border border-neutral-800 rounded-xl text-sm flex-1"
            />
            <button
              type="submit"
              className="px-4 py-2 bg-neutral-800 hover:bg-neutral-700 text-neutral-100 text-sm font-medium rounded-xl transition"
            >
              Add Endpoint
            </button>
          </form>

          {webhookSecretCreated && (
            <div className="p-3 bg-emerald-950/60 border border-emerald-800/80 rounded-xl text-xs space-y-1">
              <span className="font-semibold text-emerald-300">Signing Secret (Saved once):</span>
              <code className="block font-mono bg-neutral-950 p-2 rounded text-emerald-200">{webhookSecretCreated}</code>
            </div>
          )}

          <div className="divide-y divide-neutral-800 border border-neutral-800 rounded-xl overflow-hidden mt-4">
            {webhooks.length === 0 ? (
              <div className="p-4 text-center text-xs text-neutral-500">No webhooks registered.</div>
            ) : (
              webhooks.map((w) => (
                <div key={w.id} className="p-3.5 bg-neutral-950 flex items-center justify-between text-sm">
                  <div>
                    <div className="font-medium text-neutral-200">{w.name}</div>
                    <div className="text-xs text-neutral-400 font-mono">{w.url}</div>
                    <div className="text-[11px] text-neutral-500 mt-0.5">Secret: {w.secret_preview}</div>
                  </div>
                  <button
                    onClick={() => handleDeleteWebhook(w.id)}
                    className="p-2 text-neutral-500 hover:text-rose-400 transition"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Active Sessions */}
        <section className="bg-neutral-900/60 border border-neutral-800 p-6 rounded-2xl space-y-4">
          <div className="flex items-center space-x-2">
            <Users className="text-rose-400" size={20} />
            <h2 className="font-semibold text-neutral-100">Active Device Sessions</h2>
          </div>
          <div className="divide-y divide-neutral-800 border border-neutral-800 rounded-xl overflow-hidden">
            {sessions.map((s) => (
              <div key={s.id} className="p-3.5 bg-neutral-950 flex items-center justify-between text-sm">
                <div>
                  <div className="font-medium text-neutral-200">
                    {s.display_name} <span className="text-xs text-neutral-400">({s.username})</span>
                  </div>
                  <div className="text-xs text-neutral-400">
                    {s.device_name} • {s.platform} • Last seen {new Date(s.last_seen_at).toLocaleTimeString()}
                  </div>
                </div>
                <button
                  onClick={() => handleRevokeSession(s.id)}
                  className="px-3 py-1 bg-neutral-900 border border-neutral-800 hover:bg-rose-950/60 hover:text-rose-300 text-xs font-medium rounded-lg transition"
                >
                  Terminate
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Audit Logs */}
        <section className="bg-neutral-900/60 border border-neutral-800 p-6 rounded-2xl space-y-4">
          <div className="flex items-center space-x-2">
            <FileText className="text-rose-400" size={20} />
            <h2 className="font-semibold text-neutral-100">Compliance & Security Audit Log</h2>
          </div>
          <div className="divide-y divide-neutral-800 border border-neutral-800 rounded-xl overflow-hidden text-xs">
            {auditLogs.length === 0 ? (
              <div className="p-4 text-center text-neutral-500">No audit events recorded yet.</div>
            ) : (
              auditLogs.slice(0, 10).map((a) => (
                <div key={a.id} className="p-3 bg-neutral-950 flex justify-between items-center">
                  <div>
                    <span className="font-semibold text-rose-400 mr-2 font-mono">[{a.action}]</span>
                    <span className="text-neutral-300">{a.target}</span>
                  </div>
                  <div className="text-neutral-500 font-mono">
                    {new Date(a.created_at).toLocaleTimeString()}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        {/* Failed Deliveries & Manual Retry */}
        {failedDeliveries.length > 0 && (
          <section className="bg-rose-950/30 border border-rose-900/50 p-6 rounded-2xl space-y-4">
            <div className="flex items-center space-x-2">
              <AlertTriangle className="text-rose-400" size={20} />
              <h2 className="font-semibold text-rose-200">Dead-Letter Failed Deliveries</h2>
            </div>
            <div className="divide-y divide-rose-900/40 border border-rose-900/40 rounded-xl overflow-hidden">
              {failedDeliveries.map((d) => (
                <div key={d.id} className="p-3.5 bg-neutral-950 flex items-center justify-between text-sm">
                  <div>
                    <div className="font-medium text-rose-300">{d.integration_type}</div>
                    <div className="text-xs text-neutral-400 font-mono">{d.failure_reason}</div>
                  </div>
                  <button
                    onClick={() => handleRetryDelivery(d.id)}
                    className="px-3 py-1 bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium rounded-lg transition"
                  >
                    Retry
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* Integrity Checker */}
        <section className="bg-neutral-900/60 border border-neutral-800 p-6 rounded-2xl flex items-center justify-between">
          <div>
            <h2 className="font-semibold text-neutral-100 flex items-center space-x-2">
              <Activity className="text-rose-400" size={18} />
              <span>Database Integrity Verification</span>
            </h2>
            <p className="text-xs text-neutral-400 mt-1">
              Checks for monotonic sequence gaps, broken foreign keys, and stuck outbox locks.
            </p>
            {integrityStatus && (
              <div className="mt-2 text-xs font-mono text-emerald-400">
                Status: {integrityStatus.status} | Sequence anomalies: {integrityStatus.sequence_anomalies.length} | Stuck outbox: {integrityStatus.stuck_outbox_events}
              </div>
            )}
          </div>
          <button
            onClick={handleRunIntegrity}
            className="px-4 py-2 bg-neutral-900 border border-neutral-800 hover:bg-neutral-800 text-xs font-medium rounded-xl transition"
          >
            Run Integrity Check
          </button>
        </section>
      </div>
    </div>
  );
};
