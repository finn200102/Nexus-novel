import requests
from bs4 import BeautifulSoup

def get_royalroad_cover_image(fiction_url):
    headers = {'User-Agent': 'Mozilla/5.0'}  # avoid bot detection
    response = requests.get(fiction_url, headers=headers)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, 'html.parser')

    # Find the img tag with the specific classes
    img_tag = soup.find('img', class_='thumbnail inline-block')

    if img_tag and 'src' in img_tag.attrs:
        return img_tag['src']
    else:
        return None

if __name__ == "__main__":
    # Example usage
    url = "https://www.royalroad.com/fiction/36735/the-perfect-run"
    image_url = get_royalroad_cover_image(url)
    print("Cover image URL:", image_url)
