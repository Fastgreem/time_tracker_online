import sqlite3
import hashlib
from datetime import datetime

DB_NAME = "attendance_online.db"


def hash_password(password: str) -> str:
    """Хеширует пароль для безопасного хранения в БД."""
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    """Создает таблицы для веб-версии табеля."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Таблица сотрудников с паролями
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
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

    # Создаем тестовых сотрудников, если их нет
    cursor.execute("SELECT COUNT(*) FROM employees")
    if cursor.fetchone()[0] == 0:
        # Пароль для всех по умолчанию: "pass123"
        default_hash = hash_password("pass123")
        sample_employees = [
            ("Иванов И.И.", default_hash),
            ("Петров П.П.", default_hash),
            ("Сидоров С.С.", default_hash),
        ]
        cursor.executemany(
            "INSERT INTO employees (name, password_hash) VALUES (?, ?)",
            sample_employees,
        )

    conn.commit()
    conn.close()


def verify_user(name: str, password: str):
    """Проверяет имя и пароль пользователя. Возвращает (ID, Имя) или None."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    p_hash = hash_password(password)

    cursor.execute(
        "SELECT id, name FROM employees WHERE name = ? AND password_hash = ?",
        (name, p_hash),
    )
    user = cursor.fetchone()
    conn.close()
    return user


# Остальные функции (start_shift, end_shift, get_history, check_forgotten_shifts)
# остаются такими же, как в GUI-версии, но адаптированы под веб:


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
    """Возвращает историю конкретного сотрудника для вывода в его личном кабинете."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT date, start_time, end_time, duration FROM shifts WHERE employee_id = ? ORDER BY id DESC",
        (employee_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    return rows
