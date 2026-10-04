# Running Pocketful (stage 1)

Build and start the service in one command, from the repository root:

```sh
docker build -t pocketful stage-1 && docker run --rm -p 8080:8080 -e PORT=8080 pocketful
```

The service listens on `0.0.0.0:$PORT` (default `8080`); `GET /health` returns
`{"status": "ok"}` once it is up. It needs no network access at run time and keeps
all state in memory; seed it with `POST /_test/reset`.

Unit tests (host, Python 3.12, stdlib only), from `stage-1/`:

```sh
python3.12 -m unittest
```
