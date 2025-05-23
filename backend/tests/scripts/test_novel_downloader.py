import os
from scripts.novel_downloader import download_novel_chapter

def test_download_novel_chapter():
    OUTPUT_DIR = "downloads"
    URL = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    CHAPTER = 1
    FORMAT = "txt"
    STORY_NAME = "mother-of-learning"

    story_folder = f"{STORY_NAME}"
    story_path = os.path.join(OUTPUT_DIR, story_folder)

    # Run the download function
    success = download_novel_chapter(URL, OUTPUT_DIR, STORY_NAME, FORMAT, CHAPTER)

    # Assert that the download was successful
    assert success, "Download function did not return success"

    # Check if the story directory exists
    assert os.path.exists(story_path), f"Story directory {story_path} not found"

    # Check for the file in the story directory
    found_file = False
    expected_pattern = f"chapter_{CHAPTER}.{FORMAT}"

    for file in os.listdir(story_path):
        if expected_pattern in file:
            found_file = True
            file_path = os.path.join(story_path, file)
            assert os.path.getsize(file_path) > 0, f"File {file_path} is empty"
            break

    assert found_file, f"No file with pattern {expected_pattern} found in {story_path}"

"""
def test_download_novel_chapter_spacebattles():
    OUTPUT_DIR = "downloads"
    URL = "https://forums.spacebattles.com/threads/beware-of-chicken-xianxia.910799/"
    CHAPTER = 1
    FORMAT = "txt"
    STORY_NAME = "beware-of-chicken"

    story_folder = f"{STORY_NAME}"
    story_path = os.path.join(OUTPUT_DIR, story_folder)

    # Run the download function
    success = download_novel_chapter(URL, OUTPUT_DIR, STORY_NAME, FORMAT, CHAPTER)

    # Assert that the download was successful
    assert success, "Download function did not return success"

    # Check if the story directory exists
    assert os.path.exists(story_path), f"Story directory {story_path} not found"

    # Check for the file in the story directory
    found_file = False
    expected_pattern = f"chapter_{CHAPTER}.{FORMAT}"

    for file in os.listdir(story_path):
        if expected_pattern in file:
            found_file = True
            file_path = os.path.join(story_path, file)
            assert os.path.getsize(file_path) > 0, f"File {file_path} is empty"
            break

    assert found_file, f"No file with pattern {expected_pattern} found in {story_path}"
"""
