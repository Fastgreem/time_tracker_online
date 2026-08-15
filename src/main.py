import sys
import os
from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime
from urllib.parse import quote, unquote

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import (
    init_db,
    verify_user,
    start_shift,
    end_shift,
    get_employee_history,
    add_new_employee,
    get_admin_stats,
    get_all_workers,
    get_employee_history_by_month,
    reset_employee_password,
)

from mailer import send_report_by_email

app = FastAPI(title="Онлайн-Табель")
templates = Jinja2Templates(directory="templates")


@app.on_event("startup")
def startup_event():
    init_db()


def get_current_user(request: Request):
    user_id = request.cookies.get("user_id")
    raw_user_name = request.cookies.get("user_name")
    is_admin = request.cookies.get("is_admin")

    if not user_id or not raw_user_name:
        return None

    return {
        "id": int(user_id),
        "name": unquote(raw_user_name),
        "is_admin": int(is_admin) if is_admin else 0,
    }


# --- МАРШРУТЫ ИНТЕРФЕЙСА ---


@app.get("/", response_class=HTMLResponse)
def index_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    message = unquote(request.query_params.get("message", ""))
    current_month = datetime.now().strftime("%Y-%m")

    if user["is_admin"] == 1:
        stats = get_admin_stats()
        workers = get_all_workers()  # Достаем список сотрудников для архива
        return templates.TemplateResponse(
            "admin.html",
            {
                "request": request,
                "user_name": user["name"],
                "message": message,
                "current_month": current_month,
                "stats": stats,
                "workers": workers,
                "archive_history": None,  # При первой загрузке архив пуст
                "selected_worker": None,
                "selected_month": current_month,
            },
        )

    history = get_employee_history(user["id"])
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


@app.post("/admin/view-archive", response_class=HTMLResponse)
def view_archive(
    request: Request, worker_id: int = Form(...), archive_month: str = Form(...)
):
    """Маршрут для просмотра табелей в админке по фильтрам."""
    user = get_current_user(request)
    if not user or user["is_admin"] != 1:
        return RedirectResponse(url="/", status_code=303)

    current_month = datetime.now().strftime("%Y-%m")
    stats = get_admin_stats()
    workers = get_all_workers()

    # Получаем отфильтрованную историю смен из БД
    archive_history = get_employee_history_by_month(worker_id, archive_month.strip())

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user_name": user["name"],
            "message": "",
            "current_month": current_month,
            "stats": stats,
            "workers": workers,
            "archive_history": archive_history,
            "selected_worker": worker_id,
            "selected_month": archive_month,
        },
    )


# --- АВТОРИЗАЦИЯ И ЛОГИН ---


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=303)
    error = unquote(request.query_params.get("error", ""))
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
            url=f"/login?error={quote('Неверное ФИО или пароль!')}", status_code=303
        )

    user_id, user_name, is_admin = user
    redirect = RedirectResponse(url="/", status_code=303)

    redirect.set_cookie(key="user_id", value=str(user_id), httponly=True)
    redirect.set_cookie(key="user_name", value=quote(user_name), httponly=True)
    redirect.set_cookie(key="is_admin", value=str(is_admin), httponly=True)
    return redirect


@app.get("/logout")
def handle_logout():
    redirect = RedirectResponse(url="/login", status_code=303)
    redirect.delete_cookie("user_id")
    redirect.delete_cookie("user_name")
    redirect.delete_cookie("is_admin")
    return redirect


# --- УПРАВЛЕНИЕ СМЕНАМИ ДЛЯ СОТРУДНИКОВ ---


@app.post("/start")
def do_start_shift(request: Request):
    user = get_current_user(request)
    if not user or user["is_admin"] == 1:
        return RedirectResponse(url="/", status_code=303)

    success, message = start_shift(user["id"])
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)


@app.post("/end")
def do_end_shift(request: Request):
    user = get_current_user(request)
    if not user or user["is_admin"] == 1:
        return RedirectResponse(url="/", status_code=303)

    success, message = end_shift(user["id"])
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)


# --- ДЕЙСТВИЯ АДМИНИСТРАТОРА ---


@app.post("/admin/register")
def do_register_employee(
    request: Request, new_username: str = Form(...), new_password: str = Form(...)
):
    user = get_current_user(request)
    if not user or user["is_admin"] != 1:
        return RedirectResponse(url="/", status_code=303)

    success, message = add_new_employee(new_username, new_password)
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)


@app.post("/send-report")
def do_send_report(request: Request, month: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    if len(month) != 7 or "-" not in month:
        return RedirectResponse(
            url=f"/?message={quote('Ошибка: Неверный формат периода!')}",
            status_code=303,
        )

    success, email_message = send_report_by_email(month.strip())
    return RedirectResponse(url=f"/?message={quote(email_message)}", status_code=303)


@app.post("/admin/reset-password")
def do_reset_password(request: Request, worker_id: int = Form(...)):
    """Точка сброса пароля сотрудника администратором."""
    user = get_current_user(request)
    if not user or user["is_admin"] != 1:
        return RedirectResponse(url="/", status_code=303)

    success, message = reset_employee_password(worker_id)
    return RedirectResponse(url=f"/?message={quote(message)}", status_code=303)
