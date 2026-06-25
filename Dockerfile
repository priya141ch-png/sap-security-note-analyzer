FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (no pyrfc — RFC goes via relay client on user's laptop)
RUN pip install --no-cache-dir \
    streamlit==1.36.0 \
    pandas==2.2.2 \
    plotly==5.22.0 \
    openpyxl==3.1.5 \
    reportlab==4.2.2 \
    lxml==5.2.2 \
    beautifulsoup4==4.12.3 \
    pycryptodome==3.20.0 \
    PyPDF2==3.0.1 \
    pdfplumber==0.11.4 \
    bcrypt==4.2.0 \
    "cryptography>=42.0.0" \
    fastapi \
    "uvicorn[standard]" \
    requests

COPY . .

RUN mkdir -p user_data/profiles user_data/note_cache logs runs

EXPOSE 8501 8502

RUN chmod +x start_gcp.sh
CMD ["/bin/bash", "start_gcp.sh"]
