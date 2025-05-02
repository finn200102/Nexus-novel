import requests
from bs4 import BeautifulSoup

def get_royalroad_trending():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = "https://www.royalroad.com/fictions/trending"
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')
    stories = []

    for item in soup.select('.fiction-list-item'):
        cover_tag = item.select_one('figure img')
        title_tag = item.select_one('.fiction-title a')

        if cover_tag and title_tag:
            # Fetch correct src (cover image)
            cover_url = cover_tag.get('src')
            # Fall back to other lazy-load sources if necessary
            if not cover_url or 'nocover' in cover_url:
                cover_url = cover_tag.get('data-src') or cover_tag.get('data-original')

            title = title_tag.text.strip()
            story_url = "https://www.royalroad.com" + title_tag.get('href')

            stories.append({
                'title': title,
                'url': story_url,
                'cover_image': cover_url
            })

    return stories

if __name__ == "__main__":
    stories = get_royalroad_trending()
    for story in stories:
        print(f"{story['title']}\n  URL: {story['url']}\n  Cover: {story['cover_url']}\n")
