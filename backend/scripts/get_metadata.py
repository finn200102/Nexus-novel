# get_metadata.py
import os
import sys
from scripts.get_cover_image import get_royalroad_cover_image
from fanficfare.adapters import getAdapter
from fanficfare.configurable import Configuration


def get_story_metadata(url):
    # Create a basic configuration
    configuration = Configuration(["defaults.ini"], "DEFAULTS")

    # Initialize the appropriate adapter for the URL
    adapter = getAdapter(configuration, url)

    # Fetch just the metadata
    adapter.getStoryMetadataOnly()

    # Get the metadata as a dictionary
    metadata = adapter.getStoryMetadataOnly().getAllMetadata()
    if "royal" in url:
        cover_url = get_royalroad_cover_image(url)
        metadata["cover_image"] = cover_url

    return parse_metadata(metadata)


def parse_metadata(metadata):
    """
    Parse the following metadata fields:
    genre, author, series, numChapters, title,
    description, langcode, cover_image
    """

    keys = ['genre', 'author', 'series', 'numChapters',
            'title', 'description', 'langcode', 'cover_image', 'numChapters']
    parsed_metadata = {} 

    for key in keys:
        if key in metadata:
            parsed_metadata[key] = metadata[key]
            
        # if key == 'genre' and isinstance(metadata[key], str):
        #     try:
        #         genres = metadata[key].split("'")
        #         genres = [g.strip() for g in genres]

    return parsed_metadata
            
            
                
            
