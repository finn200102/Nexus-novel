import pybindings
import asyncio

async def main():
    site = pybindings.PySite("fanfiction")
    data = await site.fetch_story_from_url("https://www.fanfiction.net/s/5782108/1/Harry-Potter-and-the-Methods-of-Rationality")
    print(data.site)
    for chap in data.chapters:
        print(chap.chapter_number)


asyncio.run(main())
