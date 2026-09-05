import React, { useEffect, useState } from "react";
import { User } from "./types";
import { ApiService } from "./services/api";
import { LoginView } from "./components/LoginView";
import { ChatView } from "./components/ChatView";
import { AdminView } from "./components/AdminView";

export const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState<"chat" | "admin">("chat");

  useEffect(() => {
    const checkAuth = async () => {
      const token = ApiService.getToken();
      if (!token) {
        setLoading(false);
        return;
      }
      try {
        const user = await ApiService.getMe();
        setCurrentUser(user);
      } catch (err) {
        ApiService.setToken(null);
        setCurrentUser(null);
      } finally {
        setLoading(false);
      }
    };

    checkAuth();
  }, []);

  const handleLogout = async () => {
    await ApiService.logout();
    setCurrentUser(null);
    setView("chat");
  };

  if (loading) {
    return (
      <div className="h-screen flex items-center justify-center bg-neutral-950 text-neutral-400">
        <div className="flex flex-col items-center space-y-3">
          <div className="w-8 h-8 border-2 border-rose-500/30 border-t-rose-500 rounded-full animate-spin" />
          <p className="text-xs uppercase tracking-wider font-semibold">Loading Private Room...</p>
        </div>
      </div>
    );
  }

  if (!currentUser) {
    return <LoginView onSuccess={(user) => setCurrentUser(user)} />;
  }

  if (view === "admin") {
    return <AdminView onBack={() => setView("chat")} />;
  }

  return (
    <ChatView
      user={currentUser}
      onLogout={handleLogout}
      onOpenAdmin={() => setView("admin")}
    />
  );
};
