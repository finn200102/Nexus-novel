import os
import sys
import subprocess

def download_novel_chapter(url, output_dir, story_name, format_type="txt", chapter_number=1):
    # Ensure the main directory exists
    os.makedirs(output_dir, exist_ok=True)

    story_folder = f"{story_name}"
    story_path = os.path.join(output_dir, story_folder)
    os.makedirs(story_path, exist_ok=True)

    # Get absolute path for story directory
    abs_story_path = os.path.abspath(story_path)

    # Define output filename
    output_filename = f"chapter_{chapter_number}.{format_type}"

    # Use the Python interpreter from the active venv
    venv_python = sys.executable

    # Change current working directory to the target directory
    # This is the key fix - FanFicFare often writes to current directory
    original_dir = os.getcwd()
    os.chdir(abs_story_path)

    try:
        # Base command with simplified options
        cmd = [
            venv_python, "-m", "fanficfare.cli",
            "-f", format_type,
            "-b", str(chapter_number),
            "-e", str(chapter_number),
            "--force",
            "-o", f"output_filename={output_filename}",
            url
        ]

        # Run the command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )

        # Print output for debugging
        print(f"Command output: {result.stdout}")
        if result.stderr:
            print(f"Command error: {result.stderr}")

        # Check if file was successfully created
        expected_file = os.path.join(abs_story_path, output_filename)
        success = os.path.exists(expected_file) and os.path.getsize(expected_file) > 0

        return success

    finally:
        # Return to original directory
        os.chdir(original_dir)
