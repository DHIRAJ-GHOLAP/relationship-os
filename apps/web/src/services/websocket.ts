import { ConnectionStatus, Message, PresenceState } from "../types";

export class WebChatSocket {
  private ws: WebSocket | null = null;
  private running = false;
  private reconnectDelay = 1000;
  private pingInterval: any = null;
  private lastKnownSequence = 0;

  constructor(
    private token: string,
    private conversationId: string,
    private callbacks: {
      onMessage: (message: Message) => void;
      onReplay: (messages: Message[]) => void;
      onPresence: (status: PresenceState) => void;
      onStatusChange: (status: ConnectionStatus) => void;
      onTyping?: (isTyping: boolean) => void;
    }
  ) {}

  public setLastKnownSequence(seq: number) {
    if (seq > this.lastKnownSequence) {
      this.lastKnownSequence = seq;
    }
  }

  public start() {
    this.running = true;
    this.connect();
  }

  public stop() {
    this.running = false;
    if (this.pingInterval) clearInterval(this.pingInterval);
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.callbacks.onStatusChange("DISCONNECTED");
  }

  private connect() {
    if (!this.running) return;

    this.callbacks.onStatusChange("CONNECTING");

    const apiBase = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
    let wsUrl = "";
    if (apiBase) {
      const parsed = new URL(apiBase, window.location.href);
      const wsProtocol = parsed.protocol === "https:" ? "wss:" : "ws:";
      wsUrl = `${wsProtocol}//${parsed.host}/api/v1/ws?token=${encodeURIComponent(this.token)}`;
    } else {
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      wsUrl = `${protocol}//${host}/api/v1/ws?token=${encodeURIComponent(this.token)}`;
    }

    try {
      this.ws = new WebSocket(wsUrl);

      this.ws.onopen = () => {
        this.callbacks.onStatusChange("AUTHENTICATED");
        this.reconnectDelay = 1000;

        // Synchronize and replay
        this.callbacks.onStatusChange("SYNCING");
        this.sendFrame("sync", {
          conversation_id: this.conversationId,
          last_sequence: this.lastKnownSequence,
        });

        // Start ping heartbeat
        if (this.pingInterval) clearInterval(this.pingInterval);
        this.pingInterval = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.sendFrame("ping", {});
          }
        }, 20000);

        this.callbacks.onStatusChange("CONNECTED");
      };

      this.ws.onmessage = (event) => {
        try {
          const frame = JSON.parse(event.data);
          const type = frame.type;
          const payload = frame.payload;

          if (type === "event" && frame.event_type === "message.created") {
            const seq = payload.sequence_number;
            if (seq > this.lastKnownSequence) {
              this.lastKnownSequence = seq;
            }
            this.callbacks.onMessage(payload);
          } else if (type === "replay") {
            const messages: Message[] = payload.messages || [];
            messages.forEach((m) => {
              if (m.sequence_number > this.lastKnownSequence) {
                this.lastKnownSequence = m.sequence_number;
              }
            });
            this.callbacks.onReplay(messages);
          } else if (type === "presence") {
            this.callbacks.onPresence(payload.status);
          } else if (type === "typing" && this.callbacks.onTyping) {
            this.callbacks.onTyping(payload.is_typing);
          }
        } catch (e) {
          console.warn("WebSocket parse error:", e);
        }
      };

      this.ws.onclose = () => {
        if (this.pingInterval) clearInterval(this.pingInterval);
        if (this.running) {
          this.callbacks.onStatusChange("RECONNECTING");
          const jitter = Math.random() * 500;
          setTimeout(() => this.connect(), this.reconnectDelay + jitter);
          this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
        }
      };

      this.ws.onerror = () => {
        this.callbacks.onStatusChange("ERROR");
      };
    } catch (e) {
      this.callbacks.onStatusChange("ERROR");
      if (this.running) {
        setTimeout(() => this.connect(), 2000);
      }
    }
  }

  public sendMessage(body: string, clientMessageId: string) {
    this.sendFrame("send", {
      conversation_id: this.conversationId,
      client_message_id: clientMessageId,
      body,
    });
  }

  public sendTyping(isTyping: boolean) {
    this.sendFrame("typing", {
      conversation_id: this.conversationId,
      typing: isTyping,
    });
  }

  public sendRead(sequence: number) {
    this.sendFrame("read", {
      conversation_id: this.conversationId,
      last_read_sequence: sequence,
    });
  }

  private sendFrame(action: string, payload: any) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action, payload }));
    }
  }
}
