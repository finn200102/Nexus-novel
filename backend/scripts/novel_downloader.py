import os
from fanficfare.adapters import getAdapter
from fanficfare.configurable import Configuration
from fanficfare.writers import getWriter

def download_novel_chapter(url, output_dir, story_name, username, library, format_type="txt", chapter_number=1):
    # Ensure the main directory exists
    os.makedirs(output_dir, exist_ok=True)

    story_folder = f"{story_name}"
    story_path = os.path.join(output_dir, story_folder)
    os.makedirs(story_path, exist_ok=True)

    # Get absolute path for story directory
    abs_story_path = os.path.abspath(story_path)
    
    abs_story_path = os.path.join(abs_story_path, username)
    abs_story_path = os.path.join(abs_story_path, library)
    os.makedirs(abs_story_path, exist_ok=True)

    # Define output filename
    output_filename = f"chapter_{chapter_number}.{format_type}"

    # Create a basic configuration
    configuration = Configuration(["defaults.ini"], "DEFAULTS")

    # Initialize the appropriate adapter for the URL
    adapter = getAdapter(configuration, url)

    # Set the chapter range
    adapter.setChaptersRange(chapter_number, chapter_number)

    # Fetch the story metadata
    adapter.getStoryMetadataOnly()

    # Get the writer for the specified format
    writer = getWriter(format_type, configuration, adapter)

    # Open the file in binary mode instead of text mode
    writer.writeStory(outstream=open(os.path.join(abs_story_path, output_filename), 'wb'))

    # Check if file was successfully created
    success = os.path.exists(os.path.join(abs_story_path, output_filename)) and os.path.getsize(os.path.join(abs_story_path, output_filename)) > 0

    return success
