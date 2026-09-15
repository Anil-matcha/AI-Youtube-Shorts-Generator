# CPU arm64 container support

The CPU image is published for `linux/amd64` and `linux/arm64`. The image
selects its dependency lock at build time using BuildKit's `TARGETARCH`:

- amd64 installs `requirements-docker.txt`, including faster-whisper;
- arm64 installs `requirements-docker-arm64.txt`, which contains every web,
  API, download, export, and OpenCV dependency that has a manylinux arm64
  wheel.

The faster-whisper 1.2.1 dependency chain currently requires `onnxruntime`,
which does not publish a compatible manylinux arm64 wheel on PyPI. Therefore
local Whisper transcription is intentionally unavailable in the arm64 image;
use API mode there, or run local mode on amd64 until upstream publishes the
needed wheel. The application returns the normal missing-local-dependency
message instead of silently falling back.

The audit used Python 3.12 / CP312 and the `manylinux_2_17_aarch64` target:

```text
python -m pip download --only-binary=:all: \
  --platform manylinux_2_17_aarch64 --implementation cp \
  --python-version 312 --abi cp312 -r requirements-docker-arm64.txt
```

The command resolved 43 wheels, including OpenCV 4.13.0.92, Pillow 12.2.0,
NumPy, FastAPI, Uvicorn, OpenAI, Google GenAI, and their transitive packages.
The Docker workflow performs the actual multi-architecture build and push;
Docker Buildx is not required on a developer workstation.
