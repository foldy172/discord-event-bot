import aiosqlite

from config import DATABASE_PATH
from event_status import STATUS_ACTIVE, STATUS_CANCELLED, STATUS_ENDED, STATUS_PENDING


async def init_db() -> None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                roblox_mode TEXT NOT NULL,
                event_time TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                notified INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS subscribers (
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, user_id),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS manager_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS manager_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_roles (
                guild_id INTEGER NOT NULL,
                role_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, role_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_users (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS event_cohosts (
                event_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, user_id),
                FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_panel_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT NOT NULL
            )
            """
        )
        await db.commit()
        await _migrate_events_table(db)


async def _migrate_events_table(db: aiosqlite.Connection) -> None:
    try:
        await db.execute(
            "ALTER TABLE events ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
    except aiosqlite.OperationalError:
        pass
    await db.execute(
        """
        UPDATE events
        SET status = CASE
            WHEN status IS NULL OR status = '' THEN
                CASE WHEN notified = 1 THEN ? ELSE ? END
            ELSE status
        END
        """,
        (STATUS_ACTIVE, STATUS_PENDING),
    )
    await db.commit()


async def create_event(
    guild_id: int,
    channel_id: int,
    message_id: int,
    title: str,
    description: str,
    roblox_mode: str,
    event_time: str,
    role_id: int,
    creator_id: int,
) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO events (
                guild_id, channel_id, message_id, title, description,
                roblox_mode, event_time, role_id, creator_id, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                channel_id,
                message_id,
                title,
                description,
                roblox_mode,
                event_time,
                role_id,
                creator_id,
                STATUS_PENDING,
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_event(event_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_event_by_message(message_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM events WHERE message_id = ?", (message_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def add_subscriber(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO subscribers (event_id, user_id) VALUES (?, ?)",
                (event_id, user_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_subscriber(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM subscribers WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_subscribed(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM subscribers WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        return await cursor.fetchone() is not None


async def get_subscribers(event_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM subscribers WHERE event_id = ?", (event_id,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def get_pending_events() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM events WHERE status = ?", (STATUS_PENDING,)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def set_event_status(event_id: int, status: str) -> None:
    notified = 0 if status == STATUS_PENDING else 1
    await update_event(event_id, status=status, notified=notified)


async def mark_notified(event_id: int) -> None:
    await set_event_status(event_id, STATUS_ACTIVE)


async def list_events(
    guild_id: int,
    *,
    status: str | None = None,
    limit: int = 100,
) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE guild_id = ? AND status = ?
                ORDER BY event_time DESC
                LIMIT ?
                """,
                (guild_id, status, limit),
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM events
                WHERE guild_id = ?
                ORDER BY event_time DESC
                LIMIT ?
                """,
                (guild_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_events_by_status(guild_id: int, statuses: tuple[str, ...]) -> list[dict]:
    if not statuses:
        return []
    placeholders = ", ".join("?" for _ in statuses)
    query = f"""
        SELECT * FROM events
        WHERE guild_id = ? AND status IN ({placeholders})
        ORDER BY event_time DESC
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, (guild_id, *statuses))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def count_subscribers(event_id: int) -> int:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT COUNT(*) FROM subscribers WHERE event_id = ?", (event_id,)
        )
        row = await cursor.fetchone()
        return row[0] if row else 0


async def update_event(event_id: int, **fields) -> None:
    allowed = {
        "title",
        "description",
        "roblox_mode",
        "event_time",
        "role_id",
        "notified",
        "status",
    }
    parts = []
    values = []
    for key, value in fields.items():
        if key in allowed:
            parts.append(f"{key} = ?")
            values.append(value)
    if not parts:
        return
    values.append(event_id)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            f"UPDATE events SET {', '.join(parts)} WHERE id = ?",
            values,
        )
        await db.commit()


async def add_manager_role(guild_id: int, role_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO manager_roles (guild_id, role_id) VALUES (?, ?)",
                (guild_id, role_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_manager_role(guild_id: int, role_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM manager_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_manager_roles(guild_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT role_id FROM manager_roles WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_manager_user(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO manager_users (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_manager_user(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM manager_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_manager_users(guild_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM manager_users WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_admin_role(guild_id: int, role_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO admin_roles (guild_id, role_id) VALUES (?, ?)",
                (guild_id, role_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_admin_role(guild_id: int, role_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM admin_roles WHERE guild_id = ? AND role_id = ?",
            (guild_id, role_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_admin_roles(guild_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT role_id FROM admin_roles WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_admin_user(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO admin_users (guild_id, user_id) VALUES (?, ?)",
                (guild_id, user_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_admin_user(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM admin_users WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_admin_users(guild_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM admin_users WHERE guild_id = ?",
            (guild_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def add_event_cohost(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO event_cohosts (event_id, user_id) VALUES (?, ?)",
                (event_id, user_id),
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_event_cohost(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM event_cohosts WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_event_cohosts(event_id: int) -> list[int]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT user_id FROM event_cohosts WHERE event_id = ?",
            (event_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]


async def count_events_by_statuses(
    guild_id: int, statuses: tuple[str, ...]
) -> int:
    if not statuses:
        return 0
    placeholders = ", ".join("?" for _ in statuses)
    query = f"""
        SELECT COUNT(*) FROM events
        WHERE guild_id = ? AND status IN ({placeholders})
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(query, (guild_id, *statuses))
        row = await cursor.fetchone()
        return row[0] if row else 0


async def delete_events_by_statuses(
    guild_id: int, statuses: tuple[str, ...]
) -> int:
    if not statuses:
        return 0
    placeholders = ", ".join("?" for _ in statuses)
    query = f"""
        DELETE FROM events
        WHERE guild_id = ? AND status IN ({placeholders})
    """
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(query, (guild_id, *statuses))
        await db.commit()
        return cursor.rowcount


async def is_event_cohost(event_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "SELECT 1 FROM event_cohosts WHERE event_id = ? AND user_id = ?",
            (event_id, user_id),
        )
        return await cursor.fetchone() is not None


async def list_web_panel_users() -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, username, created_at, created_by
            FROM web_panel_users
            ORDER BY username COLLATE NOCASE
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_web_panel_user(username: str) -> dict | None:
    name = username.strip()
    if not name:
        return None
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_panel_users WHERE username = ? COLLATE NOCASE",
            (name,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_web_panel_user_by_id(user_id: int) -> dict | None:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM web_panel_users WHERE id = ?", (user_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def create_web_panel_user(
    username: str,
    password_hash: str,
    *,
    created_by: str,
) -> int:
    from datetime import datetime, timezone

    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO web_panel_users (username, password_hash, created_at, created_by)
            VALUES (?, ?, ?, ?)
            """,
            (username, password_hash, created_at, created_by),
        )
        await db.commit()
        return cursor.lastrowid


async def delete_web_panel_user(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM web_panel_users WHERE id = ?", (user_id,)
        )
        await db.commit()
        return cursor.rowcount > 0
