from __future__ import annotations

import json
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chat_history.sqlite3"
MAX_PET_LEVEL = 20
MAX_PET_AFFECTION = 100
MAX_RPG_PLAYER_LEVEL = 100
RPG_PLAYER_EXP_PER_LEVEL = 100
RPG_REPUTATION_MIN = -999
RPG_REPUTATION_MAX = 999
RPG_REPUTATION_TITLES = [
    (-999, -500, "遗臭万年"),
    (-499, -200, "臭名远扬"),
    (-199, -50, "人见人嫌"),
    (-49, -1, "略讨人嫌"),
    (0, 19, "籍籍无名"),
    (20, 49, "小有名气"),
    (50, 199, "人见人爱"),
    (200, 499, "声名远扬"),
    (500, 799, "一代宗师"),
    (800, 999, "传奇英雄"),
]
PET_TYPES = [
    ("耄耋", 1, 100),
    ("小团雀", 1, 20),
    ("云朵猫", 1, 20),
    ("大香肠", 1, 20),
    ("啵啵", 1, 20),
    ("四足蛇", 1, 20),
    ("广式双马尾", 1, 20),
    ("奶茶史莱姆", 1, 20),
    ("月牙兔", 2, 28),
    ("延津虾", 2, 28),
    ("尔都龙", 2, 28),
    ("地精小老头", 2, 28),
    ("大香蕉", 2, 28),
    ("糖霜狐", 2, 28),
    ("风铃鹿", 3, 38),
    ("豆包", 3, 38),
    ("星尘水母", 3, 38),
    ("笑面虎", 3, 38),
    ("乌角鲨", 3, 38),
    ("春岚猫又", 3, 38),
    ("扑棱蛾子", 3, 38),
    ("刺头大佬", 3, 38),
    ("能丶丶丶丶", 4, 52),
    ("琉璃龙", 4, 52),
    ("纸老虎", 4, 52),
    ("小火柴", 4, 52),
    ("夜航鲸", 4, 52),
    ("极光凤凰", 5, 70),
    ("哈基米", 5, 70),
    ("大狗", 5, 70),
    ("Boss幼体", 5, 80),
    ("星骸幼龙", 5, 85),
    ("裂隙小魔王", 5, 90),
]
SPECIAL_PET_NAMES = ("Boss幼体", "星骸幼龙", "裂隙小魔王")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _pet_base_stats(rarity: int) -> tuple[int, int, int]:
    rarity = int(rarity)
    return 80 + rarity * 18, 14 + rarity * 5, 10 + rarity * 4


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_user_created
            ON chat_messages (user_id, created_at, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                remind_at TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reminders_user
            ON reminders (user_id, remind_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_types (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                rarity INTEGER NOT NULL CHECK (rarity BETWEEN 1 AND 5),
                upgrade_exp INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_user_id INTEGER NOT NULL,
                type_id INTEGER NOT NULL,
                level INTEGER NOT NULL DEFAULT 1 CHECK (level BETWEEN 1 AND 20),
                exp INTEGER NOT NULL DEFAULT 0,
                hp INTEGER NOT NULL DEFAULT 100,
                attack INTEGER NOT NULL DEFAULT 20,
                speed INTEGER NOT NULL DEFAULT 15,
                affection INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (type_id) REFERENCES pet_types(id)
            )
            """
        )
        _ensure_column(conn, "pets", "hp", "INTEGER NOT NULL DEFAULT 100")
        _ensure_column(conn, "pets", "attack", "INTEGER NOT NULL DEFAULT 20")
        _ensure_column(conn, "pets", "speed", "INTEGER NOT NULL DEFAULT 15")
        _ensure_column(conn, "pets", "affection", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                current_pet_id INTEGER,
                last_played_at TEXT,
                last_battle_challenge_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (current_pet_id) REFERENCES pets(id)
            )
            """
        )
        _ensure_column(conn, "users", "last_battle_challenge_at", "TEXT")
        _ensure_column(conn, "users", "chat_mode", "TEXT NOT NULL DEFAULT 'deep'")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_checkin (
                user_id INTEGER NOT NULL,
                checkin_date TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, checkin_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_interactions (
                user_id INTEGER NOT NULL,
                interact_date TEXT NOT NULL,
                count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, interact_date)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS broadcast_settings (
                target_type TEXT NOT NULL CHECK (target_type IN ('private', 'group')),
                target_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (target_type, target_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pets_owner
            ON pets (owner_user_id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_players (
                user_id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL DEFAULT 1,
                exp INTEGER NOT NULL DEFAULT 0,
                reputation INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT '籍籍无名',
                total_runs INTEGER NOT NULL DEFAULT 0,
                wins INTEGER NOT NULL DEFAULT 0,
                deaths INTEGER NOT NULL DEFAULT 0,
                gm_welcome_date TEXT,
                gm_welcome_text TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _ensure_column(conn, "rpg_players", "gm_welcome_date", "TEXT")
        _ensure_column(conn, "rpg_players", "gm_welcome_text", "TEXT")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL CHECK (mode IN ('standard', 'creative')),
                status TEXT NOT NULL,
                chapter INTEGER NOT NULL DEFAULT 0,
                floor INTEGER NOT NULL DEFAULT 0,
                seed TEXT NOT NULL DEFAULT '',
                character_json TEXT NOT NULL DEFAULT '{}',
                map_json TEXT NOT NULL DEFAULT '{}',
                inventory_json TEXT NOT NULL DEFAULT '[]',
                flags_json TEXT NOT NULL DEFAULT '{}',
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT,
                result TEXT,
                FOREIGN KEY (user_id) REFERENCES rpg_players(user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rpg_runs_user_status_updated
            ON rpg_runs (user_id, status, updated_at)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rpg_runs_user_finished
            ON rpg_runs (user_id, finished_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_run_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                log_type TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES rpg_runs(id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rpg_run_logs_run_created
            ON rpg_run_logs (run_id, created_at, id)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_player_items (
                user_id INTEGER NOT NULL,
                item_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0,
                acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, item_id),
                FOREIGN KEY (user_id) REFERENCES rpg_players(user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rpg_player_items_user_updated
            ON rpg_player_items (user_id, updated_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rpg_achievements (
                user_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                unlocked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, achievement_id),
                FOREIGN KEY (user_id) REFERENCES rpg_players(user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_rpg_achievements_user
            ON rpg_achievements (user_id, unlocked_at)
            """
        )
        conn.executemany(
            """
            INSERT INTO pet_types (name, rarity, upgrade_exp)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                rarity = excluded.rarity,
                upgrade_exp = excluded.upgrade_exp
            """,
            PET_TYPES,
        )
        conn.execute(
            """
            UPDATE pets
            SET
                hp = 80 + (
                    SELECT rarity FROM pet_types WHERE pet_types.id = pets.type_id
                ) * 18,
                attack = 14 + (
                    SELECT rarity FROM pet_types WHERE pet_types.id = pets.type_id
                ) * 5,
                speed = 10 + (
                    SELECT rarity FROM pet_types WHERE pet_types.id = pets.type_id
                ) * 4
            WHERE hp = 100 AND attack = 20 AND speed = 15
            """
        )
        conn.execute(
            """
            UPDATE pets
            SET affection = MIN(?, MAX(0, affection))
            """,
            (MAX_PET_AFFECTION,),
        )


def add_chat_messages(user_id: int, messages: list[dict[str, str]]) -> None:
    if not messages:
        return

    try:
        with _connect() as conn:
            conn.executemany(
                """
                INSERT INTO chat_messages (user_id, role, content)
                VALUES (?, ?, ?)
                """,
                [
                    (int(user_id), message["role"], message["content"])
                    for message in messages
                ],
            )
    except sqlite3.Error as exc:
        print(f"[DB] 保存聊天记录失败: {type(exc).__name__}: {exc}")


def load_recent_chat_history(user_id: int, limit: int) -> list[dict[str, str]]:
    if limit <= 0:
        return []

    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM chat_messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (int(user_id), int(limit)),
            ).fetchall()
    except sqlite3.Error as exc:
        print(f"[DB] 读取聊天记录失败: {type(exc).__name__}: {exc}")
        return []

    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]


def clear_chat_history(user_id: int) -> int:
    try:
        with _connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM chat_messages
                WHERE user_id = ?
                """,
                (int(user_id),),
            )
            return int(cursor.rowcount)
    except sqlite3.Error as exc:
        print(f"[DB] 清空聊天记录失败: {type(exc).__name__}: {exc}")
        return 0


def get_user_chat_mode(user_id: int, default: str = "deep") -> str:
    ensure_user(user_id)
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT chat_mode
                FROM users
                WHERE user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
    except sqlite3.Error as exc:
        print(f"[DB] 读取聊天模式失败: {type(exc).__name__}: {exc}")
        return default

    if row is None or row["chat_mode"] not in ("casual", "deep"):
        return default
    return row["chat_mode"]


def set_user_chat_mode(user_id: int, chat_mode: str) -> None:
    if chat_mode not in ("casual", "deep"):
        chat_mode = "deep"

    ensure_user(user_id)
    try:
        with _connect() as conn:
            conn.execute(
                """
                UPDATE users
                SET chat_mode = ?
                WHERE user_id = ?
                """,
                (chat_mode, int(user_id)),
            )
    except sqlite3.Error as exc:
        print(f"[DB] 保存聊天模式失败: {type(exc).__name__}: {exc}")


def get_random_pet_type() -> sqlite3.Row:
    placeholders = ", ".join("?" for _ in SPECIAL_PET_NAMES)
    with _connect() as conn:
        return conn.execute(
            f"""
            SELECT id, name, rarity, upgrade_exp
            FROM pet_types
            WHERE name NOT IN ({placeholders})
            ORDER BY RANDOM()
            LIMIT 1
            """,
            SPECIAL_PET_NAMES,
        ).fetchone()


def get_random_pet_type_by_rarity(rarity: int) -> sqlite3.Row:
    placeholders = ", ".join("?" for _ in SPECIAL_PET_NAMES)
    with _connect() as conn:
        return conn.execute(
            f"""
            SELECT id, name, rarity, upgrade_exp
            FROM pet_types
            WHERE rarity = ?
            AND name NOT IN ({placeholders})
            ORDER BY RANDOM()
            LIMIT 1
            """,
            (int(rarity), *SPECIAL_PET_NAMES),
        ).fetchone()


def get_random_special_pet_type() -> sqlite3.Row | None:
    placeholders = ", ".join("?" for _ in SPECIAL_PET_NAMES)
    with _connect() as conn:
        return conn.execute(
            f"""
            SELECT id, name, rarity, upgrade_exp
            FROM pet_types
            WHERE name IN ({placeholders})
            ORDER BY RANDOM()
            LIMIT 1
            """,
            SPECIAL_PET_NAMES,
        ).fetchone()


def get_pet_type(type_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, name, rarity, upgrade_exp
            FROM pet_types
            WHERE id = ?
            """,
            (int(type_id),),
        ).fetchone()


def ensure_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id) VALUES (?)",
            (int(user_id),),
        )


def create_pet_for_user(user_id: int, type_id: int, set_current: bool = False) -> int:
    ensure_user(user_id)
    with _connect() as conn:
        pet_type = conn.execute(
            "SELECT rarity FROM pet_types WHERE id = ?",
            (int(type_id),),
        ).fetchone()
        rarity = 1 if pet_type is None else int(pet_type["rarity"])
        hp, attack, speed = _pet_base_stats(rarity)
        cursor = conn.execute(
            """
            INSERT INTO pets (owner_user_id, type_id, level, exp, hp, attack, speed, affection)
            VALUES (?, ?, 1, 0, ?, ?, ?, 0)
            """,
            (int(user_id), int(type_id), hp, attack, speed),
        )
        pet_id = int(cursor.lastrowid)
        if set_current:
            conn.execute(
                """
                UPDATE users
                SET current_pet_id = ?
                WHERE user_id = ?
                """,
                (pet_id, int(user_id)),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET current_pet_id = ?
                WHERE user_id = ? AND current_pet_id IS NULL
                """,
                (pet_id, int(user_id)),
            )
        return pet_id


def get_current_pet(user_id: int) -> sqlite3.Row | None:
    ensure_user(user_id)
    with _connect() as conn:
        return conn.execute(
            """
            SELECT
                pets.id,
                pets.owner_user_id,
                pets.type_id,
                pets.level,
                pets.exp,
                pets.hp,
                pets.attack,
                pets.speed,
                pets.affection,
                pet_types.name,
                pet_types.rarity,
                pet_types.upgrade_exp
            FROM users
            JOIN pets ON pets.id = users.current_pet_id
            JOIN pet_types ON pet_types.id = pets.type_id
            WHERE users.user_id = ?
            """,
            (int(user_id),),
        ).fetchone()


def list_user_pets(user_id: int) -> list[sqlite3.Row]:
    ensure_user(user_id)
    with _connect() as conn:
        return conn.execute(
            """
            SELECT
                pets.id,
                pets.owner_user_id,
                pets.type_id,
                pets.level,
                pets.exp,
                pets.hp,
                pets.attack,
                pets.speed,
                pets.affection,
                pet_types.name,
                pet_types.rarity,
                pet_types.upgrade_exp,
                users.current_pet_id
            FROM pets
            JOIN pet_types ON pet_types.id = pets.type_id
            JOIN users ON users.user_id = pets.owner_user_id
            WHERE pets.owner_user_id = ?
            ORDER BY pets.id
            """,
            (int(user_id),),
        ).fetchall()


def switch_current_pet(user_id: int, pet_id: int) -> sqlite3.Row | None:
    ensure_user(user_id)
    with _connect() as conn:
        pet = conn.execute(
            """
            SELECT
                pets.id,
                pets.owner_user_id,
                pets.type_id,
                pets.level,
                pets.exp,
                pets.hp,
                pets.attack,
                pets.speed,
                pets.affection,
                pet_types.name,
                pet_types.rarity,
                pet_types.upgrade_exp
            FROM pets
            JOIN pet_types ON pet_types.id = pets.type_id
            WHERE pets.owner_user_id = ? AND pets.id = ?
            """,
            (int(user_id), int(pet_id)),
        ).fetchone()
        if pet is None:
            return None

        conn.execute(
            """
            UPDATE users
            SET current_pet_id = ?
            WHERE user_id = ?
            """,
            (int(pet_id), int(user_id)),
        )
        return pet


def release_pet(user_id: int, pet_id: int) -> sqlite3.Row | None:
    """弃养（删除）属于该用户的指定宠物。

    返回被删除宠物的信息（含 name/rarity/level）；找不到或不属于该用户时返回 None。
    若删掉的是当前携带宠物，自动改携带仓库里剩余 id 最小的一只；没有剩余则置空，
    下次任意宠物指令会经 ensure_current_pet 重新领取初始宠物。
    """
    ensure_user(user_id)
    with _connect() as conn:
        pet = conn.execute(
            """
            SELECT
                pets.id,
                pets.owner_user_id,
                pets.level,
                pet_types.name,
                pet_types.rarity
            FROM pets
            JOIN pet_types ON pet_types.id = pets.type_id
            WHERE pets.owner_user_id = ? AND pets.id = ?
            """,
            (int(user_id), int(pet_id)),
        ).fetchone()
        if pet is None:
            return None

        user_row = conn.execute(
            "SELECT current_pet_id FROM users WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
        is_current = (
            user_row is not None
            and user_row["current_pet_id"] is not None
            and int(user_row["current_pet_id"]) == int(pet_id)
        )

        conn.execute("DELETE FROM pets WHERE id = ?", (int(pet_id),))

        if is_current:
            replacement = conn.execute(
                "SELECT id FROM pets WHERE owner_user_id = ? ORDER BY id LIMIT 1",
                (int(user_id),),
            ).fetchone()
            new_current = int(replacement["id"]) if replacement is not None else None
            conn.execute(
                "UPDATE users SET current_pet_id = ? WHERE user_id = ?",
                (new_current, int(user_id)),
            )
        return pet


def ensure_current_pet(user_id: int) -> sqlite3.Row:
    pet = get_current_pet(user_id)
    if pet is not None:
        return pet

    pet_type = get_random_pet_type()
    create_pet_for_user(user_id, pet_type["id"])
    pet = get_current_pet(user_id)
    if pet is None:
        raise RuntimeError("创建初始宠物失败")
    return pet


def exp_to_next_level(pet: sqlite3.Row) -> int | None:
    if int(pet["level"]) >= MAX_PET_LEVEL:
        return None
    return int(pet["upgrade_exp"]) * int(pet["level"])


def get_pet_by_id(pet_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT
                pets.id,
                pets.owner_user_id,
                pets.type_id,
                pets.level,
                pets.exp,
                pets.hp,
                pets.attack,
                pets.speed,
                pets.affection,
                pet_types.name,
                pet_types.rarity,
                pet_types.upgrade_exp
            FROM pets
            JOIN pet_types ON pet_types.id = pets.type_id
            WHERE pets.id = ?
            """,
            (int(pet_id),),
        ).fetchone()


def add_pet_exp_to(pet_id: int, amount: int) -> tuple[sqlite3.Row | None, int]:
    """给指定宠物加经验（按 pet_id，不依赖"当前携带"），返回 (宠物, 升级数)。"""
    pet = get_pet_by_id(pet_id)
    if pet is None:
        return None, 0
    level = int(pet["level"])
    exp = int(pet["exp"]) + int(amount)
    leveled = 0

    while level < MAX_PET_LEVEL:
        required = int(pet["upgrade_exp"]) * level
        if exp < required:
            break
        exp -= required
        level += 1
        leveled += 1

    if level >= MAX_PET_LEVEL:
        level = MAX_PET_LEVEL
        exp = 0

    with _connect() as conn:
        conn.execute(
            """
            UPDATE pets
            SET level = ?, exp = ?
            WHERE id = ?
            """,
            (level, exp, int(pet_id)),
        )

    return get_pet_by_id(pet_id), leveled


def add_pet_affection_to(pet_id: int, amount: int) -> sqlite3.Row | None:
    """给指定宠物加好感（按 pet_id）。"""
    with _connect() as conn:
        conn.execute(
            """
            UPDATE pets
            SET affection = MIN(?, MAX(0, affection + ?))
            WHERE id = ?
            """,
            (MAX_PET_AFFECTION, int(amount), int(pet_id)),
        )
    return get_pet_by_id(pet_id)


def add_pet_reward_to(pet_id: int, exp_amount: int, affection_amount: int) -> tuple[sqlite3.Row | None, int]:
    """给指定宠物同时加经验和好感（按 pet_id）。"""
    _, leveled = add_pet_exp_to(pet_id, exp_amount)
    return add_pet_affection_to(pet_id, affection_amount), leveled


def add_pet_exp(user_id: int, amount: int) -> tuple[sqlite3.Row, int]:
    pet = ensure_current_pet(user_id)
    return add_pet_exp_to(int(pet["id"]), amount)


def add_pet_affection(user_id: int, amount: int) -> sqlite3.Row:
    pet = ensure_current_pet(user_id)
    return add_pet_affection_to(int(pet["id"]), amount)


def add_pet_reward(user_id: int, exp_amount: int, affection_amount: int) -> tuple[sqlite3.Row, int]:
    _, leveled = add_pet_exp(user_id, exp_amount)
    return add_pet_affection(user_id, affection_amount), leveled


def mark_daily_checkin(user_id: int, checkin_date: str) -> bool:
    ensure_user(user_id)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO daily_checkin (user_id, checkin_date)
            VALUES (?, ?)
            """,
            (int(user_id), checkin_date),
        )
        return cursor.rowcount > 0


def get_last_played_at(user_id: int) -> str | None:
    ensure_user(user_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_played_at FROM users WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
    return None if row is None else row["last_played_at"]


def set_last_played_at(user_id: int, played_at: str) -> None:
    ensure_user(user_id)
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_played_at = ? WHERE user_id = ?",
            (played_at, int(user_id)),
        )


def get_last_battle_challenge_at(user_id: int) -> str | None:
    ensure_user(user_id)
    with _connect() as conn:
        row = conn.execute(
            "SELECT last_battle_challenge_at FROM users WHERE user_id = ?",
            (int(user_id),),
        ).fetchone()
    return None if row is None else row["last_battle_challenge_at"]


def set_last_battle_challenge_at(user_id: int, challenged_at: str) -> None:
    ensure_user(user_id)
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET last_battle_challenge_at = ? WHERE user_id = ?",
            (challenged_at, int(user_id)),
        )


def consume_daily_pet_interaction(user_id: int, interact_date: str, limit: int) -> int | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT count
            FROM pet_interactions
            WHERE user_id = ? AND interact_date = ?
            """,
            (int(user_id), interact_date),
        ).fetchone()
        current_count = 0 if row is None else int(row["count"])
        if current_count >= int(limit):
            return None

        next_count = current_count + 1
        conn.execute(
            """
            INSERT INTO pet_interactions (user_id, interact_date, count, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, interact_date) DO UPDATE SET
                count = excluded.count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(user_id), interact_date, next_count),
        )
        return next_count


def set_broadcast_enabled(target_type: str, target_id: int, enabled: bool) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO broadcast_settings (target_type, target_id, enabled, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(target_type, target_id) DO UPDATE SET
                enabled = excluded.enabled,
                updated_at = CURRENT_TIMESTAMP
            """,
            (target_type, int(target_id), 1 if enabled else 0),
        )


def ensure_broadcast_target(target_type: str, target_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO broadcast_settings (target_type, target_id, enabled)
            VALUES (?, ?, 1)
            """,
            (target_type, int(target_id)),
        )


def get_enabled_broadcast_targets() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT target_type, target_id
            FROM broadcast_settings
            WHERE enabled = 1
            """
        ).fetchall()


def add_reminder(user_id: int, remind_at: str, content: str) -> int:
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (user_id, remind_at, content)
            VALUES (?, ?, ?)
            """,
            (int(user_id), remind_at, content),
        )
        return int(cursor.lastrowid)


def get_reminder(reminder_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, user_id, remind_at, content
            FROM reminders
            WHERE id = ?
            """,
            (int(reminder_id),),
        ).fetchone()


def list_user_reminders(user_id: int) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, user_id, remind_at, content
            FROM reminders
            WHERE user_id = ?
            ORDER BY remind_at
            """,
            (int(user_id),),
        ).fetchall()


def list_all_reminders() -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, user_id, remind_at, content
            FROM reminders
            ORDER BY remind_at
            """
        ).fetchall()


def delete_reminder(reminder_id: int) -> bool:
    with _connect() as conn:
        cursor = conn.execute(
            "DELETE FROM reminders WHERE id = ?",
            (int(reminder_id),),
        )
        return cursor.rowcount > 0


def _to_json(data: object, default: object) -> str:
    if data is None:
        data = default
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _decode_json_field(row: sqlite3.Row, field: str, default: object) -> object:
    raw = row[field]
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def rpg_player_exp_to_next_level(level: int) -> int | None:
    level = int(level)
    if level >= MAX_RPG_PLAYER_LEVEL:
        return None
    return RPG_PLAYER_EXP_PER_LEVEL * max(1, level)


def calculate_rpg_player_level(level: int, exp: int, exp_delta: int = 0) -> tuple[int, int, int]:
    level = max(1, min(MAX_RPG_PLAYER_LEVEL, int(level)))
    exp = max(0, int(exp) + int(exp_delta))
    leveled = 0

    while level < MAX_RPG_PLAYER_LEVEL:
        required = rpg_player_exp_to_next_level(level)
        if required is None or exp < required:
            break
        exp -= required
        level += 1
        leveled += 1

    if level >= MAX_RPG_PLAYER_LEVEL:
        level = MAX_RPG_PLAYER_LEVEL
        exp = 0

    return level, exp, leveled


def calculate_rpg_reputation_title(reputation: int) -> str:
    reputation = max(RPG_REPUTATION_MIN, min(RPG_REPUTATION_MAX, int(reputation)))
    for minimum, maximum, title in RPG_REPUTATION_TITLES:
        if minimum <= reputation <= maximum:
            return title
    return "籍籍无名"


def _apply_rpg_player_progress(
    conn: sqlite3.Connection,
    user_id: int,
    *,
    exp_amount: int = 0,
    reputation_delta: int = 0,
    title: str | None = None,
    total_runs_delta: int = 0,
    wins_delta: int = 0,
    deaths_delta: int = 0,
) -> int:
    row = conn.execute(
        """
        SELECT level, exp, reputation
        FROM rpg_players
        WHERE user_id = ?
        """,
        (int(user_id),),
    ).fetchone()
    if row is None:
        raise ValueError(f"missing rpg player: {user_id}")

    level, exp, leveled = calculate_rpg_player_level(row["level"], row["exp"], exp_amount)
    reputation = max(
        RPG_REPUTATION_MIN,
        min(RPG_REPUTATION_MAX, int(row["reputation"]) + int(reputation_delta)),
    )
    current_title = title if title is not None else calculate_rpg_reputation_title(reputation)
    values: list[object] = [
        level,
        exp,
        reputation,
        current_title,
        int(total_runs_delta),
        int(wins_delta),
        int(deaths_delta),
    ]
    values.append(int(user_id))
    conn.execute(
        f"""
        UPDATE rpg_players
        SET
            level = ?,
            exp = ?,
            reputation = ?,
            title = ?,
            total_runs = total_runs + ?,
            wins = wins + ?,
            deaths = deaths + ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ?
        """,
        values,
    )
    return leveled


def ensure_rpg_player(user_id: int) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO rpg_players (user_id)
            VALUES (?)
            """,
            (int(user_id),),
        )


def get_rpg_player(user_id: int) -> sqlite3.Row:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        return conn.execute(
            """
            SELECT user_id, level, exp, reputation, title, total_runs, wins, deaths,
                   gm_welcome_date, gm_welcome_text, created_at, updated_at
            FROM rpg_players
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchone()


def add_rpg_player_progress(
    user_id: int,
    exp_amount: int = 0,
    reputation_delta: int = 0,
    title: str | None = None,
) -> sqlite3.Row:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        _apply_rpg_player_progress(
            conn,
            user_id,
            exp_amount=exp_amount,
            reputation_delta=reputation_delta,
            title=title,
        )
    return get_rpg_player(user_id)


def set_rpg_player_gm_welcome(user_id: int, welcome_date: str, welcome_text: str) -> sqlite3.Row:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE rpg_players
            SET
                gm_welcome_date = ?,
                gm_welcome_text = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (welcome_date, welcome_text, int(user_id)),
        )
    return get_rpg_player(user_id)


def add_rpg_player_items(user_id: int, item_ids: list[str] | tuple[str, ...]) -> None:
    ensure_rpg_player(user_id)
    counts: dict[str, int] = {}
    for item_id in item_ids:
        item_id = str(item_id)
        if not item_id:
            continue
        counts[item_id] = counts.get(item_id, 0) + 1
    if not counts:
        return

    with _connect() as conn:
        conn.executemany(
            """
            INSERT INTO rpg_player_items (user_id, item_id, quantity)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET
                quantity = quantity + excluded.quantity,
                updated_at = CURRENT_TIMESTAMP
            """,
            [(int(user_id), item_id, quantity) for item_id, quantity in counts.items()],
        )


def list_rpg_player_items(user_id: int) -> list[sqlite3.Row]:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        return conn.execute(
            """
            SELECT user_id, item_id, quantity, acquired_at, updated_at
            FROM rpg_player_items
            WHERE user_id = ? AND quantity > 0
            ORDER BY acquired_at, item_id
            """,
            (int(user_id),),
        ).fetchall()


def unlock_rpg_achievement(user_id: int, achievement_id: str) -> bool:
    """记录一条成就解锁。返回 True 表示这次是首次解锁（已存在则返回 False）。"""
    ensure_rpg_player(user_id)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO rpg_achievements (user_id, achievement_id)
            VALUES (?, ?)
            """,
            (int(user_id), str(achievement_id)),
        )
        return cursor.rowcount > 0


def list_rpg_achievements(user_id: int) -> set[str]:
    """返回该玩家已解锁的成就 id 集合。"""
    ensure_rpg_player(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT achievement_id
            FROM rpg_achievements
            WHERE user_id = ?
            """,
            (int(user_id),),
        ).fetchall()
    return {str(row["achievement_id"]) for row in rows}


def create_rpg_run(
    user_id: int,
    mode: str,
    status: str = "mode_select",
    seed: str = "",
    character: object | None = None,
    map_data: object | None = None,
    inventory: object | None = None,
    flags: object | None = None,
) -> int:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO rpg_runs (
                user_id, mode, status, seed,
                character_json, map_json, inventory_json, flags_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(user_id),
                mode,
                status,
                seed,
                _to_json(character, {}),
                _to_json(map_data, {}),
                _to_json(inventory, []),
                _to_json(flags, {}),
            ),
        )
        return int(cursor.lastrowid)


def get_rpg_run(run_id: int) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, user_id, mode, status, chapter, floor, seed,
                   character_json, map_json, inventory_json, flags_json,
                   started_at, updated_at, finished_at, result
            FROM rpg_runs
            WHERE id = ?
            """,
            (int(run_id),),
        ).fetchone()


def get_active_rpg_run(user_id: int) -> sqlite3.Row | None:
    ensure_rpg_player(user_id)
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, user_id, mode, status, chapter, floor, seed,
                   character_json, map_json, inventory_json, flags_json,
                   started_at, updated_at, finished_at, result
            FROM rpg_runs
            WHERE user_id = ? AND finished_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(user_id),),
        ).fetchone()


def decode_rpg_run_state(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "mode": row["mode"],
        "status": row["status"],
        "chapter": int(row["chapter"]),
        "floor": int(row["floor"]),
        "seed": row["seed"],
        "character": _decode_json_field(row, "character_json", {}),
        "map": _decode_json_field(row, "map_json", {}),
        "inventory": _decode_json_field(row, "inventory_json", []),
        "flags": _decode_json_field(row, "flags_json", {}),
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
        "result": row["result"],
    }


def save_rpg_run_state(
    run_id: int,
    *,
    status: str | None = None,
    chapter: int | None = None,
    floor: int | None = None,
    character: object | None = None,
    map_data: object | None = None,
    inventory: object | None = None,
    flags: object | None = None,
) -> sqlite3.Row | None:
    fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
    values: list[object] = []

    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if chapter is not None:
        fields.append("chapter = ?")
        values.append(int(chapter))
    if floor is not None:
        fields.append("floor = ?")
        values.append(int(floor))
    if character is not None:
        fields.append("character_json = ?")
        values.append(_to_json(character, {}))
    if map_data is not None:
        fields.append("map_json = ?")
        values.append(_to_json(map_data, {}))
    if inventory is not None:
        fields.append("inventory_json = ?")
        values.append(_to_json(inventory, []))
    if flags is not None:
        fields.append("flags_json = ?")
        values.append(_to_json(flags, {}))

    values.append(int(run_id))
    with _connect() as conn:
        conn.execute(
            f"""
            UPDATE rpg_runs
            SET {", ".join(fields)}
            WHERE id = ?
            """,
            values,
        )
    return get_rpg_run(run_id)


def finish_rpg_run(
    run_id: int,
    result: str,
    *,
    status: str = "finished",
    exp_amount: int = 0,
    reputation_delta: int = 0,
    won: bool = False,
    died: bool = False,
) -> sqlite3.Row | None:
    run = get_rpg_run(run_id)
    if run is None:
        return None

    user_id = int(run["user_id"])
    with _connect() as conn:
        cursor = conn.execute(
            """
            UPDATE rpg_runs
            SET
                status = ?,
                result = ?,
                finished_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ? AND finished_at IS NULL
            """,
            (status, result, int(run_id)),
        )
        # 同一局可能因重复消息或并发处理走到两次结算。只有第一个成功把
        # finished_at 从 NULL 改掉的调用，才允许继续发放局外奖励。
        if cursor.rowcount == 0:
            return None
        _apply_rpg_player_progress(
            conn,
            user_id,
            exp_amount=exp_amount,
            reputation_delta=reputation_delta,
            total_runs_delta=1,
            wins_delta=1 if won else 0,
            deaths_delta=1 if died else 0,
        )
    return get_rpg_run(run_id)


def add_rpg_run_log(run_id: int, log_type: str, content: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO rpg_run_logs (run_id, log_type, content)
            VALUES (?, ?, ?)
            """,
            (int(run_id), log_type, content),
        )


def list_rpg_run_logs(run_id: int, limit: int = 20) -> list[sqlite3.Row]:
    with _connect() as conn:
        return conn.execute(
            """
            SELECT id, run_id, log_type, content, created_at
            FROM rpg_run_logs
            WHERE run_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(run_id), int(limit)),
        ).fetchall()


init_db()
