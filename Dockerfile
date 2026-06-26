# SUTD Survival Guide — unified Telegram bot.
# The bot lives in sutd_survival_guide/ but imports the gym tracker from a
# sibling app, so the build context is the repo root.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Singapore

WORKDIR /app

# Install deps first so this layer is cached unless requirements change.
COPY sutd_survival_guide/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code + the sibling apps the bot imports from / migrates.
COPY sutd_survival_guide/ ./sutd_survival_guide/
COPY aloysius_gym_crowd_tracker/ ./aloysius_gym_crowd_tracker/
COPY dylan_deadline_notifier/ ./dylan_deadline_notifier/

# Persisted state (SQLite DB + gym counts) lives on a mounted volume here.
# settings.py reads these env vars and falls back to in-repo paths locally.
RUN mkdir -p /data
ENV DEADLINE_DB_FILE=/data/deadlines.db \
    GYM_DATA_FILE=/data/gym_data.json

WORKDIR /app/sutd_survival_guide
CMD ["python", "bot.py"]
