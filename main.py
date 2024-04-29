import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.filters.command import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy.sql import text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, Table, Column, Integer, String, MetaData, select, update, DateTime
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)

# Создаем подключение к базе данных
engine = create_engine('postgresql://postgres:password@localhost/postgres')
# Объект бота
bot = Bot(token="6893998297:AAG4of2D0PUCjXn4k6Oqq0k5ms788vofiY4")
# Диспетчер
dp = Dispatcher()
metadata = MetaData()

projects = Table(
    'projects', metadata,
    Column('id', Integer, primary_key=True),
    Column('user_id', Integer),  # Add user_id column
    Column('project_name', String),
    Column('client_name', String),
    Column('client_phone', String),
    Column('end_date', DateTime)
)

class ProjectForm(StatesGroup):
    project_name = State()
    client_name = State()
    client_phone = State()
    end_date = State()
    user_id = State()

class ProjectsState(StatesGroup):
    waiting_for_project_choice = State()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = [
        [
            types.KeyboardButton(text="Мои проекты"),
            types.KeyboardButton(text="Добавить проект")
        ],
    ]
    keyboard = types.ReplyKeyboardMarkup(
        keyboard=kb,
        resize_keyboard=True,
        input_field_placeholder="Выберите кнопку"
    )
    await message.answer("Посмотрите ваши проекты или добавите проект?", reply_markup=keyboard)


@dp.message(F.text.lower() == "мои проекты")
async def show_projects(message: types.Message):
    user_id = message.from_user.id

    Session = sessionmaker(bind=engine)
    session = Session()

    user_projects = session.query(projects).filter_by(user_id=user_id).all()
    session.close()

    if user_projects:
        projects_keyboard = InlineKeyboardMarkup(row_width=1, inline_keyboard=[])

        for project in user_projects:
            button_text = f"{project.project_name} - {project.end_date.strftime('%d.%m.%y %H:%M')}"
            callback_data = f"project_{project.id}"
            delete_callback_data = f"delete_project_{project.id}"
            projects_keyboard.inline_keyboard.append(
                [InlineKeyboardButton(text=button_text, callback_data=callback_data),
                 InlineKeyboardButton(text="Удалить проект", callback_data=delete_callback_data)])

        await message.answer("Ваши проекты:", reply_markup=projects_keyboard)
    else:
        await message.answer("У вас пока нет проектов.")


@dp.callback_query(lambda query: query.data.startswith('delete_project_'))
async def delete_project(query: types.CallbackQuery):
    id = int(query.data.split('_')[2])

    with engine.connect() as connection:
        # Выполнить SQL-запрос на удаление проекта
        connection.execute(text("DELETE FROM projects WHERE id=:id"), {"id": id})
        connection.commit()

    await query.message.answer(f"Проект успешно удален.")


@dp.callback_query(lambda query: query.data.startswith('project_'))
async def project_info(query: types.CallbackQuery):
    project_id = int(query.data.split('_')[1])
    Session = sessionmaker(bind=engine)
    session = Session()
    project = session.query(projects).filter_by(id=project_id).first()
    session.close()
    if project:
        now = datetime.now()
        if now > project.end_date:
            await query.message.answer("Срок проекта уже прошел.")
        else:
            time_remaining = project.end_date - now
            days_remaining = time_remaining.days
            hours_remaining = time_remaining.seconds // 3600
            await query.message.answer(
                f"Название проекта: {project.project_name}\nСрок окончания: {project.end_date}\nОсталось времени: {days_remaining} дней {hours_remaining} часов")
    else:
        await query.message.answer("Проект не найден.")

@dp.message(F.text.lower() == "добавить проект")
async def add_project(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    await state.update_data(user_id=user_id)  # Save user_id to state
    await message.reply("Введите название проекта:")
    await state.set_state(ProjectForm.project_name)

@dp.message(ProjectForm.project_name)
async def get_project_name(message: types.Message, state: FSMContext):
    await state.update_data(project_name = message.text)
    await message.answer("Введите имя клиента:")
    # Wait for the client name from the user
    await state.set_state(ProjectForm.client_name)

@dp.message(ProjectForm.client_name)
async def get_client_name(message: types.Message, state: FSMContext):
    await state.update_data(client_name = message.text)
    await message.answer("Введите номер клиента (без знака +):")
    # Move to the next state to get the client phone number
    await state.set_state(ProjectForm.client_phone)

@dp.message(ProjectForm.client_phone)
async def get_client_phone(message: types.Message, state: FSMContext):
    await state.update_data(client_phone = message.text)
    await message.answer("Введите срок окончания проекта в формате дд.мм.гг чч:мм (например, 31.12.2024 23:59):")
    await state.set_state(ProjectForm.end_date)

@dp.message(ProjectForm.end_date)
async def get_end_date(message: types.Message, state: FSMContext):
    try:
        end_date = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        user_data = await state.get_data()  # Get all data at once
        project_name = user_data["project_name"]
        client_name = user_data["client_name"]
        client_phone = user_data["client_phone"]
        user_id = user_data["user_id"]  # Retrieve user_id
    except ValueError:
        await message.answer("Неверный формат даты. Пожалуйста, введите дату в формате дд.мм.гг чч:мм (например, 31.12.2024 23:59):")
        return

    with engine.connect() as connection:
        data = {
            "user_id": user_id,
            "project_name": project_name,
            "client_name": client_name,
            "client_phone": client_phone,
            "end_date": end_date
        }
        connection.execute(text("INSERT INTO projects (user_id, project_name, client_name, client_phone, end_date) VALUES (:user_id, :project_name, :client_name, :client_phone, :end_date)"), data)
        connection.commit()  # Commit the changes
        logging.info("Project data inserted successfully!")

    await message.answer(f"Проект успешно добавлен:\n"
                         f"Имя клиента: {client_name}\n"
                         f"Номер клиента: +{client_phone}\n"
                         f"Название проекта: {project_name}\n"
                         f"Срок окончания: {end_date.strftime('%d.%m.%y %H:%M')}")


async def check_projects():
    while True:
        now = datetime.now()  # Ensure datetime object
        try:
            three_days_from_now = now + timedelta(days=3)
        except (ValueError, TypeError):  # Handle calculation errors
            logging.error("Error calculating three_days_from_now value. Skipping check.")
            continue  # Move to the next iteration

        with engine.connect() as connection:
            result = connection.execution_options(stream_results=True).execute(
                text(
                    "SELECT id, client_name, client_phone, project_name, end_date, user_id FROM projects WHERE end_date BETWEEN NOW() AND :end_date"),
                {"end_date": three_days_from_now}
            )
            messages_to_send = []
            for row in result:
                id, client_name, client_phone, project_name, end_date, user_id = row
                time_remaining = end_date - now
                days_remaining = time_remaining.days
                hours_remaining = time_remaining.seconds // 3600

                if days_remaining == 3:
                    message = f"У вас осталось 3 дня до окончания проекта '{project_name}'."
                    messages_to_send.append((user_id, message))
                elif days_remaining == 2:
                    message = f"У вас осталось 2 дня до окончания проекта '{project_name}'."
                    messages_to_send.append((user_id, message))
                elif days_remaining == 1:
                    message = f"У вас остался 1 день до окончания проекта '{project_name}'."
                    messages_to_send.append((user_id, message))
                elif days_remaining == 0 and hours_remaining == 1:
                    message = f"У вас остался 1 час до окончания проекта '{project_name}'."
                    messages_to_send.append((user_id, message))
                elif now > end_date:
                    message = f"Срок проекта '{project_name}' уже прошел."
                    messages_to_send.append((user_id, message))

            for user_id, message in messages_to_send:
                await bot.send_message(chat_id=user_id, text=message)

            await asyncio.sleep(3600)  # Check every half-day


async def main():
    try:
        with engine.connect() as connection:
            print("Database connection   successful!")
    except Exception as e:
        print("Database connection failed. Error: ", str(e))
    asyncio.create_task(check_projects())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
