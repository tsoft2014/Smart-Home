FROM python:3.11-slim

# Установка системных зависимостей, необходимых для Android-сборки и Java
RUN apt-get update && apt-get install -y \
    git zip unzip openjdk-17-jdk autoconf libtool pkg-config \
    zlib1g-dev libncurses5-dev libncursesw5-dev libffi-dev \
    libssl-dev cmake build-essential sudo && \
    rm -rf /var/lib/apt/lists/*

# Создаем рабочего пользователя
RUN useradd -ms /bin/bash user
USER user
WORKDIR /home/user/hostcwd

# Обновляем pip и устанавливаем стабильный buildozer вместе с совместимым Cython
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
RUN pip install --no-cache-dir buildozer cython==3.0.11
