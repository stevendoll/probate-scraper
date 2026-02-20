FROM python:3.12-slim

# Install Chromium and ChromeDriver from Debian repos.
# Using the system packages avoids version-mismatch issues between
# the browser binary and the driver.
RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-driver \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Tell the scraper where to find the binaries
ENV CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py scraper.py dynamo.py ./

CMD ["python", "app.py"]
