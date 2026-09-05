import { Conversation, Message, User } from "../types";

const BASE_URL = "";

export class ApiService {
  private static token: string | null = localStorage.getItem("relationship_os_token");

  public static setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem("relationship_os_token", token);
    } else {
      localStorage.removeItem("relationship_os_token");
    }
  }

  public static getToken(): string | null {
    return this.token;
  }

  private static async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> || {}),
    };

    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${BASE_URL}${path}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const message = errorData?.error?.message || `HTTP ${response.status}: ${response.statusText}`;
      throw new Error(message);
    }

    return response.json();
  }

  // Auth endpoints
  public static async login(username: string, password: string, deviceName = "Web Browser"): Promise<{ access_token: string; user: User }> {
    const res = await this.request<{ access_token: string; user: User }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, device_name: deviceName, platform: "browser" }),
    });
    this.setToken(res.access_token);
    return res;
  }

  public static async enroll(token: string, deviceName = "Web Browser"): Promise<{ access_token: string; user: User }> {
    const res = await this.request<{ access_token: string; user: User }>("/api/v1/auth/enroll", {
      method: "POST",
      body: JSON.stringify({ token, device_name: deviceName, platform: "browser" }),
    });
    this.setToken(res.access_token);
    return res;
  }

  public static async getMe(): Promise<User> {
    return this.request<User>("/api/v1/auth/me");
  }

  public static async logout(): Promise<void> {
    try {
      await this.request("/api/v1/auth/logout", { method: "POST" });
    } finally {
      this.setToken(null);
    }
  }

  // Conversations & Messages
  public static async getConversations(): Promise<Conversation[]> {
    return this.request<Conversation[]>("/api/v1/conversations");
  }

  public static async getMessages(conversationId: string, beforeSeq?: number, afterSeq?: number, limit = 50): Promise<Message[]> {
    const params = new URLSearchParams({ limit: limit.toString() });
    if (beforeSeq !== undefined) params.append("before_seq", beforeSeq.toString());
    if (afterSeq !== undefined) params.append("after_seq", afterSeq.toString());
    return this.request<Message[]>(`/api/v1/conversations/${conversationId}/messages?${params.toString()}`);
  }

  public static async sendMessage(conversationId: string, body: string, clientMessageId: string): Promise<Message> {
    return this.request<Message>(`/api/v1/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({
        client_message_id: clientMessageId,
        message: { type: "text", body },
      }),
    });
  }

  public static async markRead(conversationId: string, lastReadSequence: number): Promise<void> {
    await this.request(`/api/v1/conversations/${conversationId}/read`, {
      method: "POST",
      body: JSON.stringify({ last_read_sequence: lastReadSequence }),
    });
  }

  public static async searchMessages(conversationId: string, query: string): Promise<Message[]> {
    const params = new URLSearchParams({ q: query });
    return this.request<Message[]>(`/api/v1/conversations/${conversationId}/search?${params.toString()}`);
  }

  // Admin endpoints
  public static async getAdminHealth(): Promise<any> {
    return this.request("/api/v1/admin/health");
  }

  public static async getSessions(): Promise<any[]> {
    return this.request("/api/v1/admin/sessions");
  }

  public static async revokeSession(sessionId: string): Promise<void> {
    await this.request(`/api/v1/admin/sessions/${sessionId}/revoke`, { method: "POST" });
  }

  public static async createEnrollmentToken(deviceName = "Terminal Client", expiresHours = 24): Promise<{ token: string; expires_at: string }> {
    return this.request("/api/v1/auth/enrollment-tokens", {
      method: "POST",
      body: JSON.stringify({ device_name: deviceName, platform: "windows", expires_in_hours: expiresHours }),
    });
  }

  public static async getWebhooks(): Promise<any[]> {
    return this.request("/api/v1/admin/webhooks");
  }

  public static async createWebhook(name: string, url: string, eventFilters = ["message.created"]): Promise<any> {
    return this.request("/api/v1/admin/webhooks", {
      method: "POST",
      body: JSON.stringify({ name, url, event_filters: eventFilters }),
    });
  }

  public static async deleteWebhook(id: string): Promise<void> {
    await this.request(`/api/v1/admin/webhooks/${id}`, { method: "DELETE" });
  }

  public static async getFailedDeliveries(): Promise<any[]> {
    return this.request("/api/v1/admin/deliveries/failed");
  }

  public static async retryDelivery(deliveryId: string): Promise<void> {
    await this.request(`/api/v1/admin/deliveries/${deliveryId}/retry`, { method: "POST" });
  }

  public static async getAuditLogs(): Promise<any[]> {
    return this.request("/api/v1/admin/audit?limit=50");
  }

  public static async verifyIntegrity(): Promise<any> {
    return this.request("/api/v1/admin/verify-integrity", { method: "POST" });
  }
}
