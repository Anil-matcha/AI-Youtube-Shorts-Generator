import os
import unittest


class FaceDetectorSmokeTests(unittest.TestCase):
    def test_haar_cascade_initializes(self):
        import cv2

        cascade_path = os.path.join(
            cv2.data.haarcascades,
            "haarcascade_frontalface_default.xml",
        )
        self.assertTrue(hasattr(cv2, "CascadeClassifier"))
        self.assertTrue(os.path.isfile(cascade_path))

        detector = cv2.CascadeClassifier(cascade_path)
        self.assertFalse(detector.empty())


