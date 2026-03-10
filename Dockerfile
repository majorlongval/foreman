FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run seed_agent by default. Override with FOREMAN_AGENT env var.
# Options: seed_agent, implement_agent, review_agent, foreman_brain
ENV FOREMAN_AGENT=seed_agent
CMD python ${FOREMAN_AGENT}.py
