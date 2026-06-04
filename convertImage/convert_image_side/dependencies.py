"""Optional third-party dependencies used by the GUI."""

DND_OK = False
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES

    DND_OK = True
except Exception:
    TkinterDnD = None
    DND_FILES = None


TINIFY_OK = False
try:
    from tinify_async_compress import TinifyAsyncCompressor, Config, TinyReqMode, CompressResult

    TINIFY_OK = True
except Exception:
    TinifyAsyncCompressor = None
    Config = None
    TinyReqMode = None
    CompressResult = None
    TINIFY_OK = False

