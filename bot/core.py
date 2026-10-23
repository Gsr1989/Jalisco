"""bot/core.py — Instancias de Bot, Dispatcher y storage."""
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN

session_bot = AiohttpSession(timeout=300)
bot         = Bot(token=BOT_TOKEN, session=session_bot)
storage     = MemoryStorage()
dp          = Dispatcher(storage=storage)
