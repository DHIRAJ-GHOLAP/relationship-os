export type UserRole = "OWNER" | "RECIPIENT" | "ADMIN";

export interface User {
  id: string;
  username: string;
  display_name: string;
  role: UserRole;
  is_active: boolean;
}

export interface Conversation {
  id: string;
  title: string;
  type: string;
  status: string;
  created_at: string;
  unread_count: number;
}

export type DeliveryState = "queued" | "processing" | "delivered" | "failed" | "retrying" | "cancelled" | "read";

export interface Message {
  id: string;
  conversation_id: string;
  sender_id: string;
  sender_name?: string;
  message_type: string;
  body: string;
  created_at: string;
  client_message_id: string;
  sequence_number: number;
  delivery_state: DeliveryState;
}

export type ConnectionStatus = "DISCONNECTED" | "CONNECTING" | "AUTHENTICATED" | "SYNCING" | "CONNECTED" | "RECONNECTING" | "ERROR";

export type PresenceState = "online" | "away" | "offline" | "unknown";
