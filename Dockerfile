FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run seed_agent by default. Override with FOREMAN_AGENT=review_agent
ENV FOREMAN_AGENT=seed_agent
CMD python ${FOREMAN_AGENT}.py
