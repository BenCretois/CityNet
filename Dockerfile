FROM python:3.7

RUN pip install pdm
WORKDIR /app
COPY pyproject.toml pdm.lock /app
RUN pdm install --no-self

COPY entrypoint.sh /app
ENTRYPOINT ["/app/entrypoint.sh"]
