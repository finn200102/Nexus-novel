from fastapi import status


class NexusNovelException(Exception):
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class MetadataServerError(NexusNovelException):
    def __init__(self, message: str = "Metadata server error"):
        super().__init__(message, status.HTTP_503_SERVICE_UNAVAILABLE)


class NovelNotFoundError(NexusNovelException):
    def __init__(self, novel_id: int):
        super().__init__(
            f"Novel with ID {novel_id} not found", status.HTTP_404_NOT_FOUND
        )


class ChapterNotFoundError(NexusNovelException):
    def __init__(self, chapter_id: int):
        super().__init__(
            f"Chapter with ID {chapter_id} not found", status.HTTP_404_NOT_FOUND
        )


class ValidationError(NexusNovelException):
    def __init__(self, message: str):
        super().__init__(message, status.HTTP_400_BAD_REQUEST)


class LibraryNotFoundError(NexusNovelException):
    def __init__(self, library_id: int):
        super().__init__(
            f"Library with ID {library_id} not found", status.HTTP_404_NOT_FOUND
        )


class ForbiddenError(NexusNovelException):
    def __init__(self, message: str = "You don't have permission for this resource"):
        super().__init__(message, status.HTTP_403_FORBIDDEN)
