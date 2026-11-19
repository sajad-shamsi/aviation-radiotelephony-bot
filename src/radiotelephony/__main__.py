"""Launch the Aviation Radiotelephony Telegram bot."""

import asyncio

from radiotelephony.bot import main

if __name__ == "__main__":
    asyncio.run(main())
