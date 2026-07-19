import os


# Set this before any test module imports the application's database settings.
os.environ["DATABASE_URL"] = "sqlite:///./test.db"
