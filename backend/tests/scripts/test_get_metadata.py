import os
import pytest
from scripts.get_metadata import get_story_metadata

def test_get_story_metadata():
    # URL for Mother of Learning
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"

    try:
        # Get the metadata
        metadata = get_story_metadata(url)

        # Now you have the metadata in the 'metadata' variable
        print("Metadata retrieved successfully!")

        print(metadata)

    except Exception as e:
        print(f"Error retrieving metadata: {e}")
