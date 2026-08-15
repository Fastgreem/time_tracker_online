import sqlite3
import hashlib
from datetime import datetime

DB_NAME = "attendance_online.db"


def hash_password(password: str) -> str:
    """Хеширует пароль для безопасного хранения."""
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    """Создает таблицы для веб-версии табеля с поддержкой ролей."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица сотрудников (добавлена колонка is_admin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            is_admin INTEGER DEFAULT 0
        )
    """)

    # Таблица смен
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees (id)
        )
    """)

    # Создаем дефолтных пользователей, если таблица пуста
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        # Пароль для всех: pass123
        default_hash = hash_password("pass123")

        # Создаем одного администратора и двух обычных сотрудников
        users = [
            ("Администратор", default_hash, 1),
            ("Иванов И.И.", default_hash, 0),
            ("Петров П.П.", default_hash, 0),
        ]
        cursor.executemany(
            "INSERT INTO employees (name, password_hash, is_admin) VALUES (?, ?, ?)",
            users,
        )

    conn.commit()
    conn.close()


def verify_user(name: str, password: str):
    """Проверяет имя, пароль. Возвращает (ID, Имя, is_admin) или None."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    p_hash = hash_password(password)

    cursor.execute(
        "SELECT id, name, is_admin FROM employees WHERE name = ? AND password_hash = ?",
        (name, p_hash),
    )
    user = cursor.fetchone()
    conn.close()
    return user


def add_new_employee(name: str, password: str) -> tuple[bool, str]:
    """Регистрация нового сотрудника в системе."""
    if not name or not password:
        return False, "Имя и пароль не могут быть пустыми!"

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    try:
        p_hash = hash_password(password)
        cursor.execute(
            "INSERT INTO employees (name, password_hash, is_admin) VALUES (?, ?, 0)",
            (name.strip(), p_hash),
        )
        conn.commit()
        return True, f"Сотрудник {name} успешно зарегистрирован!"
    except sqlite3.IntegrityError:
        return False, "Сотрудник с таким ФИО уже существует!"
    finally:
        conn.close()


def get_admin_stats():
    """Собирает общую аналитику для панели управления."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    current_date = datetime.now().strftime("%Y-%m-%d")

    # 1. Сколько всего сотрудников зарегистрировано (исключая админа)
    cursor.execute("SELECT COUNT(*) FROM employees WHERE is_admin = 0")
    total_emp = cursor.fetchone()[0]

    # 2. Кто сейчас находится на смене (end_time пустой)
    cursor.execute(
        """
        SELECT employees.name, shifts.start_time 
        FROM shifts 
        JOIN employees ON shifts.employee_id = employees.id 
        WHERE shifts.date = ? AND shifts.end_time IS NULL
    """,
        (current_date,),
    )
    active_now = cursor.fetchall()

    conn.close()
    return {"total_employees": total_emp, "active_now": active_now}


def start_shift(employee_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    current_date = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M:%S")

    cursor.execute(
        "SELECT id FROM shifts WHERE employee_id = ? AND date = ? AND end_time IS NULL",
        (employee_id, current_date),
    )
    if cursor.fetchone():
        conn.close()
        return False, "У вас уже есть открытая смена сегодня!"

    cursor.execute(
        "INSERT INTO shifts (employee_id, date, start_time) VALUES (?, ?, ?)",
        (employee_id, current_date, current_time),
    )
    conn.commit()
    conn.close()
    return True, f"Смена открыта в {current_time}!"


def end_shift(employee_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, start_time FROM shifts WHERE employee_id = ? AND end_time IS NULL ORDER BY id DESC LIMIT 1",
        (employee_id,),
    )
    open_shift = cursor.fetchone()

    if not open_shift:
        conn.close()
        return False, "У вас нет открытых смен!"

    shift_id, start_time_str = open_shift
    now = datetime.now()
    end_time_str = now.strftime("%H:%M:%S")

    fmt = "%H:%M:%S"
    try:
        start_dt = datetime.strptime(start_time_str, fmt)
        end_dt = datetime.strptime(end_time_str, fmt)
        duration_td = end_dt - start_dt
        total_seconds = int(duration_td.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        duration_str = f"{hours}ч {minutes}м"
    except Exception:
        duration_str = "Ошибка"

    cursor.execute(
        "UPDATE shifts SET end_time = ?, duration = ? WHERE id = ?",
        (end_time_str, duration_str, shift_id),
    )
    conn.commit()
    conn.close()
    return True, f"Смена закрыта в {end_time_str}. Отработано: {duration_str}"


def get_employee_history(employee_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date, start_time, end_time, duration FROM shifts WHERE employee_id = ? ORDER BY id DESC",
        (employee_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows
