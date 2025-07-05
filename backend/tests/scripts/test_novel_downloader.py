import os

from scripts.novel_downloader import download_novel_chapter


def test_download_novel_chapter():
    OUTPUT_DIR = "downloads"
    URL = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    CHAPTER = 1
    FORMAT = "txt"
    STORY_NAME = "mother-of-learning"

    # These are test-only parameters for creating the subdirectory structure
    username = FORMAT
    library = CHAPTER

    # Expected save path
    story_path = os.path.join(OUTPUT_DIR, STORY_NAME, FORMAT, str(CHAPTER))

    # Run the download function
    success = download_novel_chapter(
        URL, OUTPUT_DIR, STORY_NAME, username, library, FORMAT, CHAPTER
    )

    assert success, "Download function did not return success"
    assert os.path.exists(story_path), f"Story directory {story_path} not found"

    # Check for expected file
    expected_filename = f"chapter_{CHAPTER}.{FORMAT}"
    expected_file_path = os.path.join(story_path, expected_filename)
    assert os.path.isfile(
        expected_file_path
    ), f"Expected file not found: {expected_file_path}"
    assert (
        os.path.getsize(expected_file_path) > 0
    ), f"File is empty: {expected_file_path}"


def test_download_multiple_novel_chapters():
    test_cases = [
        {
            "url": "https://www.novelall.com/novel/Dragon-Marked-War-God.html",
            "story_name": "dragon-marked-war-god",
            "chapters": [1, 2],
            "format": "txt",
        },
        {
            "url": "https://archiveofourown.org/works/4701869/chapters/10736366",
            "story_name": "OhGodNotAgain",
            "chapters": [1],
            "format": "txt",
        },
    ]

    OUTPUT_DIR = "downloads"

    for case in test_cases:
        for chapter in case["chapters"]:
            story_path = os.path.join(
                OUTPUT_DIR, case["story_name"], case["format"], str(chapter)
            )

            success = download_novel_chapter(
                case["url"],
                OUTPUT_DIR,
                case["story_name"],
                case["format"],  # Used as `username` in test
                chapter,  # Used as `library` in test
                case["format"],
                chapter,
            )

            assert (
                success
            ), f"Download failed for {case['story_name']} Chapter {chapter}"
            assert os.path.exists(story_path), f"Story directory {story_path} not found"

            expected_filename = f"chapter_{chapter}.{case['format']}"
            expected_file_path = os.path.join(story_path, expected_filename)
            assert os.path.isfile(
                expected_file_path
            ), f"Expected file not found: {expected_file_path}"
            assert (
                os.path.getsize(expected_file_path) > 0
            ), f"File is empty: {expected_file_path}"
