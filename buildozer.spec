name: Build Kivy APK

on:
  push:
    branches: [ "main" ]
  workflow_dispatch:

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Build APK with Docker (Official Kivy Image)
        run: |
          docker run --rm \
            -v ${{ github.workspace }}:/home/user/hostpython \
            kivy/buildozer android debug

      - name: Upload APK Artifact
        uses: actions/upload-artifact@v4
        with:
          name: python-kivy-apk
          path: bin/*.apk
