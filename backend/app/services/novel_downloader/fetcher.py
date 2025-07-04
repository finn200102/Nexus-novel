import pybindings

async def fetch_story_data_by_url(url: str, site_name: str):
    """
    Returns a PyStory object from pybindings
    """

    site = pybindings.PySite(site_name)
    py_story = await site.fetch_story_from_url(url)

    return py_story

