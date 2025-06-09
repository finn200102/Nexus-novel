import os
import cloudscraper
from bs4 import BeautifulSoup
from fanficfare.adapters import getAdapter
from fanficfare.configurable import Configuration
from fanficfare.writers import getWriter


def get_fanfiction_metadata(url: str) -> dict:
    """Fetch metadata for a FanFiction.Net story."""
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(url)
    if resp.status_code != 200:
        raise ValueError(f"Failed to fetch url {url}: {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    metadata: dict[str, str | int] = {}

    profile = soup.find("div", id="profile_top")
    if profile:
        title_tag = profile.find("b", class_="xcontrast_txt")
        if title_tag:
            metadata["title"] = title_tag.text.strip()
        author_tag = profile.find("a", class_="xcontrast_txt")
        if author_tag:
            metadata["author"] = author_tag.text.strip()
        img_tag = profile.find("img")
        if img_tag:
            metadata["cover_image"] = img_tag.get("src")

    select_tag = soup.find("select", id="chap_select")
    if select_tag:
        metadata["numChapters"] = len(select_tag.find_all("option"))
    else:
        metadata["numChapters"] = 1

    return metadata


def download_fanfiction_chapter(
    url: str,
    output_dir: str,
    username: str,
    library: str,
    story_name: str,
    format_type: str = "txt",
    chapter_number: int = 1,
) -> bool:
    """Download a single chapter using FanFicFare with Cloudflare bypass."""
    os.makedirs(output_dir, exist_ok=True)
    story_path = os.path.join(output_dir, username, str(library), story_name)
    os.makedirs(story_path, exist_ok=True)

    config = Configuration(["defaults.ini"], "DEFAULTS")
    if not config.has_section("overrides"):
        config.add_section("overrides")
    config.set("overrides", "use_cloudscraper", "true")

    adapter = getAdapter(config, url)
    adapter.setChaptersRange(chapter_number, chapter_number)
    adapter.getStoryMetadataOnly()
    writer = getWriter(format_type, config, adapter)

    outfile = os.path.join(story_path, f"chapter_{chapter_number}.{format_type}")
    writer.writeStory(outstream=open(outfile, "wb"))
    return os.path.exists(outfile) and os.path.getsize(outfile) > 0
