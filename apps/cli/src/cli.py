"""Terminal Chat Client for Relationship OS using Rich.

Supports Windows PowerShell, CMD, Linux terminal, and macOS terminal.
"""

import os
import sys
import uuid
import signal
import asyncio
from datetime import datetime
from typing import List, Optional
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt

# Ensure imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from packages.sdk.python.relationship_os_sdk.client import RelationshipOSClient
from packages.sdk.python.relationship_os_sdk.ws_client import RelationshipOSWebSocket
from apps.cli.src.storage import clear_credentials, load_credentials, save_credentials


class TerminalChatApp:
    def __init__(self, server_url: str = "http://127.0.0.1:8000", minimal: bool = False, no_color: bool = False):
        self.server_url = server_url.rstrip("/")
        self.minimal = minimal
        self.console = Console(no_color=no_color, highlight=False)
        self.client = RelationshipOSClient(self.server_url)
        self.ws_client: Optional[RelationshipOSWebSocket] = None
        self.conversation_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.username: Optional[str] = None
        self.display_name: Optional[str] = None
        self.status = "DISCONNECTED"
        self.messages: List[dict] = []
        self._running = False

    def print_header(self):
        if self.minimal:
            self.console.print("--- PRIVATE ROOM ♥ ---", style="bold magenta")
            return

        status_symbol = "●" if self.status == "CONNECTED" else "○"
        status_style = "green" if self.status == "CONNECTED" else "yellow" if self.status == "RECONNECTING" else "red"

        header_text = Text()
        header_text.append("♥ PRIVATE ROOM ♥\n", style="bold red")
        header_text.append(f"Status: {status_symbol} {self.status} | Logged in as: {self.username or 'Anonymous'}", style=status_style)

        self.console.print(Panel(header_text, border_style="magenta", expand=True))

    def format_message(self, msg: dict) -> str:
        sender = msg.get("sender_name") or ("You" if msg.get("sender_id") == self.user_id else "Partner")
        is_me = msg.get("sender_id") == self.user_id
        body = msg.get("body", "")

        # Safe date formatting
        try:
            created_str = msg.get("created_at", "")
            dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        except Exception:
            time_str = ""

        if is_me:
            return f"[bold cyan]You[/] [dim]({time_str})[/]: {body} [dim green]✓[/]"
        else:
            return f"[bold magenta]{sender} ♥[/] [dim]({time_str})[/]: {body}"

    def render_history(self):
        self.console.clear()
        self.print_header()
        self.console.print("")
        for m in self.messages[-25:]:
            self.console.print(self.format_message(m))
        self.console.print("")

    def on_inbound_message(self, msg: dict):
        self.messages.append(msg)
        self.render_history()

    def on_replay(self, payload: dict):
        new_msgs = payload.get("messages", [])
        for m in new_msgs:
            if not any(existing.get("id") == m.get("id") for existing in self.messages):
                self.messages.append(m)
        self.render_history()

    def on_status_change(self, status: str):
        self.status = status
        self.render_history()

    async def initialize_auth(self, enroll_token: Optional[str] = None) -> bool:
        """Authenticate using saved credentials, enrollment token, or login."""
        creds = load_credentials()

        if enroll_token:
            self.console.print("[dim]Enrolling device with token...[/]")
            try:
                data = await self.client.enroll(enroll_token, device_name="PowerShell Client", platform=sys.platform)
                self.user_id = data["user"]["id"]
                self.username = data["user"]["username"]
                self.display_name = data["user"]["display_name"]
                
                # Fetch conversations
                convs = await self.client.get_conversations()
                self.conversation_id = convs[0]["id"] if convs else None

                save_credentials(
                    token=data["access_token"],
                    server_url=self.server_url,
                    user_id=self.user_id,
                    username=self.username,
                    conversation_id=self.conversation_id or "",
                )
                self.console.print("[green]Enrollment successful![/]")
                return True
            except Exception as e:
                self.console.print(f"[bold red]Enrollment failed: {str(e)}[/]")
                return False

        if creds and creds.get("server_url") == self.server_url:
            self.client.access_token = creds.get("access_token")
            self.user_id = creds.get("user_id")
            self.username = creds.get("username")
            self.conversation_id = creds.get("conversation_id")
            try:
                await self.client.get_me()
                return True
            except Exception:
                self.console.print("[yellow]Saved session expired. Please re-authenticate.[/]")
                clear_credentials()

        # Prompt for username and password
        self.console.print("[bold cyan]Please log in to Relationship OS[/]")
        username = Prompt.ask("Username")
        password = Prompt.ask("Password", password=True)

        try:
            data = await self.client.login(username, password, device_name="PowerShell Client", platform=sys.platform)
            self.user_id = data["user"]["id"]
            self.username = data["user"]["username"]
            self.display_name = data["user"]["display_name"]
            
            convs = await self.client.get_conversations()
            self.conversation_id = convs[0]["id"] if convs else None

            save_credentials(
                token=data["access_token"],
                server_url=self.server_url,
                user_id=self.user_id,
                username=self.username,
                conversation_id=self.conversation_id or "",
            )
            return True
        except Exception as e:
            self.console.print(f"[bold red]Login failed: {str(e)}[/]")
            return False

    async def start(self, enroll_token: Optional[str] = None):
        auth_ok = await self.initialize_auth(enroll_token)
        if not auth_ok:
            await self.client.close()
            return

        if not self.conversation_id:
            convs = await self.client.get_conversations()
            if convs:
                self.conversation_id = convs[0]["id"]
            else:
                self.console.print("[bold red]No conversations found.[/]")
                await self.client.close()
                return

        # Fetch recent history via REST
        try:
            history = await self.client.get_history(self.conversation_id, limit=30)
            self.messages = history
        except Exception as e:
            self.console.print(f"[dim]Could not preload history: {e}[/]")

        # Setup WebSocket for live transport
        ws_protocol = "wss" if self.server_url.startswith("https") else "ws"
        server_host = self.server_url.split("://")[-1]
        ws_url = f"{ws_protocol}://{server_host}"

        self.ws_client = RelationshipOSWebSocket(
            ws_url=ws_url,
            token=self.client.access_token,
            conversation_id=self.conversation_id,
            on_message=self.on_inbound_message,
            on_replay=self.on_replay,
            on_status_change=self.on_status_change,
        )
        self.ws_client.start()

        self._running = True
        self.render_history()

        # Input loop running in executor
        loop = asyncio.get_running_loop()

        while self._running:
            try:
                user_input = await loop.run_in_executor(None, input, "> ")
                text = user_input.strip()
                if not text:
                    continue

                if text == "/quit" or text == "/exit":
                    break
                elif text == "/clear":
                    self.render_history()
                    continue
                elif text == "/logout":
                    clear_credentials()
                    self.console.print("[green]Credentials cleared. Exiting...[/]")
                    break

                # Send message
                client_msg_id = str(uuid.uuid4())
                if self.ws_client and self.status == "CONNECTED":
                    await self.ws_client.send_chat_message(text, client_msg_id)
                else:
                    # Fallback to REST API
                    await self.client.send_message(self.conversation_id, text, client_msg_id)

            except (KeyboardInterrupt, EOFError):
                break
            except Exception as e:
                self.console.print(f"[bold red]Send error: {str(e)}[/]")

        # Shutdown
        if self.ws_client:
            await self.ws_client.stop()
        await self.client.close()
        self.console.print("\n[dim]Disconnected. Goodbye! ♥[/]")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Relationship OS - Terminal Chat Client")
    parser.add_argument("--server", default=os.getenv("SERVER_URL", "http://127.0.0.1:8000"), help="Server API URL")
    parser.add_argument("--enroll", default=None, help="One-time enrollment token")
    parser.add_argument("--minimal", action="store_true", help="Minimal display mode")
    parser.add_argument("--no-color", action="store_true", help="Disable color outputs")
    parser.add_argument("--logout", action="store_true", help="Clear saved credentials and exit")

    args = parser.parse_args()

    if args.logout:
        clear_credentials()
        print("Credentials successfully removed.")
        return

    app = TerminalChatApp(server_url=args.server, minimal=args.minimal, no_color=args.no_color)
    asyncio.run(app.start(enroll_token=args.enroll))


if __name__ == "__main__":
    main()
