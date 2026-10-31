"""Analisi automatica di ortofoto di prospetto e restituzione in DXF (mm interi)."""
import os

# Le ortofoto di RealityScan superano facilmente il limite di OpenCV (2^30 pixel).
os.environ.setdefault("OPENCV_IO_MAX_IMAGE_PIXELS", str(2 ** 40))

__version__ = "0.1.1"
