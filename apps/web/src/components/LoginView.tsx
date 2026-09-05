import React, { useState } from "react";
import { ApiService } from "../services/api";
import { User } from "../types";
import { KeyRound, Lock, ShieldCheck, User as UserIcon } from "lucide-react";

interface LoginViewProps {
  onSuccess: (user: User) => void;
}

export const LoginView: React.FC<LoginViewProps> = ({ onSuccess }) => {
  const [mode, setMode] = useState<"login" | "enroll">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [enrollToken, setEnrollToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      if (mode === "login") {
        if (!username || !password) {
          throw new Error("Please enter both username and password.");
        }
        const res = await ApiService.login(username, password);
        onSuccess(res.user);
      } else {
        if (!enrollToken) {
          throw new Error("Please enter your enrollment token.");
        }
        const res = await ApiService.enroll(enrollToken);
        onSuccess(res.user);
      }
    } catch (err: any) {
      setError(err.message || "Authentication failed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-neutral-950 via-neutral-900 to-neutral-950 p-4">
      <div className="w-full max-w-md bg-neutral-900/90 backdrop-blur border border-neutral-800 rounded-2xl shadow-2xl p-8">
        <div className="text-center mb-8">
          <div className="w-16 h-16 bg-rose-950/60 border border-rose-800/40 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl">
            ❤️
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-neutral-100">Relationship OS</h1>
          <p className="text-sm text-neutral-400 mt-1">Private One-to-One Communication</p>
        </div>

        {/* Tab Selection */}
        <div className="flex bg-neutral-950/60 p-1 rounded-xl border border-neutral-800 mb-6">
          <button
            type="button"
            onClick={() => { setMode("login"); setError(null); }}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition ${
              mode === "login"
                ? "bg-rose-600 text-white shadow"
                : "text-neutral-400 hover:text-neutral-200"
            }`}
          >
            Password Sign In
          </button>
          <button
            type="button"
            onClick={() => { setMode("enroll"); setError(null); }}
            className={`flex-1 py-2 text-sm font-medium rounded-lg transition ${
              mode === "enroll"
                ? "bg-rose-600 text-white shadow"
                : "text-neutral-400 hover:text-neutral-200"
            }`}
          >
            Enrollment Token
          </button>
        </div>

        {error && (
          <div className="bg-rose-950/50 border border-rose-800/60 text-rose-300 text-sm p-3.5 rounded-xl mb-6 flex items-start space-x-2">
            <span className="text-rose-400 font-bold">!</span>
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          {mode === "login" ? (
            <>
              <div>
                <label className="block text-xs font-semibold text-neutral-300 uppercase tracking-wider mb-2">
                  Username
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-neutral-500">
                    <UserIcon size={18} />
                  </div>
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder="Enter your username"
                    className="w-full pl-10 pr-4 py-2.5 bg-neutral-950/70 border border-neutral-800 rounded-xl text-neutral-100 placeholder-neutral-500 focus:outline-none focus:border-rose-500 focus:ring-1 focus:ring-rose-500 transition text-sm"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-neutral-300 uppercase tracking-wider mb-2">
                  Password
                </label>
                <div className="relative">
                  <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-neutral-500">
                    <Lock size={18} />
                  </div>
                  <input
                    type="password"
                    required
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••••••"
                    className="w-full pl-10 pr-4 py-2.5 bg-neutral-950/70 border border-neutral-800 rounded-xl text-neutral-100 placeholder-neutral-500 focus:outline-none focus:border-rose-500 focus:ring-1 focus:ring-rose-500 transition text-sm"
                  />
                </div>
              </div>
            </>
          ) : (
            <div>
              <label className="block text-xs font-semibold text-neutral-300 uppercase tracking-wider mb-2">
                One-Time Enrollment Token
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3.5 flex items-center pointer-events-none text-neutral-500">
                  <KeyRound size={18} />
                </div>
                <input
                  type="text"
                  required
                  value={enrollToken}
                  onChange={(e) => setEnrollToken(e.target.value)}
                  placeholder="Paste enrollment token here"
                  className="w-full pl-10 pr-4 py-2.5 bg-neutral-950/70 border border-neutral-800 rounded-xl text-neutral-100 placeholder-neutral-500 focus:outline-none focus:border-rose-500 focus:ring-1 focus:ring-rose-500 transition text-sm font-mono"
                />
              </div>
              <p className="text-xs text-neutral-500 mt-2">
                Tokens are issued securely by the room owner to link new devices without passwords.
              </p>
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full mt-6 py-3 bg-rose-600 hover:bg-rose-500 active:bg-rose-700 text-white font-medium rounded-xl transition flex items-center justify-center space-x-2 shadow-lg shadow-rose-900/30 disabled:opacity-50"
          >
            {loading ? (
              <span className="inline-block w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            ) : (
              <>
                <ShieldCheck size={18} />
                <span>{mode === "login" ? "Enter Private Room" : "Redeem & Connect"}</span>
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  );
};
