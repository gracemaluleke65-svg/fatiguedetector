FROM python:3.11-slim-bullseye

# Install system dependencies for dlib and OpenCV
RUN apt-get update && apt-get install -y \
    cmake \
    libopenblas-dev \
    liblapack-dev \
    libx11-dev \
    libgtk-3-dev \
    libboost-python-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest
COPY . .

# Download shape predictor if not exists
RUN if [ ! -f shape_predictor_68_face_landmarks.dat ]; then \
    apt-get update && apt-get install -y wget && \
    wget http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2 && \
    apt-get install -y bzip2 && \
    bzip2 -d shape_predictor_68_face_landmarks.dat.bz2 && \
    rm -rf /var/lib/apt/lists/*; \
    fi

# Expose port
EXPOSE 10000

# Use gunicorn with eventlet worker
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:10000", "app:app"]