import asyncio

from taskview_be.config import get_settings
from taskview_be.public_demo import fetch_public_snapshots
from taskview_be.store import PostgresNeedexStore


async def main() -> None:
    settings = get_settings()
    store = PostgresNeedexStore(settings.taskview_database_url)
    await store.start()
    try:
        snapshots = await fetch_public_snapshots(settings)
        for snapshot in snapshots:
            count = await store.replace_public_demo_snapshot(snapshot)
            print(
                f"{snapshot.source_key}: {count} safe rows, "
                f"sha256={snapshot.content_sha256[:12]}, fetched_at={snapshot.fetched_at.isoformat()}"
            )
    finally:
        await store.stop()


if __name__ == "__main__":
    asyncio.run(main())
