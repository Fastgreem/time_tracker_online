import os
import sqlite3
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from openpyxl import Workbook
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

DB_NAME = "attendance_online.db"


def generate_excel_report(target_month: str) -> str:
    """Генерирует единый плоский Excel-отчет за месяц. Возвращает путь к файлу."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT employees.name, shifts.date, shifts.start_time, shifts.end_time, shifts.duration
        FROM shifts
        JOIN employees ON shifts.employee_id = employees.id
        WHERE shifts.date LIKE ?
        ORDER BY employees.name ASC, shifts.date ASC
    """,
        (f"{target_month}%",),
    )

    all_shifts = cursor.fetchall()
    conn.close()

    if not all_shifts:
        return ""

    wb = Workbook()
    ws = wb.active
    ws.title = "Сводный табель"

    ws.append([f"Сводный табель учета рабочего времени за: {target_month}"])
    ws.append([])
    ws.append(
        [
            "ФИО",
            "Дата",
            "Время прихода",
            "Время ухода",
            "Отработано за день",
            "Итого за месяц",
        ]
    )

    current_employee = None
    employee_seconds = 0
    total_rows_written = 3

    def parse_duration_to_seconds(dur_str):
        if not dur_str or "авто" in dur_str.lower() or "-" in dur_str:
            return 0
        try:
            parts = dur_str.replace("ч", "").replace("м", "").split()
            hours = int(parts[0]) if len(parts) > 0 else 0
            minutes = int(parts[1]) if len(parts) > 1 else 0
            return (hours * 3600) + (minutes * 60)
        except Exception:
            return 0

    for i, (name, date, start, end, duration) in enumerate(all_shifts):
        ws.append(
            [
                name,
                date,
                start,
                end if end else "В процессе",
                duration if duration else "-",
            ]
        )
        total_rows_written += 1
        employee_seconds += parse_duration_to_seconds(duration)

        if current_employee is None:
            current_employee = name

        is_last_row = i == len(all_shifts) - 1
        next_is_different = not is_last_row and all_shifts[i + 1][0] != current_employee

        if is_last_row or next_is_different:
            total_hours = employee_seconds // 3600
            total_minutes = (employee_seconds % 3600) // 60
            ws[f"F{total_rows_written}"] = f"{total_hours}ч {total_minutes}м"
            current_employee = None
            employee_seconds = 0

    for col in ws.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        ws.column_dimensions[col.column_letter].width = max(max_len + 3, 12)

    filename = f"Сводный_отчет_{target_month}.xlsx"
    wb.save(filename)
    return filename


def send_report_by_email(target_month: str) -> tuple[bool, str]:
    """Генерирует Excel-файл и отправляет его бухгалтеру на Email."""
    # 1. Создаем файл отчета
    filepath = generate_excel_report(target_month)
    if not filepath:
        return False, f"Нет данных для отчета за месяц {target_month}."

    # 2. Считываем настройки подключения из файла .env
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 465))
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD")
    receiver_email = os.getenv("BUHGALTER_EMAIL")

    if not all([smtp_server, sender_email, sender_password, receiver_email]):
        return False, "Ошибка конфигурации: проверьте заполнение файла .env"

    # 3. Собираем структуру электронного письма
    msg = MIMEMultipart()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = f"Сводный табель учета времени за {target_month}"

    body = f"Здравствуйте!\n\nВо вложении направляем сводный табель учета рабочего времени сотрудников за отчетный период {target_month}."
    msg.attach(MIMEText(body, "plain"))

    # 4. Прикрепляем сгенерированный Excel файл к письму
    try:
        with open(filepath, "rb") as attachment:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={os.path.basename(filepath)}",
            )
            msg.attach(part)

        # 5. Подключаемся к почтовому серверу и отправляем
        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())

        # Удаляем временный файл с диска после успешной отправки
        os.remove(filepath)
        return (
            True,
            f"Отчет за {target_month} успешно отправлен на адрес {receiver_email}.",
        )

    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        return False, f"Ошибка отправки почты: {str(e)}"
