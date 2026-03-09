from database import async_session 
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine
from models import Song
from downloader import generate_meta_string
import asyncio
from config import DATABASE_URL, MEDIA_FOLDER
import os

async def migrate_all_to_simplified():
    async with async_session() as db:
        # 1. Fetch all songs
        result = await db.execute(select(Song))
        songs = result.scalars().all()
        
        print(f"Backend Server Side: Starting migration for {len(songs)} songs...")

        for s in songs:
            # 2. Use the updated centralized function
            # This now returns Simplified strings and a meta string containing:
            # Simplified + Traditional + Pinyin + Shorthand
            s_title, s_artist, final_meta = generate_meta_string(s.title, s.artist)
            
            # 3. Update the database record
            s.title = s_title
            s.artist = s_artist
            s.meta = final_meta
            
            # 4. Handle rank defaults
            if s.rank is None:
                s.rank = 0
            
        # 5. Commit all changes
        try:
            await db.commit()
            print("Backend Server Side: Migration Complete. All songs simplified and meta-tagged with Pinyin.")
        except Exception as e:
            await db.rollback()
            print(f"Backend Server Side ERROR: Migration failed, changes rolled back. {e}")




async def list_orphaned_files():
    async with async_session() as db:
        # 1. Fetch all file_paths from the database
        result = await db.execute(select(Song.file_path))
        # We extract just the filename (basename) to ensure we can match
        # even if the DB stores subfolders or absolute paths.
        db_filenames = {os.path.basename(p) for p in result.scalars().all() if p}

        print(f"--- Scanning Folder: {MEDIA_FOLDER} ---")
        
        count = 0
        
        # 2. Iterate through files in the media folder
        try:
            files_in_folder = os.listdir(MEDIA_FOLDER)
        except FileNotFoundError:
            print(f"Error: {MEDIA_FOLDER} not found.")
            return

        for filename in files_in_folder:
            # Skip directories and hidden system files
            file_full_path = os.path.join(MEDIA_FOLDER, filename)
            if os.path.isdir(file_full_path) or filename.startswith('.'):
                continue
            
            # 3. Check if the file is missing from the DB set
            if filename not in db_filenames:
                count += 1
                print(f"{count}. {filename}")
                try:
                    os.remove(file_full_path)
                    print(f"{count}. DELETED: {filename}")
                except Exception as e:
                    print(f"{count}. ERROR deleting {filename}: {e}")

        # 4. Summary
        if count == 0:
            print("No orphaned files found. Everything is in the database.")
        else:
            print(f"\nTotal orphaned files found: {count}")


engine = create_async_engine(DATABASE_URL, echo=True)

async def add_columns_async():
    async with engine.begin() as conn:  # engine is your AsyncEngine instance
        # Define a helper to run the raw SQL
        def update_schema(sync_conn):
            # 1. Add the 'rank' column
            try:
                sync_conn.execute(text("ALTER TABLE songs ADD COLUMN rank INTEGER DEFAULT 0"))
                print("Backend Server Side: Added 'rank' column.")
            except Exception:
                print("Backend Server Side: 'rank' column already exists.")

            # 2. Add the 'meta' column
            try:
                sync_conn.execute(text("ALTER TABLE songs ADD COLUMN meta TEXT DEFAULT ''"))
                print("Backend Server Side: Added 'meta' column.")
            except Exception:
                print("Backend Server Side: 'meta' column already exists.")

        # Execute the helper in a sync context
        await conn.run_sync(update_schema)
        
    print("Backend Server Side: Schema update successful.")

async def run_migration_pipeline():
    # Run schema changes first
    # await add_columns_async()
    # Then run data migration
    # await migrate_all_to_simplified()
    await list_orphaned_files()

if __name__ == "__main__":
    try:
        # Run the combined pipeline
        asyncio.run(run_migration_pipeline())
    except Exception as e:
        print(f"Backend Server Side ERROR: {e}")

    