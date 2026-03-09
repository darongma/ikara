from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# Removed StaticPool - usually not recommended for file-based SQLite in production
from models import Base
from config import DATABASE_URL
from downloader import showMessage

engine = create_async_engine(
    DATABASE_URL, 
    echo=False,
    connect_args={
        "check_same_thread": False,
        "timeout": 30  # <--- VERY IMPORTANT: Tells SQLite to wait 30s for a lock to clear
    },
    # poolclass=StaticPool, # <--- Remove this for file-based DBs
)

# expire_on_commit=False is excellent - prevents errors when accessing song data after a save
async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db():
    async with engine.begin() as conn:
        # run_sync is the correct way to bridge the async/sync gap for metadata
        await conn.run_sync(Base.metadata.create_all)
    showMessage(f"Database Initialized: {DATABASE_URL}")

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()