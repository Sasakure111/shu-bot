from __future__ import annotations

import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[1] / "data" / "chat_history.sqlite3"
MAX_PET_LEVEL = 20
MAX_PET_AFFECTION = 100
PET_TYPES = [
    ("耄耋", 1, 100),
    ("小团雀", 1, 20),
    ("云朵猫", 1, 20),
    ("大香肠", 1, 20),
    ("广式双马尾", 1, 20),
    ("奶茶史莱姆", 1, 20),
    ("月牙兔", 2, 28),
    ("地精小老头", 2, 28),
    ("糖霜狐", 2, 28),
    ("风铃鹿", 3, 38),
    ("星尘水母", 3, 38),
    ("春岚猫又", 3, 38),
    ("扑棱蛾子", 3, 38),
    ("能丶丶丶丶", 4, 52),
    ("琉璃龙", 4, 52),
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


def add_pet_exp(user_id: int, amount: int) -> tuple[sqlite3.Row, int]:
    pet = ensure_current_pet(user_id)
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
            (level, exp, int(pet["id"])),
        )

    return ensure_current_pet(user_id), leveled


def add_pet_affection(user_id: int, amount: int) -> sqlite3.Row:
    pet = ensure_current_pet(user_id)
    with _connect() as conn:
        conn.execute(
            """
            UPDATE pets
            SET affection = MIN(?, MAX(0, affection + ?))
            WHERE id = ?
            """,
            (MAX_PET_AFFECTION, int(amount), int(pet["id"])),
        )
    return ensure_current_pet(user_id)


def add_pet_reward(user_id: int, exp_amount: int, affection_amount: int) -> tuple[sqlite3.Row, int]:
    pet, leveled = add_pet_exp(user_id, exp_amount)
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


init_db()
