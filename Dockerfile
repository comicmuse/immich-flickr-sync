FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
VOLUME ["/app/data"]
ENTRYPOINT ["immich-flickr-sync"]
CMD ["run", "--config", "/app/data/config.yaml"]
