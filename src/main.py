import sys
import os
from fastapi import FastAPI, Request, Form, Response, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from urllib.parse import (
    quote,
    unquote,
)  # Добавили для работы с русскими буквами в Cookie

# Подтягиваем папку src в пути поиска модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, verify_user, start_shift, end_shift, get_employee_history
from mailer import send_report_by_email

app = FastAPI(title="Онлайн-Табель")

templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup_event():
    init_db()


def get_current_user(request: Request):
    """Проверяет авторизацию и безопасно раскодирует русское имя из Cookie."""
    user_id = request.cookies.get("user_id")
    raw_user_name = request.cookies.get("user_name")

    if not user_id or not raw_user_name:
        return None

    # Раскодируем имя обратно из веб-формата в нормальный русский текст
    user_name = unquote(raw_user_name)
    return {"id": int(user_id), "name": user_name}


# --- МАРШРУТЫ АВТОРИЗАЦИИ (LOGIN / LOGOUT) ---


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    history = get_employee_history(user["id"])
    message = (
        request.query_params.get("message")
        if request.query_params.get("message")
        else ""
    )
    current_month = datetime.now().strftime("%Y-%m")

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "user_name": user["name"],
            "history": history,
            "message": message,
            "current_month": current_month,
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)

    error = (
        request.query_params.get("error") if request.query_params.get("error") else ""
    )
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error}
    )


@app.post("/login")
def handle_login(
    response: Response, username: str = Form(...), password: str = Form(...)
):
    user = verify_user(username.strip(), password)

    if not user:
        return RedirectResponse(
            url="/login?error=Неверное ФИО или пароль!", status_code=303
        )

    user_id, user_name = user
    redirect = RedirectResponse(url="/", status_code=303)

    # Защита: кодируем имя в безопасный формат (например, "Иванов" станет "%D0%98%D0%B2...")
    safe_user_name = quote(user_name)

    redirect.set_cookie(key="user_id", value=str(user_id), httponly=True)
    redirect.set_cookie(key="user_name", value=safe_user_name, httponly=True)
    return redirect


@app.get("/logout")
def handle_logout():
    redirect = RedirectResponse(url="/login", status_code=303)
    redirect.delete_cookie("user_id")
    redirect.delete_cookie("user_name")
    return redirect


# --- МАРШРУТЫ СМЕН (ВХОД / ВЫХОД) ---


@app.post("/start")
def do_start_shift(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    success, message = start_shift(user["id"])
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)


@app.post("/end")
def do_end_shift(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    success, message = end_shift(user["id"])
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)


# --- МАРШРУТ ОТПРАВКИ ОТЧЕТА НА EMAIL ---


@app.post("/send-report")
def do_send_report(request: Request, month: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if len(month) != 7 or "-" not in month:
        return RedirectResponse(
            url=f"/?message={quote('Ошибка: Неверный формат месяца! Используйте ГГГГ-ММ')}",
            status_code=303,
        )

    success, email_message = send_report_by_email(month.strip())
    return RedirectResponse(url=f"/?message={quote(email_message)}", status_code=303)
