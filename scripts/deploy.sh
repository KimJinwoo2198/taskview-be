#!/bin/sh
set -eu

cd "$(dirname "$0")/.."

if [ ! -f .env.deploy ]; then
  echo ".env.deploy 파일이 없습니다. .env.deploy.example을 복사하고 배포 값을 설정하세요." >&2
  exit 1
fi

docker compose --env-file .env.deploy -f compose.deploy.yaml up -d --build
docker compose --env-file .env.deploy -f compose.deploy.yaml ps
