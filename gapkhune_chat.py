import asyncio
import os
import re
import time
import uuid
from datetime import datetime

import flet as ft

# ------------------------------------------------------------
# ChatRoom - Flet multi-user chat prototype
# Shared rooms/messages live in server memory. Deploy one server
# instance for all connected users to see the same messages.
# Messages are cleared when the server restarts.
# ------------------------------------------------------------

MAX_MESSAGE_LENGTH = 1000
MAX_USERNAME_LENGTH = 24
MAX_ROOM_LENGTH = 40
POLL_SECONDS = 2
MAX_MESSAGES_PER_ROOM = 300

ROOMS = {}  # room_name -> list[dict]
ROOM_LOCK = asyncio.Lock()


def clean_text(value: str, limit: int) -> str:
    value = (value or "").strip()
    value = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", value)
    return value[:limit]


def safe_room_name(value: str) -> str:
    value = clean_text(value, MAX_ROOM_LENGTH)
    value = re.sub(r"[^A-Za-z0-9 _-]", "", value).strip()
    return value or "عمومی"


def main(page: ft.Page):
    page.title = "گپ‌خونه | چت آنلاین"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = "#F3F6FB"
    page.window_min_width = 360
    page.window_min_height = 600

    username_input = ft.TextField(
        label="اسم شما",
        hint_text="مثلاً علی",
        max_length=MAX_USERNAME_LENGTH,
        autofocus=True,
        border_radius=12,
    )
    room_input = ft.TextField(
        label="نام اتاق",
        hint_text="عمومی",
        value="عمومی",
        max_length=MAX_ROOM_LENGTH,
        border_radius=12,
    )
    status_text = ft.Text("", color="#B42318", size=13)
    messages_column = ft.Column(
        spacing=10,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
        controls=[],
    )
    message_input = ft.TextField(
        hint_text="پیامت رو بنویس...",
        expand=True,
        multiline=True,
        min_lines=1,
        max_lines=4,
        max_length=MAX_MESSAGE_LENGTH,
        border_radius=18,
        filled=True,
        bgcolor="#FFFFFF",
        on_submit=None,
    )

    state = {
        "username": "",
        "room": "عمومی",
        "last_signature": None,
        "joined": False,
        "closed": False,
    }

    def show_error(message: str):
        status_text.value = message
        page.update()

    def format_time(timestamp: float) -> str:
        try:
            return datetime.fromtimestamp(timestamp).strftime("%H:%M")
        except (ValueError, OSError, OverflowError):
            return "--:--"

    def render_message(item: dict):
        mine = item.get("username") == state["username"]
        bubble_color = "#D8F8D5" if mine else "#FFFFFF"
        alignment = ft.MainAxisAlignment.END if mine else ft.MainAxisAlignment.START
        name_color = "#137547" if mine else "#2563EB"

        bubble = ft.Container(
            content=ft.Column(
                [
                    ft.Text(
                        item.get("username", "کاربر"),
                        size=12,
                        weight=ft.FontWeight.BOLD,
                        color=name_color,
                    ),
                    ft.Text(item.get("text", ""), size=15, color="#172033"),
                    ft.Text(
                        format_time(item.get("time", time.time())),
                        size=10,
                        color="#64748B",
                        text_align=ft.TextAlign.RIGHT,
                    ),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=bubble_color,
            border_radius=ft.border_radius.only(
                top_left=14,
                top_right=14,
                bottom_left=14 if mine else 4,
                bottom_right=4 if mine else 14,
            ),
            padding=12,
            width= min(520, 520),
        )
        return ft.Row([bubble], alignment=alignment)

    async def refresh_messages():
        while not state["closed"]:
            try:
                if state["joined"]:
                    async with ROOM_LOCK:
                        items = list(ROOMS.get(state["room"], []))
                    signature = tuple(
                        (m.get("id"), m.get("text"), m.get("username"))
                        for m in items
                    )
                    if signature != state["last_signature"]:
                        messages_column.controls = [render_message(m) for m in items]
                        state["last_signature"] = signature
                        page.update()
            except Exception:
                # Keep the session alive if a temporary UI refresh fails.
                pass
            await asyncio.sleep(POLL_SECONDS)

    async def send_message(_=None):
        if not state["joined"]:
            show_error("اول وارد یک اتاق شو.")
            return
        text_value = clean_text(message_input.value, MAX_MESSAGE_LENGTH)
        if not text_value:
            show_error("پیام خالی قابل ارسال نیست.")
            return
        try:
            item = {
                "id": str(uuid.uuid4()),
                "username": state["username"],
                "text": text_value,
                "time": time.time(),
            }
            async with ROOM_LOCK:
                room_messages = ROOMS.setdefault(state["room"], [])
                room_messages.append(item)
                if len(room_messages) > MAX_MESSAGES_PER_ROOM:
                    del room_messages[:-MAX_MESSAGES_PER_ROOM]
            message_input.value = ""
            status_text.value = ""
            page.update()
        except Exception:
            show_error("ارسال پیام ناموفق بود؛ اتصال را بررسی و دوباره تلاش کن.")

    def join_chat(_=None):
        username = clean_text(username_input.value, MAX_USERNAME_LENGTH)
        room = safe_room_name(room_input.value)
        if len(username) < 2:
            show_error("اسم باید حداقل ۲ حرف داشته باشد.")
            return
        if not room:
            show_error("یک نام برای اتاق وارد کن.")
            return
        state["username"] = username
        state["room"] = room
        state["joined"] = True
        state["last_signature"] = None
        status_text.value = ""
        messages_column.controls = []
        chat_view.visible = True
        join_view.visible = False
        room_title.value = f"اتاق: {room}"
        message_input.value = ""
        page.update()

    def leave_chat(_=None):
        state["joined"] = False
        state["last_signature"] = None
        chat_view.visible = False
        join_view.visible = True
        status_text.value = ""
        page.update()

    room_title = ft.Text("اتاق: عمومی", size=16, weight=ft.FontWeight.BOLD, color="#FFFFFF")
    chat_view = ft.Column(
        expand=True,
        visible=False,
        spacing=0,
        controls=[
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.FORUM_ROUNDED, color="#FFFFFF", size=26),
                        ft.Column(
                            [
                                ft.Text("گپ‌خونه", color="#FFFFFF", size=19, weight=ft.FontWeight.BOLD),
                                room_title,
                            ],
                            spacing=1,
                            expand=True,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.LOGOUT_ROUNDED,
                            tooltip="خروج از اتاق",
                            icon_color="#FFFFFF",
                            on_click=leave_chat,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                ),
                bgcolor="#2563EB",
                padding=ft.padding.symmetric(horizontal=16, vertical=12),
            ),
            ft.Container(
                content=messages_column,
                expand=True,
                padding=12,
            ),
            ft.Container(
                content=ft.Row(
                    [
                        message_input,
                        ft.IconButton(
                            icon=ft.Icons.SEND_ROUNDED,
                            icon_color="#FFFFFF",
                            bgcolor="#2563EB",
                            tooltip="ارسال پیام",
                            on_click=send_message,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                    spacing=8,
                ),
                padding=12,
                bgcolor="#E8EEF7",
            ),
        ],
    )

    join_view = ft.Column(
        visible=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        alignment=ft.MainAxisAlignment.CENTER,
        spacing=18,
        controls=[
            ft.Container(
                content=ft.Icon(ft.Icons.FORUM_ROUNDED, color="#FFFFFF", size=42),
                bgcolor="#2563EB",
                padding=18,
                border_radius=22,
            ),
            ft.Text("گپ‌خونه", size=30, weight=ft.FontWeight.BOLD, color="#172033"),
            ft.Text(
                "یک اتاق بساز یا اسم اتاق دوستت را وارد کن تا با هم چت کنید.",
                size=14,
                color="#64748B",
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Container(
                content=ft.Column(
                    [
                        username_input,
                        room_input,
                        ft.FilledButton(
                            "ورود به چت",
                            icon=ft.Icons.LOGIN_ROUNDED,
                            on_click=join_chat,
                            width=320,
                            height=48,
                            style=ft.ButtonStyle(
                                bgcolor="#2563EB",
                                color="#FFFFFF",
                                shape=ft.RoundedRectangleBorder(radius=12),
                            ),
                        ),
                        status_text,
                    ],
                    spacing=14,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=360,
                padding=20,
                bgcolor="#FFFFFF",
                border_radius=20,
                shadow=ft.BoxShadow(
                    blur_radius=20,
                    spread_radius=1,
                    color="#16000000",
                    offset=ft.Offset(0, 6),
                ),
            ),
            ft.Text(
                "برای چت خصوصی، هر دو نفر دقیقاً یک نام اتاق وارد کنند.",
                size=12,
                color="#64748B",
                text_align=ft.TextAlign.CENTER,
            ),
        ],
    )

    page.add(
        ft.SafeArea(
            content=ft.Container(
                content=ft.Stack([join_view, chat_view], expand=True),
                expand=True,
                padding=0,
            ),
            expand=True,
        )
    )
    page.run_task(refresh_messages)

    def on_disconnect(_):
        state["closed"] = True

    page.on_disconnect = on_disconnect


if __name__ == "__main__":
    # Render/Railway can set PORT. Flet's web server listens on this port.
    port = int(os.environ.get("PORT", "8550"))
    ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=port, host="0.0.0.0")
