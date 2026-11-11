"""数据库：一个 SQLite 文件。只存最少的信息：学生称呼（可以用代号）、家长称呼、事项、进度、留痕。
不存身份证、成绩单、聊天原文。每张表都带 agency_id，一个机构只能看到自己的数据。"""
import hashlib, os, secrets, sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
DB_PATH = Path(os.environ.get("APP_DB", Path(__file__).parent / "data" / "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS agency (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS user (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL REFERENCES agency(id), name TEXT NOT NULL,
  login TEXT NOT NULL UNIQUE, pw TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('consultant','owner')), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS session (token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES user(id), expires TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS student (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, name TEXT NOT NULL, parent TEXT NOT NULL,
  consultant_id INTEGER NOT NULL REFERENCES user(id), archived INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
  UNIQUE (agency_id, name));
CREATE TABLE IF NOT EXISTS item (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, student_id INTEGER NOT NULL REFERENCES student(id),
  what TEXT NOT NULL, owner TEXT NOT NULL CHECK (owner IN ('学生','家长','学校','机构')), due TEXT NOT NULL,
  created TEXT NOT NULL, agreed TEXT, replied TEXT, reply_text TEXT, done TEXT, school TEXT, deleted INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS chase (id INTEGER PRIMARY KEY, item_id INTEGER NOT NULL REFERENCES item(id), date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS log (
  id INTEGER PRIMARY KEY, agency_id INTEGER NOT NULL, student_id INTEGER, at TEXT NOT NULL, user_id INTEGER,
  who TEXT NOT NULL, src TEXT NOT NULL, act TEXT NOT NULL, undo TEXT, undone INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS custom_school (
  agency_id INTEGER NOT NULL, school TEXT NOT NULL, round TEXT NOT NULL, date TEXT NOT NULL,
  by TEXT NOT NULL, on_date TEXT NOT NULL, src TEXT NOT NULL DEFAULT '', PRIMARY KEY (agency_id, school, round));
CREATE INDEX IF NOT EXISTS item_student ON item(student_id);
CREATE INDEX IF NOT EXISTS log_agency ON log(agency_id, id);
"""


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def init():
    with connect() as con:
        con.executescript(SCHEMA)


def now():
    return datetime.now(TZ)


def today():
    return now().strftime("%Y-%m-%d")


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 240_000).hex()
    return f"pbkdf2${salt}${h}"


def check_pw(pw, stored):
    try:
        _, salt, _h = stored.split("$")
    except ValueError:
        return False
    return secrets.compare_digest(hash_pw(pw, salt), stored)
