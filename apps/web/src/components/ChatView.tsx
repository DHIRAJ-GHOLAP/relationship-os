import React, { useEffect, useRef, useState } from "react";
import { ConnectionStatus, Conversation, Message, PresenceState, User } from "../types";
import { ApiService } from "../services/api";
import { WebChatSocket } from "../services/websocket";
import {
  Check,
  CheckCheck,
  LogOut,
  Search,
  Send,
  Shield,
  Wifi,
  WifiOff,
  X,
} from "lucide-react";

interface ChatViewProps {
  user: User;
  onLogout: () => void;
  onOpenAdmin?: () => void;
}

export const ChatView: React.FC<ChatViewProps> = ({ user, onLogout, onOpenAdmin }) => {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputBody, setInputBody] = useState("");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("DISCONNECTED");
  const [partnerPresence, setPartnerPresence] = useState<PresenceState>("offline");
  const [partnerTyping, setPartnerTyping] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchResults, setSearchResults] = useState<Message[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const socketRef = useRef<WebChatSocket | null>(null);
  const typingTimeoutRef = useRef<any>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    const initChat = async () => {
      try {
        const convs = await ApiService.getConversations();
        if (convs.length > 0) {
          const activeConv = convs[0];
          setConversation(activeConv);

          const history = await ApiService.getMessages(activeConv.id, undefined, undefined, 50);
          setMessages(history);
          scrollToBottom();

          const token = ApiService.getToken();
          if (token) {
            const socket = new WebChatSocket(token, activeConv.id, {
              onMessage: (newMsg) => {
                setMessages((prev) => {
                  if (prev.some((m) => m.id === newMsg.id || m.client_message_id === newMsg.client_message_id)) {
                    return prev;
                  }
                  return [...prev, newMsg];
                });
                scrollToBottom();

                if (newMsg.sender_id !== user.id) {
                  socket.sendRead(newMsg.sequence_number);
                }
              },
              onReplay: (replayed) => {
                setMessages((prev) => {
                  const existingIds = new Set(prev.map((m) => m.id));
                  const fresh = replayed.filter((m) => !existingIds.has(m.id));
                  return [...prev, ...fresh].sort((a, b) => a.sequence_number - b.sequence_number);
                });
                scrollToBottom();
              },
              onPresence: (status) => {
                setPartnerPresence(status);
              },
              onStatusChange: (status) => {
                setConnectionStatus(status);
              },
              onTyping: (isTyping) => {
                setPartnerTyping(isTyping);
              },
            });

            socketRef.current = socket;
            socket.start();
          }
        }
      } catch (err) {
        console.error("Failed to initialize chat:", err);
      }
    };

    initChat();

    return () => {
      if (socketRef.current) {
        socketRef.current.stop();
      }
    };
  }, [user.id]);

  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInputBody(e.target.value);
    if (socketRef.current && connectionStatus === "CONNECTED") {
      socketRef.current.sendTyping(true);
      if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
      typingTimeoutRef.current = setTimeout(() => {
        socketRef.current?.sendTyping(false);
      }, 2000);
    }
  };

  const handleSendMessage = async () => {
    const text = inputBody.trim();
    if (!text || !conversation) return;

    const clientMessageId = crypto.randomUUID();
    setInputBody("");

    const tempMessage: Message = {
      id: clientMessageId,
      conversation_id: conversation.id,
      sender_id: user.id,
      sender_name: user.display_name,
      message_type: "text",
      body: text,
      created_at: new Date().toISOString(),
      client_message_id: clientMessageId,
      sequence_number: messages.length > 0 ? messages[messages.length - 1].sequence_number + 1 : 1,
      delivery_state: "queued",
    };

    setMessages((prev) => [...prev, tempMessage]);
    scrollToBottom();

    try {
      if (socketRef.current && connectionStatus === "CONNECTED") {
        socketRef.current.sendMessage(text, clientMessageId);
      } else {
        const saved = await ApiService.sendMessage(conversation.id, text, clientMessageId);
        setMessages((prev) =>
          prev.map((m) => (m.client_message_id === clientMessageId ? saved : m))
        );
      }
    } catch (err) {
      console.error("Send failed:", err);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleSearch = async () => {
    if (!searchQuery.trim() || !conversation) return;
    try {
      const results = await ApiService.searchMessages(conversation.id, searchQuery.trim());
      setSearchResults(results);
    } catch (err) {
      console.error("Search failed:", err);
    }
  };

  const partnerName = user.role === "OWNER" ? "Recipient" : "Owner";

  return (
    <div className="flex flex-col h-screen max-w-4xl mx-auto bg-neutral-950 border-x border-neutral-800 shadow-2xl relative">
      <header className="h-16 px-4 border-b border-neutral-800 flex items-center justify-between bg-neutral-900/90 backdrop-blur shrink-0 z-10">
        <div className="flex items-center space-x-3">
          <div className="relative">
            <div className="w-10 h-10 rounded-full bg-rose-950/80 border border-rose-800/60 flex items-center justify-center text-xl">
              ❤️
            </div>
            <span
              className={`absolute bottom-0 right-0 w-3 h-3 rounded-full border-2 border-neutral-950 ${
                partnerPresence === "online"
                  ? "bg-emerald-500"
                  : partnerPresence === "away"
                  ? "bg-amber-500"
                  : "bg-neutral-600"
              }`}
            />
          </div>
          <div>
            <div className="font-semibold text-neutral-100 flex items-center space-x-2">
              <span>{partnerName}</span>
              <span className="text-xs px-2 py-0.5 rounded-full bg-neutral-800 text-neutral-300 font-mono">
                {conversation?.title || "Private Room"}
              </span>
            </div>
            <div className="text-xs text-neutral-400 flex items-center space-x-1.5">
              <span>{partnerPresence === "online" ? "Active Now" : partnerPresence}</span>
              <span>•</span>
              <span className="flex items-center space-x-1">
                {connectionStatus === "CONNECTED" ? (
                  <span className="text-emerald-400 flex items-center space-x-1">
                    <Wifi size={12} />
                    <span>Live</span>
                  </span>
                ) : (
                  <span className="text-amber-400 flex items-center space-x-1">
                    <WifiOff size={12} />
                    <span>{connectionStatus}</span>
                  </span>
                )}
              </span>
            </div>
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            onClick={() => setIsSearchOpen(true)}
            className="p-2 rounded-xl text-neutral-400 hover:text-neutral-100 hover:bg-neutral-800 transition"
            title="Search messages"
          >
            <Search size={18} />
          </button>

          {(user.role === "OWNER" || user.role === "ADMIN") && onOpenAdmin && (
            <button
              onClick={onOpenAdmin}
              className="p-2 rounded-xl text-rose-400 hover:text-rose-300 hover:bg-rose-950/40 transition flex items-center space-x-1 text-xs font-medium border border-rose-900/40"
              title="Admin Console"
            >
              <Shield size={16} />
              <span className="hidden sm:inline">Admin</span>
            </button>
          )}

          <button
            onClick={onLogout}
            className="p-2 rounded-xl text-neutral-400 hover:text-rose-400 hover:bg-neutral-800 transition"
            title="Sign out"
          >
            <LogOut size={18} />
          </button>
        </div>
      </header>

      {connectionStatus !== "CONNECTED" && (
        <div className="bg-amber-950/70 border-b border-amber-800/60 px-4 py-1.5 text-xs text-amber-300 flex items-center justify-between shrink-0">
          <span>Connection status: {connectionStatus}. Changes will sync automatically.</span>
          <span className="animate-spin text-amber-400">◐</span>
        </div>
      )}

      {isSearchOpen && (
        <div className="absolute inset-0 bg-neutral-950/95 z-20 flex flex-col p-4 backdrop-blur">
          <div className="flex items-center space-x-2 pb-3 border-b border-neutral-800">
            <Search size={20} className="text-neutral-400" />
            <input
              type="text"
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="Search conversation history..."
              className="flex-1 bg-transparent border-none text-neutral-100 placeholder-neutral-500 focus:outline-none text-sm"
            />
            <button
              onClick={handleSearch}
              className="px-3 py-1 bg-rose-600 text-white rounded-lg text-xs font-medium"
            >
              Search
            </button>
            <button
              onClick={() => { setIsSearchOpen(false); setSearchResults([]); }}
              className="p-1 text-neutral-400 hover:text-neutral-100"
            >
              <X size={20} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto mt-4 space-y-2">
            {searchResults.length === 0 ? (
              <p className="text-center text-xs text-neutral-500 mt-8">
                {searchQuery ? "No matching messages found." : "Type a keyword and press Enter."}
              </p>
            ) : (
              searchResults.map((m) => (
                <div key={m.id} className="p-3 bg-neutral-900 border border-neutral-800 rounded-xl text-sm">
                  <div className="flex justify-between text-xs text-neutral-400 mb-1">
                    <span>{m.sender_name || (m.sender_id === user.id ? "You" : partnerName)}</span>
                    <span>{new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
                  </div>
                  <div className="text-neutral-200">{m.body}</div>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center p-6">
            <div className="w-16 h-16 rounded-full bg-rose-950/40 border border-rose-900/30 flex items-center justify-center text-3xl mb-3">
              💌
            </div>
            <h3 className="font-semibold text-neutral-200 text-lg">Your Private Room is Ready</h3>
            <p className="text-sm text-neutral-400 max-w-sm mt-1">
              Messages sent here are encrypted in transit, persisted safely, and synchronized across your devices.
            </p>
          </div>
        ) : (
          messages.map((m) => {
            const isMe = m.sender_id === user.id;
            const time = new Date(m.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            });

            return (
              <div
                key={m.id || m.client_message_id}
                className={`flex flex-col ${isMe ? "items-end" : "items-start"}`}
              >
                <div
                  className={`max-w-[80%] sm:max-w-md px-4 py-2.5 rounded-2xl shadow-sm text-sm break-words ${
                    isMe
                      ? "bg-rose-600 text-white rounded-br-sm"
                      : "bg-neutral-900 text-neutral-100 border border-neutral-800 rounded-bl-sm"
                  }`}
                >
                  <p className="whitespace-pre-wrap">{m.body}</p>
                </div>
                <div className="flex items-center space-x-1.5 mt-1 px-1 text-[11px] text-neutral-500 font-medium">
                  <span>{time}</span>
                  {isMe && (
                    <span>
                      {m.delivery_state === "read" ? (
                        <CheckCheck size={14} className="text-rose-400 inline" />
                      ) : (
                        <Check size={14} className="text-neutral-400 inline" />
                      )}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}

        {partnerTyping && (
          <div className="flex items-center space-x-2 text-xs text-neutral-400 italic">
            <span className="inline-block w-2 h-2 rounded-full bg-rose-500 animate-pulse" />
            <span>{partnerName} is typing...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <footer className="p-4 border-t border-neutral-800 bg-neutral-900/60 backdrop-blur shrink-0">
        <div className="flex items-end space-x-2 bg-neutral-950 border border-neutral-800 rounded-2xl p-2 focus-within:border-rose-500/80 transition">
          <textarea
            rows={1}
            value={inputBody}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={`Message ${partnerName}... (Enter to send)`}
            className="flex-1 max-h-32 bg-transparent text-neutral-100 placeholder-neutral-500 text-sm resize-none focus:outline-none px-2 py-1.5"
          />
          <button
            onClick={handleSendMessage}
            disabled={!inputBody.trim()}
            className="p-2.5 bg-rose-600 hover:bg-rose-500 active:bg-rose-700 disabled:opacity-40 text-white rounded-xl transition shadow shadow-rose-900/30"
          >
            <Send size={16} />
          </button>
        </div>
      </footer>
    </div>
  );
};
