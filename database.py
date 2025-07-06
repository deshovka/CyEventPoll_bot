import aiosqlite
import logging

logger = logging.getLogger(__name__)

async def init_db():
    async with aiosqlite.connect("events.db") as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                date TEXT NOT NULL,
                image_id TEXT,
                message_id INTEGER,
                UNIQUE(title, date)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS participants (
                event_id INTEGER,
                user_id INTEGER,
                username TEXT,
                participation_status TEXT,
                PRIMARY KEY (event_id, user_id),
                FOREIGN KEY (event_id) REFERENCES events (event_id) ON DELETE CASCADE
            )
        ''')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_participants_event_id ON participants(event_id)')
        await db.commit()