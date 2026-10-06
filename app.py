import base64
import json
import os
import re
import subprocess
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# =========================
# SETTINGS
# =========================

OUT = Path("output")
OUT.mkdir(exist_ok=True)

TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-6-astra")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2.5-sunburst")
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

TOPIC = os.getenv("VIDEO_TOPIC", "Indian horror stories")
LANGUAGE = os.getenv("VIDEO_LANGUAGE", "Hindi")
SCENES = int(os.getenv("VIDEO_SCENES", "8"))

PRIVACY = os.getenv("VIDEO_PRIVACY", "private")
CATEGORY = os.getenv("YOUTUBE_CATEGORY_ID", "24")

client = OpenAI(api
