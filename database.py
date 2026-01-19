"""
数据库模块 - 支持广告管理功能
优化：使用线程安全的连接管理
"""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List
from contextlib import contextmanager
from config import config

@dataclass
class UserInfo:
    user_id: int
    chat_id: int
    join_time: datetime
    message_count: int = 0
    check_count: int = 0
    verification_times: int = 0  # 新增：验证通过次数

@dataclass
class Advertisement:
    """广告按钮数据"""
    id: Optional[int] = None
    title: str = ""
    url: str = ""
    sort: int = 0
    validity_period: Optional[datetime] = None
    created_at: Optional[datetime] = None

class Database:
    def __init__(self):
        db_path = Path(config.get("database.path", "data/bot.db"))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._local = threading.local()
        self._init_tables()

    def _get_conn(self):
        """获取线程本地的数据库连接"""
        if not hasattr(self._local, 'conn'):
            self._local.conn = sqlite3.connect(self.db_path)
        return self._local.conn

    @contextmanager
    def _get_cursor(self):
        """上下文管理器：自动提交和关闭"""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_tables(self):
        # 临时连接用于初始化
        conn = sqlite3.connect(self.db_path)
        try:
            # 用户表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER,
                    chat_id INTEGER,
                    join_time TEXT,
                    message_count INTEGER DEFAULT 0,
                    check_count INTEGER DEFAULT 0,
                    verification_times INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, chat_id)
                )
            """)
            
            # 广告表
            conn.execute("""
                CREATE TABLE IF NOT EXISTS advertisements (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    sort INTEGER DEFAULT 0,
                    validity_period TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
        finally:
            conn.close()

    # ============ 用户管理 ============
    
    def get_user(self, user_id: int, chat_id: int) -> Optional[UserInfo]:
        with self._get_cursor() as cur:
            cur.execute(
                "SELECT * FROM users WHERE user_id=? AND chat_id=?",
                (user_id, chat_id)
            )
            row = cur.fetchone()
            if row:
                return UserInfo(
                    user_id=row[0],
                    chat_id=row[1],
                    join_time=datetime.fromisoformat(row[2]),
                    message_count=row[3],
                    check_count=row[4],
                    verification_times=row[5] if len(row) > 5 else 0
                )
        return None

    def save_user(self, user: UserInfo):
        with self._get_cursor() as cur:
            cur.execute("""
                INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?)
            """, (user.user_id, user.chat_id, user.join_time.isoformat(),
                  user.message_count, user.check_count, user.verification_times))

    def increment_message_count(self, user_id: int, chat_id: int):
        with self._get_cursor() as cur:
            cur.execute(
                "UPDATE users SET message_count = message_count + 1 WHERE user_id=? AND chat_id=?",
                (user_id, chat_id)
            )

    def increment_check_count(self, user_id: int, chat_id: int):
        with self._get_cursor() as cur:
            cur.execute(
                "UPDATE users SET check_count = check_count + 1 WHERE user_id=? AND chat_id=?",
                (user_id, chat_id)
            )
    
    def increment_verification_times(self, user_id: int, chat_id: int):
        """增加验证通过次数"""
        with self._get_cursor() as cur:
            cur.execute(
                "UPDATE users SET verification_times = verification_times + 1 WHERE user_id=? AND chat_id=?",
                (user_id, chat_id)
            )

    # ============ 广告管理 ============
    
    def add_advertisement(self, ad: Advertisement) -> int:
        """添加广告"""
        with self._get_cursor() as cur:
            cur.execute("""
                INSERT INTO advertisements (title, url, sort, validity_period)
                VALUES (?, ?, ?, ?)
            """, (ad.title, ad.url, ad.sort, 
                  ad.validity_period.isoformat() if ad.validity_period else None))
            return cur.lastrowid
    
    def get_all_advertisements(self) -> List[Advertisement]:
        """获取所有广告"""
        with self._get_cursor() as cur:
            cur.execute("""
                SELECT id, title, url, sort, validity_period, created_at
                FROM advertisements
                ORDER BY sort DESC, created_at DESC
            """)
            ads = []
            for row in cur.fetchall():
                ads.append(Advertisement(
                    id=row[0],
                    title=row[1],
                    url=row[2],
                    sort=row[3],
                    validity_period=datetime.fromisoformat(row[4]) if row[4] else None,
                    created_at=datetime.fromisoformat(row[5]) if row[5] else None
                ))
            return ads
    
    def get_valid_advertisements(self) -> List[Advertisement]:
        """获取有效的广告（未过期）"""
        now = datetime.now().isoformat()
        with self._get_cursor() as cur:
            cur.execute("""
                SELECT id, title, url, sort, validity_period, created_at
                FROM advertisements
                WHERE validity_period IS NULL OR validity_period > ?
                ORDER BY sort DESC, created_at DESC
            """, (now,))
            ads = []
            for row in cur.fetchall():
                ads.append(Advertisement(
                    id=row[0],
                    title=row[1],
                    url=row[2],
                    sort=row[3],
                    validity_period=datetime.fromisoformat(row[4]) if row[4] else None,
                    created_at=datetime.fromisoformat(row[5]) if row[5] else None
                ))
            return ads
    
    def delete_advertisement(self, ad_id: int):
        """删除广告"""
        with self._get_cursor() as cur:
            cur.execute("DELETE FROM advertisements WHERE id=?", (ad_id,))

db = Database()
