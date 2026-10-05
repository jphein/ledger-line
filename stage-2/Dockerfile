# Pocketful stage 1: Python 3.12 stdlib only; no packages are installed.
FROM python:3.12-alpine
WORKDIR /app
COPY pocketful ./pocketful
ENV PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8080
CMD ["python", "-m", "pocketful.server"]
