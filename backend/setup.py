from setuptools import setup, find_packages

setup(
    name="nexus-novel",
    version="0.1.0",
    packages=find_packages(include=["app", "app.*", "config", "config.*"]),
    install_requires=[
        "sqlalchemy",
        "alembic",
        "python-dotenv",
    ],
    python_requires=">=3.8",
    author="Your Name",
    author_email="your.email@example.com",
    description="A novel management system",
)

