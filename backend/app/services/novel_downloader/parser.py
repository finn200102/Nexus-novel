def parse_novel_data(py_story):
    """
    Parses a PyStory object into a novel_data format.
    """

    novel_data = {
        "title": py_story.story_name,
        "site": py_story.site,
        "description": py_story.description,
        "site_story_id": py_story.story_id,
    }

    return novel_data


def parse_author_data(py_story):
    """
    Parse a PyStory object into a author_data format.
    """

    author_data = {
        "name": py_story.author_name,
        "site_author_id": py_story.author_id,
    }

    return author_data


def parse_chapter_data(py_story):
    """
    Parse a PyStory object into a list(chapter_data) format.
    """

    chapter_data_list = []

    for chapter in py_story.chapters:
        chapter_data = {
            "title": chapter.title,
            "content": chapter.text,
            "chapter_number": chapter.chapter_number,
            "site_chapter_id": chapter.chapter_id,
            "content_status": "MISSING",
        }

        chapter_data_list.append(chapter_data)

    return chapter_data_list


def parse_single_chapter_data(py_story):
    """
    Parse a PyStory object into a list(chapter_data) format.
    """

    chapter_data = {
        "content": py_story.text,
    }

    return chapter_data
