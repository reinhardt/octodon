class NotFound(Exception):
    """Resource could not be located"""

    def __init__(self, status_code=-1, text=""):
        self.status_code = status_code
        self.text = text


class ConnectionError(Exception):
    """Problem while connecting to remote host"""
