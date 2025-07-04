import pybindings

async def fetch_story_data_by_url(url: str, site_name: str):
    """
    Returns a PyStory object from pybindings
    """

    site = pybindings.PySite(site_name)
    py_story = await site.fetch_story_from_url(url)

    return py_story


async def fetch_chapter(story_id: int, chapter_number: int, chapter_id: int, site_name: str):

    site = pybindings.PySite(site_name)
    py_chapter = await site.fetch_chapter(story_id, chapter_id, chapter_number)

    return py_chapter

