# Running Pocketful (stage 2)

Build and start the service in one command, from the repository root:

```sh
docker build -t pocketful stage-2 && docker run --rm -p 8080:8080 -e PORT=8080 pocketful
```

The service listens on `0.0.0.0:$PORT` (default `8080`). `GET /health` returns
`{"status": "ok"}` once it is up. Open `http://localhost:8080/` in a browser for the
wallet UI; every asset is served from the image and nothing is fetched from the
network at run time. State is in memory; seed it with `POST /_test/reset`.

Unit tests (host, Python 3.12, stdlib only), from `stage-2/`:

```sh
python3.12 -m unittest
```
